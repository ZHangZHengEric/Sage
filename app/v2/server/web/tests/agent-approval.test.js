import assert from 'node:assert/strict'
import { test } from 'node:test'
import { approvalRuleItems, changeApprovalRule, approvalChanges, approvalOverrideCount } from '../src/agent-approval.js'

test('approval editor uses remote approval keys and retains rules missing from discovery', () => {
  const rows = approvalRuleItems([{ name: 'mcp_notes_read', approval_key: 'mcp:notes:read.remote', source: 'mcp' }],
    { 'mcp:old:write': 'ask' })
  assert.deepEqual(rows.map(row => row.key), ['mcp:notes:read.remote', 'mcp:old:write'])
  assert.equal(rows[0].name, 'mcp_notes_read')
  assert.equal(rows[1].available, false)
  const rules = changeApprovalRule({ 'mcp:old:write': 'ask' }, rows[0].key, 'auto_approve')
  assert.deepEqual(rules, { 'mcp:old:write': 'ask', 'mcp:notes:read.remote': 'auto_approve' })
  assert.deepEqual(changeApprovalRule(rules, 'mcp:old:write', 'inherit'), { 'mcp:notes:read.remote': 'auto_approve' })
})

test('inherit removes the override, and an unchanged confirmation retains legacy inherit representation', () => {
  const before = { read: 'inherit', write: 'ask' }
  const draft = changeApprovalRule(changeApprovalRule(before, 'read', 'ask'), 'read', 'inherit')
  assert.equal(approvalChanges(before, draft), 0)
  assert.equal(approvalOverrideCount(before), 1)
  assert.deepEqual(before, { read: 'inherit', write: 'ask' })
})
