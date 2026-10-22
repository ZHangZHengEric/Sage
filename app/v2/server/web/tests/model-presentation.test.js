import assert from 'node:assert/strict'
import { test } from 'node:test'
import { modelFieldHelp } from '../src/model-presentation.js'

test('unset output budget explains the active protocol default', () => {
  assert.match(modelFieldHelp('request_max_output_tokens', { protocol: 'anthropic-messages' }), /默认使用 4,096 Token/)
  for (const protocol of ['openai-chat-completions', 'openai-responses', 'gemini-generate-content', 'orcarouter', 'cheaperinference']) {
    assert.match(modelFieldHelp('request_max_output_tokens', { protocol }), /由服务商采用模型默认值/)
  }
})

test('output default reflects the valid capability profile and Anthropic ceiling', () => {
  const profile = { effective_max_output_tokens: 8192 }
  assert.match(modelFieldHelp('request_max_output_tokens', { protocol: 'openai-responses', capability_profile: profile }), /默认使用 8,192 Token/)
  assert.match(modelFieldHelp('request_max_output_tokens', { protocol: 'anthropic-messages', capability_profile: profile }), /默认使用 4,096 Token/)
  assert.match(modelFieldHelp('request_max_output_tokens', { protocol: 'anthropic-messages', capability_profile: { effective_max_output_tokens: 1024 } }), /默认使用 1,024 Token/)
  // Clearing a profile after editing restores the protocol's unprobed default.
  assert.match(modelFieldHelp('request_max_output_tokens', { protocol: 'openai-responses', request: { max_output_tokens: 256 }, capability_profile: null }), /由服务商采用模型默认值/)
})
