import assert from 'node:assert/strict'
import { test } from 'node:test'
import { reactive } from 'vue'
import { chooseSchema, initialValue, resolveSchema } from '../src/config-schema.js'

test('schema defaults resolve references, nullable fields and reactive defaults', () => {
  const root = { $defs: { Agent: { type: 'object', required: ['name', 'mode'], properties: { name: { type: 'string' }, mode: { enum: ['simple', 'team'] } } } } }
  assert.deepEqual(initialValue({ $ref: '#/$defs/Agent' }, root), { name: '', mode: 'simple' })
  assert.equal(initialValue({ anyOf: [{ type: 'integer', exclusiveMinimum: 0 }, { type: 'null' }], default: null }, root), 1)
  assert.deepEqual(initialValue(reactive({ default: ['file_read'] }), root), ['file_read'])
  assert.equal(chooseSchema({ anyOf: [{ type: 'object' }, { type: 'array' }] }, [], root).type, 'array')
  assert.equal(resolveSchema({ $ref: '#/$defs/Agent' }, root).type, 'object')
})
