import { describe, expect, it } from 'vitest'

import {
  THINKING_LEVEL_OPTIONS,
  getDefaultThinkingLevel,
  getThinkingLevelOptions
} from '../modelCapabilities.js'

describe('modelCapabilities', () => {
  it('exposes the same five frontend levels for every configured model', () => {
    const expected = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max']

    expect(THINKING_LEVEL_OPTIONS).toEqual(expected)
    for (const model of ['gpt-5.4', 'deepseek-v4-flash', 'qwen3.8-max-preview', 'gpt-4o']) {
      expect(getThinkingLevelOptions(model)).toEqual(expected)
    }
  })

  it('defaults every configured model to medium', () => {
    expect(getDefaultThinkingLevel('gpt-5.4')).toBe('medium')
    expect(getDefaultThinkingLevel('deepseek-v4-flash')).toBe('medium')
  })

  it('keeps the five-level selector independent from model metadata', () => {
    expect(getDefaultThinkingLevel('')).toBe('medium')
    expect(getThinkingLevelOptions(null)).toEqual(THINKING_LEVEL_OPTIONS)
  })
})
