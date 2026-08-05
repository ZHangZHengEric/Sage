import { describe, expect, it } from 'vitest'

import {
  mergeStreamedText,
  mergeToolFunctionArguments
} from '../mergeToolFunctionArguments.js'

describe('mergeStreamedText', () => {
  it('supports deltas, cumulative snapshots, and empty tool-call patches', () => {
    const complete = '命令被安全策略拦截，我改用脚本文件方式验证。'

    expect(mergeStreamedText('命令', '被安全策略拦截')).toBe('命令被安全策略拦截')
    expect(mergeStreamedText('哈', '哈')).toBe('哈哈')
    expect(mergeStreamedText('命令', complete, true)).toBe(complete)
    expect(mergeStreamedText(complete, complete, true)).toBe(complete)
    expect(mergeStreamedText(complete, null)).toBe(complete)
    expect(mergeStreamedText(complete, '')).toBe(complete)
    expect(mergeStreamedText([{ type: 'text', text: complete }], null)).toEqual([
      { type: 'text', text: complete }
    ])
  })
})

describe('mergeToolFunctionArguments streaming', () => {
  it('merges incremental arguments without discarding prior data', () => {
    expect(mergeToolFunctionArguments('{"a":', '"1"}')).toBe('{"a":"1"}')
    expect(mergeToolFunctionArguments('{"a":1}', {})).toBe('{"a":1}')
  })
})
