import { describe, expect, it } from 'vitest'

import { buildDeliveryDisplayItems, normalizeChatMessages } from '../chatDisplayItems.js'

describe('chatDisplayItems normalizeChatMessages', () => {
  it('returns chat messages unchanged', () => {
    const source = [{
      message_id: 'a1',
      role: 'assistant',
      tool_calls: [{
        id: 'tc_read_1',
        type: 'function',
        function: {
          name: 'file_read',
          arguments: '{}'
        }
      }]
    }]

    const normalized = normalizeChatMessages(source)

    expect(normalized).toHaveLength(1)
    expect(normalized[0].tool_calls).toHaveLength(1)
    expect(normalized[0].tool_calls[0].function.name).toBe('file_read')
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

  it('filters messages explicitly hidden by backend metadata', () => {
    const source = [
      { message_id: 'u1', role: 'user', content: 'run' },
      {
        message_id: 'hidden-1',
        role: 'assistant',
        content: 'internal correction',
        metadata: { hidden_from_chat: true, llm_scope: 'next_request' }
      }
    ]

    const normalized = normalizeChatMessages(source)
    expect(normalized.map(message => message.message_id)).toEqual(['u1'])
  })
})
