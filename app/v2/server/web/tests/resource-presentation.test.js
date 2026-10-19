import assert from 'node:assert/strict'
import { test } from 'node:test'
import { markdownBody, schemaType, toolParameters, toolPresentation } from '../src/resource-presentation.js'

test('tool parameters retain referenced types, nullability, required flags and falsy defaults', () => {
  const root = { type: 'object', $defs: { Choice: { anyOf: [{ type: 'array', items: { type: 'integer' } }, { type: 'null' }] } },
    required: ['values'], properties: { values: { $ref: '#/$defs/Choice', default: null }, enabled: { type: 'boolean', default: false }, limit: { type: 'integer', default: 0 } } }
  const fields = toolParameters({ source: 'mcp', input_schema: root })
  assert.equal(fields[0].type, 'integer[] | null')
  assert.equal(fields[0].required, true)
  assert.equal(fields[0].hasDefault, true)
  assert.equal(fields[0].default, null)
  assert.equal(fields[1].default, false)
  assert.equal(fields[2].default, 0)
  assert.equal(schemaType({ $ref: '#/$defs/Cycle' }, { $defs: { Cycle: { $ref: '#/$defs/Cycle' } } }), '未指定')
})

test('official display aliases never override an external tool with the same name', () => {
  assert.equal(toolPresentation({ name: 'file_read', source: 'official', category: 'files' }).title, '读取文件')
  const external = toolPresentation({ name: 'file_read', source: 'mcp', description: 'Remote behavior' })
  assert.equal(external.title, 'file_read')
  assert.equal(external.description, 'Remote behavior')
})

test('skill reading removes only leading frontmatter and preserves body separators', () => {
  const source = '\uFEFF---\r\nname: writer\r\n---\r\n# Instructions\r\n\r\n---\r\nMore'
  assert.equal(markdownBody(source), '# Instructions\r\n\r\n---\r\nMore')
  assert.equal(markdownBody('# Plain markdown\n---\nMore'), '# Plain markdown\n---\nMore')
})
