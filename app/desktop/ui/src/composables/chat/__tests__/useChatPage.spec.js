import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'

const streamHarness = vi.hoisted(() => ({ handleMessage: null }))

const workbenchStore = vi.hoisted(() => ({
  items: [],
  filteredItems: [],
  isRealtime: true,
  consumeGuidance: vi.fn(),
  appendToolProgress: vi.fn(),
  extractFromMessage: vi.fn(),
  updateToolResult: vi.fn(),
  resetState: vi.fn(),
  setSessionId: vi.fn(),
  clearItems: vi.fn(),
  setCurrentIndex: vi.fn(),
  setRealtime: vi.fn()
}))

const panelStore = vi.hoisted(() => ({
  showWorkbench: false,
  activePanel: null,
  openWorkbench: vi.fn(),
  openWorkspace: vi.fn(),
  openSettings: vi.fn(),
  closeAll: vi.fn()
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ replace: vi.fn() })
}))

vi.mock('vue-sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() }
}))

vi.mock('@/utils/i18n.js', async () => {
  const { ref } = await import('vue')
  return { useLanguage: () => ({ t: key => key, language: ref('zh-CN') }) }
})

vi.mock('@/api/chat.js', () => ({ chatAPI: {} }))
vi.mock('@/api/agent.js', () => ({ agentAPI: { getAgentAbilities: vi.fn() } }))

vi.mock('@/composables/chat/useChatActiveSessionCache.js', async () => {
  const { ref } = await import('vue')
  return {
    useChatActiveSessionCache: () => ({
      activeSessions: ref({}),
      handleActiveSessionsUpdated: vi.fn(),
      getSessionLastIndex: vi.fn(() => 0),
      updateActiveSessionLastIndex: vi.fn(),
      updateActiveSession: vi.fn(),
      markSessionInterrupted: vi.fn(),
      removeSessionFromCache: vi.fn(),
      deriveSessionTitle: vi.fn(),
      startSSESync: vi.fn(),
      stopSSESync: vi.fn()
    })
  }
})

vi.mock('@/composables/chat/useChatScroll.js', async () => {
  const { ref } = await import('vue')
  return {
    useChatScroll: () => ({
      messagesListRef: ref(null),
      messagesEndRef: ref(null),
      shouldAutoScroll: ref(true),
      scrollToBottom: vi.fn(),
      handleScroll: vi.fn(),
      clearScrollTimer: vi.fn()
    })
  }
})

vi.mock('@/composables/chat/useChatStream.js', () => ({
  useChatStream: options => {
    streamHarness.handleMessage = options.handleMessage
    return {
      handleSessionLoad: vi.fn(),
      handleSendMessage: vi.fn(),
      stopGeneration: vi.fn(),
      rerunSession: vi.fn()
    }
  }
}))

vi.mock('@/composables/chat/useChatLifecycle.js', () => ({
  useChatLifecycle: vi.fn()
}))

vi.mock('@/composables/chat/useChatAgentConfig.js', async () => {
  const { ref } = await import('vue')
  return {
    useChatAgentConfig: () => ({
      agents: ref([]),
      selectedAgent: ref(null),
      selectedAgentId: ref(null),
      config: ref({}),
      selectAgent: vi.fn(),
      updateConfig: vi.fn(),
      restoreSelectedAgent: vi.fn(),
      loadAgents: vi.fn(),
      handleAgentChange: vi.fn()
    })
  }
})

vi.mock('@/composables/chat/useChatWorkspace.js', async () => {
  const { ref } = await import('vue')
  return {
    useChatWorkspace: () => ({
      showWorkspace: ref(false),
      workspaceFiles: ref([]),
      isWorkspaceLoading: ref(false),
      handleWorkspacePanel: vi.fn(),
      downloadWorkspaceFile: vi.fn(),
      downloadFile: vi.fn(),
      deleteFile: vi.fn(),
      clearTaskAndWorkspace: vi.fn(),
      refreshWorkspace: vi.fn()
    })
  }
})

vi.mock('@/stores/workbench.js', () => ({ useWorkbenchStore: () => workbenchStore }))
vi.mock('@/stores/panel.js', () => ({ usePanelStore: () => panelStore }))

import { useChatPage } from '../useChatPage.js'

describe('useChatPage assistant stream rendering', () => {
  let wrapper

  beforeEach(() => {
    vi.useFakeTimers()
    streamHarness.handleMessage = null
    workbenchStore.items = []
    workbenchStore.filteredItems = []
  })

  afterEach(() => {
    wrapper?.unmount()
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('keeps all buffered content when a tool-call patch arrives', () => {
    let page
    wrapper = mount(defineComponent({
      setup () {
        page = useChatPage({})
        return () => null
      }
    }))
    page.currentSessionId.value = 'session-1'

    const fullContent = '命令被安全策略拦截，我改用脚本文件方式验证。'
    streamHarness.handleMessage({
      role: 'assistant',
      content: fullContent,
      message_id: 'message-1',
      session_id: 'session-1',
      type: 'assistant'
    })

    vi.advanceTimersByTime(16)
    expect(page.filteredMessages.value[0].content).not.toBe(fullContent)

    streamHarness.handleMessage({
      role: 'assistant',
      content: fullContent,
      message_id: 'message-1',
      session_id: 'session-1',
      type: 'tool_call',
      tool_calls: [{
        id: 'call-1',
        index: 0,
        type: 'function',
        function: { name: 'file_write', arguments: '{}' }
      }]
    })

    expect(page.filteredMessages.value[0].content).toBe(fullContent)
    expect(page.filteredMessages.value[0].tool_calls).toHaveLength(1)
  })
})
