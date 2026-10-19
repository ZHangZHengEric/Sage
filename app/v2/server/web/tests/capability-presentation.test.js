import assert from 'node:assert/strict'
import { test } from 'node:test'
import { capabilityNodes, effectivePlugin, pluginExplanation, selectionChanged } from '../src/capability-presentation.js'

const capability = 'tool.selection-policy'
const catalog = {
  configurable: [capability, 'custom.capability'],
  defaults: { [capability]: 'sage.tool-selection.llm' },
  default_config: { [capability]: { max_visible_tools: 12 } },
  plugins: [
    { id: 'sage.tool-selection.llm', capabilities: [capability], schema: { properties: { max_visible_tools: { default: 24 }, model_timeout_seconds: { default: 30 } } } },
    { id: 'sage.tool-selection.direct', capabilities: [capability], schema: { properties: {} } },
  ],
}

test('effective parameters follow host defaults, merge same-plugin overrides and replace changed plugins', () => {
  assert.deepEqual(effectivePlugin(catalog, {}, capability).config, { max_visible_tools: 12, model_timeout_seconds: 30 })
  assert.deepEqual(effectivePlugin(catalog, { [capability]: { plugin: 'sage.tool-selection.llm', config: { max_visible_tools: 0 } } }, capability).config,
    { max_visible_tools: 0, model_timeout_seconds: 30 })
  assert.deepEqual(effectivePlugin(catalog, { [capability]: { plugin: 'sage.tool-selection.direct', config: {} } }, capability).config, {})
})

test('a missing plugin stays visible without presenting host parameters as its own', () => {
  const selected = effectivePlugin(catalog, { [capability]: { plugin: 'removed', config: { custom: false } } }, capability)
  assert.equal(selected.id, 'removed')
  assert.equal(selected.available, false)
  assert.deepEqual(selected.config, { custom: false })
  assert.match(pluginExplanation(selected.id, selected.config).effects.join(' '), /验证/)
})

test('canvas includes every configurable capability and model routes only when provided', () => {
  const nodes = capabilityNodes(catalog)
  assert.deepEqual(new Set(nodes.map(n => n.id)), new Set(catalog.configurable))
  assert.equal(capabilityNodes(catalog, 'Primary model').filter(n => n.id === 'model.provider').length, 1)
  const mixed = { ...catalog, defaults: { ...catalog.defaults, 'memory.provider': 'server.memory' }, plugins: [...catalog.plugins, { id: 'server.memory', capabilities: ['memory.provider'] }] }
  assert.ok(!capabilityNodes(mixed).some(node => node.id === 'memory.provider'))
})

test('change markers compare stored selections including source and ignore object-key order', () => {
  assert.equal(selectionChanged({ plugin: 'x', config: { b: false, a: 0 } }, { config: { a: 0, b: false }, plugin: 'x' }), false)
  assert.equal(selectionChanged(undefined, { plugin: 'x', config: {} }), true)
  assert.equal(selectionChanged(undefined, undefined), false)
})

test('effect explanations distinguish unlimited tools from a bounded selection', () => {
  assert.match(pluginExplanation('sage.tool-selection.lexical', { max_visible_tools: 12 }).effects.join(' '), /12/)
  assert.doesNotMatch(pluginExplanation('sage.tool-selection.direct', { max_visible_tools: 12 }).effects.join(' '), /12/)
  assert.match(pluginExplanation('sage.context.reducer.window').effects.join(' '), /摘要器.*不参与/)
})
