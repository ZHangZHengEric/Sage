import { describe, it, expect } from 'vitest'
import { extractIncompleteJsonStringField } from '../streamingJsonStringFields.js'

describe('extractIncompleteJsonStringField', () => {
  it('extracts command without closing quote on JSON', () => {
    expect(
      extractIncompleteJsonStringField('{"command":"ls -lah', ['command'])
    ).toBe('ls -lah')
  })

  it('handles escapes', () => {
    expect(extractIncompleteJsonStringField(String.raw`{"command":"a\nb"`, ['command'])).toBe(
      'a\nb'
    )
  })
})
