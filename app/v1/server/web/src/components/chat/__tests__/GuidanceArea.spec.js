import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import GuidanceArea from '../GuidanceArea.vue'
import { chatAPI } from '@/api/chat.js'
import { useLanguageStore } from '@/stores/language.js'
import { useWorkbenchStore } from '@/stores/workbench.js'

vi.mock('@/api/chat.js', () => ({
  chatAPI: {
    updatePendingUserInjection: vi.fn(),
    deletePendingUserInjection: vi.fn(),
  },
}))

const sessionId = 'sess-guidance'

const mountGuidanceArea = (language = 'zhCN', props = {}) => {
  setActivePinia(createPinia())

  const languageStore = useLanguageStore()
  languageStore.setLanguage(language)

  const workbench = useWorkbenchStore()
  workbench.addGuidance(sessionId, {
    guidanceId: 'g1',
    content: '第一条引导',
  })

  const wrapper = mount(GuidanceArea, {
    props: { sessionId, ...props },
  })

  return { wrapper, workbench }
}

describe('GuidanceArea', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('renders queued guidance copy in the current language', () => {
    const { wrapper } = mountGuidanceArea('zhCN')
    expect(wrapper.text()).toContain('1 条待发送引导')

    wrapper.unmount()

    const { wrapper: englishWrapper } = mountGuidanceArea('enUS')
    expect(englishWrapper.text()).toContain('1 queued guidance')
  })

  it('updates pending guidance through the API and local store', async () => {
    chatAPI.updatePendingUserInjection.mockResolvedValue({})
    const { wrapper, workbench } = mountGuidanceArea()

    await wrapper.find('button[title="编辑"]').trigger('click')
    await wrapper.find('textarea').setValue('更新后的引导')
    await wrapper.find('button[title="保存"]').trigger('click')
    await flushPromises()

    expect(chatAPI.updatePendingUserInjection).toHaveBeenCalledWith(
      sessionId,
      'g1',
      '更新后的引导',
    )
    expect(workbench.getGuidances(sessionId)[0].content).toBe('更新后的引导')
  })

  it('calls apply-now handler for a pending guidance item', async () => {
    const applyNowHandler = vi.fn()
    const { wrapper } = mountGuidanceArea('zhCN', { applyNowHandler })

    await wrapper.find('button[title="立即应用"]').trigger('click')

    expect(applyNowHandler).toHaveBeenCalledWith(expect.objectContaining({
      guidanceId: 'g1',
      content: '第一条引导',
    }))
  })

  it('removes guidance locally after delete is requested', async () => {
    chatAPI.deletePendingUserInjection.mockResolvedValue({})
    const { wrapper, workbench } = mountGuidanceArea()

    await wrapper.find('button[title="删除"]').trigger('click')
    await flushPromises()

    expect(chatAPI.deletePendingUserInjection).toHaveBeenCalledWith(sessionId, 'g1')
    expect(workbench.getGuidances(sessionId)).toEqual([])
  })
})
