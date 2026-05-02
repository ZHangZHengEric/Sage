import { describe, it, expect } from 'vitest'
import { mergeToolFunctionArguments } from '../mergeToolFunctionArguments.js'

describe('mergeToolFunctionArguments streaming', () => {
  it('concatenates string fragments when neither is prefix', () => {
    expect(mergeToolFunctionArguments('{"a":', '"1"}')).toBe('{"a":"1"}')
  })

  it('keeps longer snapshot when chunks are cumulative', () => {
    expect(mergeToolFunctionArguments('{"c":"x"', '{"c":"x","d":true}')).toBe(
      '{"c":"x","d":true}'
    )
  })

  it('does not discard string delta when existing is non-empty object', () => {
    const merged = mergeToolFunctionArguments({ command: 'echo' }, ' hello')
    expect(merged).toBe('{"command":"echo"} hello')
  })

  it('merges stringify(object) with prior string fragments', () => {
    const merged = mergeToolFunctionArguments('{"command":"echo', {
      command: 'echo hello'
    })
    expect(merged.startsWith('{"command":"echo')).toBe(true)
    expect(JSON.parse(merged)).toEqual({ command: 'echo hello' })
  })

  it('empty incoming object preserves existing string', () => {
    expect(mergeToolFunctionArguments('{"a":1}', {})).toBe('{"a":1}')
  })
})
