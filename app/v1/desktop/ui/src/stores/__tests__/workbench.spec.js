import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useWorkbenchStore } from '../workbench.js'

describe('workbench store session isolation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('keeps matching tool calls separate across parent and child sessions', () => {
    const store = useWorkbenchStore()
    store.setSessionId('parent', { autoJumpToLast: false })

    store.addItem({
      type: 'tool_call',
      sessionId: 'parent',
      messageId: 'same-message',
      stableKey: 'tool:same-message:0',
      data: {
        id: 'call_memory',
        function: { name: 'search_memory', arguments: '{}' }
      },
      toolResult: null
    })

    store.addItem({
      type: 'tool_call',
      sessionId: 'child',
      messageId: 'same-message',
      stableKey: 'tool:same-message:0',
      data: {
        id: 'call_memory',
        function: { name: 'search_memory', arguments: '{}' }
      },
      toolResult: null
    })

    expect(store.items).toHaveLength(2)
    expect(store.filteredItems.map(item => item.sessionId)).toEqual(['parent'])

    store.updateToolResult(
      'call_memory',
      { session_id: 'child', content: 'child result' },
      'child'
    )

    const parentItem = store.items.find(item => item.sessionId === 'parent')
    const childItem = store.items.find(item => item.sessionId === 'child')

    expect(parentItem.toolResult).toBeNull()
    expect(childItem.toolResult.content).toBe('child result')

    store.setSessionId('child', { autoJumpToLast: false })
    expect(store.filteredItems.map(item => item.sessionId)).toEqual(['child'])
  })

  it('keeps pending tool progress scoped by session', () => {
    const store = useWorkbenchStore()
    store.setSessionId('parent', { autoJumpToLast: false })

    store.appendToolProgress({
      toolCallId: 'call_memory',
      text: 'child progress',
      sessionId: 'child'
    })

    store.addItem({
      type: 'tool_call',
      sessionId: 'parent',
      data: {
        id: 'call_memory',
        function: { name: 'search_memory', arguments: '{}' }
      },
      toolResult: null
    })

    const parentItem = store.items.find(item => item.sessionId === 'parent')
    expect(parentItem.liveOutput).toBeUndefined()

    store.addItem({
      type: 'tool_call',
      sessionId: 'child',
      data: {
        id: 'call_memory',
        function: { name: 'search_memory', arguments: '{}' }
      },
      toolResult: null
    })

    const childItem = store.items.find(item => item.sessionId === 'child')
    expect(childItem.liveOutput).toBe('child progress')
  })
})
