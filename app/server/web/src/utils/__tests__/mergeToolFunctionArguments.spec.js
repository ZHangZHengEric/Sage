import { describe, it, expect } from 'vitest'
import {
  mergeStreamedText,
  mergeToolFunctionArguments
} from '../mergeToolFunctionArguments.js'

describe('mergeStreamedText', () => {
  it('appends incremental text chunks', () => {
    expect(mergeStreamedText('命令', '被安全策略拦截')).toBe('命令被安全策略拦截')
    expect(mergeStreamedText('哈', '哈')).toBe('哈哈')
  })

  it('keeps a cumulative final snapshot without duplicating it', () => {
    const complete = '命令被安全策略拦截，我改用脚本文件方式验证。'
    expect(mergeStreamedText('命令', complete, true)).toBe(complete)
    expect(mergeStreamedText(complete, complete, true)).toBe(complete)
  })

  it('does not erase existing text with an empty tool-call patch', () => {
    expect(mergeStreamedText('完整内容', null)).toBe('完整内容')
    expect(mergeStreamedText('完整内容', '')).toBe('完整内容')
    expect(mergeStreamedText([{ type: 'text', text: '完整内容' }], null)).toEqual([
      { type: 'text', text: '完整内容' }
    ])
  })
})

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
