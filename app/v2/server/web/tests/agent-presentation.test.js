import assert from 'node:assert/strict'
import { test } from 'node:test'
import { agentBudgetPlaceholder, budgetFields } from '../src/agent-presentation.js'
import { modelFieldPlaceholder } from '../src/model-presentation.js'

test('budget placeholders resolve inherited ceilings and the selected model without filling the form', () => {
  const form = { model_id: 'chosen', budgets: {} }
  const models = [{ id: 'chosen', protocol: 'anthropic-messages', limits: { context_window: 200000 }, request: {} }]
  const defaults = { budgets: { max_steps: 18, input_tokens: 64000 }, entrypoint: { config: { max_steps: 40 } } }
  assert.equal(agentBudgetPlaceholder('max_steps', form, models, defaults), '18（系统默认）')
  assert.equal(agentBudgetPlaceholder('input_tokens', form, models, defaults), '64,000（系统默认）')
  assert.equal(agentBudgetPlaceholder('output_tokens', form, models, defaults), '4,096（系统默认）')
  assert.deepEqual(form.budgets, {})
  assert.deepEqual(models[0].request, {})
})

test('retired token sub-budgets are not offered as editable limits', () => {
  const keys = budgetFields.map(field => field.key)
  assert.ok(!keys.includes('system_tokens'))
  assert.ok(!keys.includes('protected_recent_tokens'))
})

test('blank model selection follows the default model and request budget respects probe limits', () => {
  const models = [{ id: 'default', is_default: true, protocol: 'openai-responses', request: { max_output_tokens: 16384 }, limits: { context_window: 16000 }, capability_profile: { effective_max_output_tokens: 8192 } }]
  assert.equal(agentBudgetPlaceholder('output_tokens', {}, models), '8,192（系统默认）')
  assert.equal(agentBudgetPlaceholder('input_tokens', {}, models, { budgets: { input_tokens: 64000 } }), '16,000（系统默认）')
  assert.equal(agentBudgetPlaceholder('output_tokens', {}, models, { budgets: { output_tokens: 1024 } }), '1,024（系统默认）')
  assert.equal(agentBudgetPlaceholder('wall_time_seconds'), '不设时限（系统默认）')
  assert.equal(agentBudgetPlaceholder('max_steps'), '24（系统默认）')
  assert.equal(agentBudgetPlaceholder('max_steps', {}, [], { entrypoint: { type: 'flow' } }), '100（系统默认）')
  assert.equal(agentBudgetPlaceholder('input_tokens'), '32,768（系统默认）')
})

test('model placeholders distinguish absent declarations from protocol and provider defaults', () => {
  assert.equal(modelFieldPlaceholder('request_max_output_tokens', { protocol: 'anthropic-messages' }), '4,096（系统默认）')
  assert.equal(modelFieldPlaceholder('request_max_output_tokens', { protocol: 'openai-responses' }), '不指定（系统默认）')
  assert.equal(modelFieldPlaceholder('context_window'), '未声明（系统默认）')
  assert.equal(modelFieldPlaceholder('temperature'), '不指定（系统默认）')
  assert.equal(modelFieldPlaceholder('top_p'), '不指定（系统默认）')
})
