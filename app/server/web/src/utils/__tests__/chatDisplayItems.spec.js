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
})
