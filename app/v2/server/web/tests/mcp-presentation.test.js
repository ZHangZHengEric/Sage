import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mcpServerKey, mcpToolInventory } from '../src/mcp-presentation.js'

test('MCP inventory joins cached names and newly discovered definitions without mixing owners or calling names', () => {
  const alice = { user_id: 'alice' }, bob = { user_id: 'bob' }
  const servers = [{ name: 'notes:team', tools: ['same', 'cached'], _owner: alice }, { name: 'notes:team', tools: ['same'], _owner: bob }, { name: 'stopped', tools: ['disabled_tool'], disabled: true }]
  const schema = { type: 'object', properties: { query: { type: 'string' } }, required: ['query'] }
  const live = { name: 'same', source: 'mcp', description: 'Alice tool', input_schema: schema, approval_key: 'mcp:notes%3Ateam:read' }
  const rows = mcpToolInventory(servers, [{ owner: alice, tools: [live, { name: 'new', source: 'mcp', approval_key: 'mcp:notes%3Ateam:new' }, { name: 'file_read', source: 'official' }] }], 'me')
  assert.equal(rows.length, 5)
  assert.equal(rows[0].tool.input_schema, schema)
  assert.equal(rows[0].tool.description, 'Alice tool')
  assert.equal(rows[1].state, 'unknown')
  assert.equal(rows[1].tool.input_schema, undefined)
  assert.equal(rows[2].tool.name, 'new')
  assert.equal(rows[3].hasDefinition, false)
  assert.equal(rows[4].state, 'disabled')
  assert.notEqual(mcpServerKey(servers[0]), mcpServerKey(servers[1]))
  assert.equal(new Set(rows.map(row => row.key)).size, rows.length)
})
test('MCP inventory retains discovered tools even when a saved service has not yet recorded them', () => {
  const rows = mcpToolInventory([], [{ tools: [{ name: 'mcp_new_search', source: 'mcp', approval_key: 'mcp:new:search' }] }])
  assert.equal(rows.length, 1)
  assert.equal(rows[0].serverName, 'new')
  assert.equal(rows[0].serverKey, 'unmatched')
})
