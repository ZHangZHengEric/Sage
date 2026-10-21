import assert from 'node:assert/strict'
import { test } from 'node:test'
import { componentGroups, pluginName, displayValue } from '../src/plugin-presentation.js'

test('component grouping preserves every implementation including multi-capability providers', () => {
  const plugins = [
    { id: 'sage.context.summarizer.model', capabilities: ['context.summarizer'] },
    { id: 'sage.context.summarizer.extractive', capabilities: ['context.summarizer'] },
    { id: 'sage.tool.official', capabilities: ['tool.provider'] },
  ]
  const groups = componentGroups({ plugins, defaults: { 'session.store': 'injected' } }, [{ capability: 'custom.scope', plugin_id: null }])
  assert.deepEqual(new Set(groups.flatMap(g => g.plugins.map(p => p.id))), new Set(plugins.map(p => p.id)))
  assert.equal(groups.find(g => g.id === 'context.summarizer').name, '上下文摘要器')
  assert.equal(groups.find(g => g.id === 'context.summarizer').plugins.length, 2)
  assert.equal(groups.find(g => g.id === 'session.store').plugins.length, 0)
  assert.ok(groups.some(g => g.id === 'custom.scope'))
  assert.equal(pluginName(plugins[0]), '模型摘要')
  assert.equal(pluginName('sage.tool-selection.llm'), '大模型工具选择')
  assert.equal(displayValue(false), '关闭')
  assert.equal(displayValue(0), '0')
})
