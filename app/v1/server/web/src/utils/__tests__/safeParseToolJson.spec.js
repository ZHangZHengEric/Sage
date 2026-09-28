import { describe, it, expect } from 'vitest'
import {
  parseToolJsonValue,
  parseToolJsonObjectRecord,
  escapeIllegalNewlinesInJsonStrings
} from '../safeParseToolJson.js'

describe('safeParseToolJson', () => {
  it('parses normal object', () => {
    const s = JSON.stringify({ summary: 'x', tasks: [{ id: '1', name: 'a', status: 'pending' }] })
    const v = parseToolJsonValue(s)
    expect(v.summary).toBe('x')
    expect(v.tasks).toHaveLength(1)
  })

  it('parses double-encoded JSON string', () => {
    const inner = JSON.stringify({ a: 1 })
    const outer = JSON.stringify(inner)
    expect(parseToolJsonValue(outer)).toEqual({ a: 1 })
  })

  it('repairs literal newline inside string value', () => {
    const broken = '{\n  "name": "line1\nline2"\n}'
    expect(JSON.parse.bind(null, broken)).toThrow()
    const fixed = escapeIllegalNewlinesInJsonStrings(broken)
    expect(JSON.parse(fixed).name).toBe('line1\nline2')
    expect(parseToolJsonObjectRecord(broken).name).toBe('line1\nline2')
  })

  it('parseToolJsonObjectRecord returns {} for non-object', () => {
    expect(parseToolJsonObjectRecord('[1]')).toEqual({})
    expect(parseToolJsonObjectRecord('null')).toEqual({})
  })
})
