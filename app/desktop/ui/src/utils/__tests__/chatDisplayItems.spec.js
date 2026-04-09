import { describe, expect, it } from 'vitest'

import { normalizeChatMessages } from '../chatDisplayItems.js'

describe('chatDisplayItems normalizeChatMessages', () => {
  it('keeps pending sys_finish_task tool calls visible when no tool result exists', () => {
    const source = [{
      message_id: 'a1',
      role: 'assistant',
      tool_calls: [{
        id: 'tc_finish_1',
        type: 'function',
        function: {
          name: 'sys_finish_task',
          arguments: '{}'
        }
      }]
    }]

    const normalized = normalizeChatMessages(source)

    expect(normalized).toHaveLength(1)
    expect(normalized[0].tool_calls).toHaveLength(1)
    expect(normalized[0].tool_calls[0].function.name).toBe('sys_finish_task')
    expect(normalized[0].metadata?.finish_task?.status).toBe('pending')
  })
})
