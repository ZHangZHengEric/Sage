import assert from 'node:assert/strict'
import { test } from 'node:test'
import { defaultRsiForm, rsiPayload, evaluationScore, packageChanges, lineDiff } from '../src/rsi.js'

test('RSI form admits only explicit instructions/skills and validated case splits', () => {
  const form = defaultRsiForm()
  form.goal = 'Improve arithmetic'
  form.datasetMode = 'import'
  form.suiteText = JSON.stringify({ cases: [
    { id: 'a', input: '2+2', rubric: '4', split: 'training' },
    { id: 'b', input: '3+3', rubric: '6', split: 'validation' },
  ] })
  const payload = rsiPayload(form)
  assert.equal(payload.validation_case_count, 1)
  assert.deepEqual(payload.optimization_scope, ['instructions', 'skills'])
  assert.equal(payload.suite.cases.length, 2)
  assert.ok(!('request_id' in payload))
  form.suiteText = JSON.stringify({ cases: [{ id: 'a', split: 'test' }] })
  assert.throws(() => rsiPayload(form), /training.*validation/)
  form.datasetMode = 'generate'; form.scope = []
  assert.throws(() => rsiPayload(form), /优化范围/)
  form.scope = ['instructions']; form.rounds = 0
  assert.throws(() => rsiPayload(form), /轮数/)
})

test('unreported scores remain absent while a valid zero remains zero', () => {
  const data = score => ({ cases: [{ case: { split: 'validation' }, grade: { score } }] })
  assert.equal(evaluationScore(data(0), 'validation'), 0)
  assert.equal(evaluationScore(data(null), 'validation'), null)
  assert.equal(evaluationScore({ cases: [] }, 'validation'), null)
})

test('version comparison resolves prompt files and includes added/deleted Skill resources', () => {
  const before = { manifest: { entrypoint: { agent: 'a' }, agents: { a: { instructions: { path: 'prompt.md' }, skills: ['old'] } } },
    files: { 'prompt.md': 'Before', 'skills/old/SKILL.md': 'Old' } }
  const after = structuredClone(before)
  after.manifest.agents.a.instructions = { inline: 'After' }
  after.manifest.agents.a.skills = ['new']
  delete after.files['skills/old/SKILL.md']
  after.files['skills/new/SKILL.md'] = 'New'
  const changes = packageChanges(before, after)
  assert.deepEqual(changes.map(c => c.path), ['系统提示词', '启用技能', 'skills/new/SKILL.md', 'skills/old/SKILL.md'])
  assert.equal(changes[0].before, 'Before')
  assert.equal(changes[3].after, '')
  const diff = lineDiff('A\nB\nC', 'A\nX\nC')
  assert.deepEqual(diff.lines.map(row => [row.kind, row.text]), [['same', 'A'], ['remove', 'B'], ['add', 'X'], ['same', 'C']])
  assert.ok(lineDiff('A\n'.repeat(2000), 'B\n'.repeat(2000)).truncated)
})
