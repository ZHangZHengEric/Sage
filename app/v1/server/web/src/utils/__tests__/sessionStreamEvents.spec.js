import { describe, expect, it } from 'vitest'

import {
  getSessionMessageIndexKey,
  isCurrentSessionStreamEnd
} from '../sessionStreamEvents.js'

describe('sessionStreamEvents', () => {
  it('only treats stream_end for the active session as current completion', () => {
    expect(isCurrentSessionStreamEnd({
      type: 'stream_end',
      session_id: 'parent'
    }, 'parent')).toBe(true)

    expect(isCurrentSessionStreamEnd({
      type: 'stream_end',
      session_id: 'child'
    }, 'parent')).toBe(false)
  })

  it('separates message index keys by session id', () => {
    expect(getSessionMessageIndexKey({
      session_id: 'parent',
      message_id: 'same'
    })).toBe('parent::same')

    expect(getSessionMessageIndexKey({
      session_id: 'child',
      message_id: 'same'
    })).toBe('child::same')
  })
})
