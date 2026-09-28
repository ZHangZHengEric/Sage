import { describe, expect, it } from 'vitest'

import { normalizeChatMessages } from '../chatDisplayItems.js'

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

  it('filters messages explicitly hidden by backend metadata', () => {
    const source = [
      { message_id: 'u1', role: 'user', content: 'run' },
      {
        message_id: 'hidden-1',
        role: 'assistant',
        content: 'internal correction',
        metadata: { sse_visible: false, llm_scope: 'next_request' }
      }
    ]

    const normalized = normalizeChatMessages(source)
    expect(normalized.map(message => message.message_id)).toEqual(['u1'])
  })
})
