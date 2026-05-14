import { describe, expect, it } from 'vitest'

import { buildDeliveryDisplayItems, normalizeChatMessages } from '../chatDisplayItems.js'

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

  it('keeps agent_execution_error as a visible assistant message', () => {
    const source = [
      { message_id: 'u1', role: 'user', content: 'run', message_type: 'user_input' },
      {
        message_id: 'a1',
        role: 'assistant',
        content: 'Tool was not provided.',
        type: 'agent_execution_error',
        message_type: 'agent_execution_error'
      }
    ]

    const { items } = buildDeliveryDisplayItems(source)

    const visibleMessage = items.find(item => item.type === 'message' && item.message?.message_id === 'a1')
    expect(visibleMessage?.message.content).toBe('Tool was not provided.')
  })
})
