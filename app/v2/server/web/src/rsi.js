export const rsiFields = [
  ['rounds', '优化轮数', 1, 100], ['initial_training_case_count', '初始训练题量', 1, 100],
  ['training_cases_per_round', '每轮新增训练题', 0, 100], ['validation_case_count', '固定验证题量', 1, 100],
  ['max_concurrency', '并发调用数', 1, 16], ['evaluation_repeats', '每题评测次数', 1, 10],
  ['call_timeout_seconds', '单次调用时限（秒）', 1, 7200], ['timeout_seconds', '实验时限（秒）', 1, 86400],
  ['max_system_prompt_chars', '提示词字符上限', 1, 1000000], ['max_skill_chars', '单个技能字符上限', 1, 1000000],
  ['max_skill_count', '技能数量上限', 0, 256], ['max_edit_repairs', '候选修正次数', 0, 10],
]

export function defaultRsiForm() {
  return { goal: '', scope: ['instructions', 'skills'], model_id: '', datasetMode: 'generate', suiteText: '',
    rounds: 8, initial_training_case_count: 6, training_cases_per_round: 6, validation_case_count: 24,
    max_concurrency: 3, evaluation_repeats: 1, call_timeout_seconds: 240, timeout_seconds: 3600,
    max_system_prompt_chars: 64000, max_skill_chars: 32000, max_skill_count: 16, max_edit_repairs: 3,
    target_score: 0.95, patience: 3, stability_passes: 2 }
}

function number(value, label, min, max, integer = true) {
  if (value === '' || value == null || !Number.isFinite(Number(value)) || (integer && !Number.isInteger(Number(value))) || Number(value) < min || Number(value) > max) {
    throw Error(`${label}须为 ${min}–${max} 范围内的${integer ? '整数' : '数值'}`)
  }
  return Number(value)
}

export function rsiPayload(form) {
  if (!form.goal.trim() || form.goal.length > 16000) throw Error('请填写 1–16000 字的优化目标')
  if (!form.scope.length || form.scope.some(part => !['instructions', 'skills'].includes(part))) throw Error('请选择提示词或技能作为优化范围')
  const payload = { goal: form.goal.trim(), optimization_scope: [...new Set(form.scope)],
    model_id: form.model_id || null }
  for (const [key, label, min, max] of rsiFields) payload[key] = number(form[key], label, min, max)
  payload.stopping_policy = { target_score: number(form.target_score, '目标得分', 0.001, 1, false),
    patience: number(form.patience, '停滞轮数', 1, 100), stability_passes: number(form.stability_passes, '稳定复测次数', 2, 5) }
  if (form.datasetMode === 'import') {
    let data
    try { data = JSON.parse(form.suiteText) } catch { throw Error('题集 JSON 格式不正确') }
    const cases = Array.isArray(data) ? data : data?.cases
    if (!Array.isArray(cases) || !cases.length || cases.length > 200) throw Error('题集须包含 1–200 道 training / validation 案例')
    const ids = new Set()
    for (const item of cases) {
      if (!item || !['training', 'validation'].includes(item.split)) throw Error('题集仅支持 training 和 validation 分组')
      if (typeof item.id !== 'string' || !item.id.trim() || ids.has(item.id)) throw Error('题目 ID 须非空且不重复')
      if (typeof item.input !== 'string' || !item.input.trim() || typeof item.rubric !== 'string' || !item.rubric.trim()) throw Error('每道题须填写 input 和 rubric')
      ids.add(item.id)
    }
    const validation = cases.filter(c => c.split === 'validation').length
    const training = cases.length - validation
    if (!training || !validation || training > 100 || validation > 100) throw Error('training 和 validation 各须包含 1–100 道题')
    payload.suite = { cases }
    payload.validation_case_count = validation
    payload.initial_training_case_count = Math.min(payload.initial_training_case_count, training)
  }
  return payload
}

export function evaluationScore(evaluation, split) {
  const rows = (evaluation?.cases || []).filter(c => c.case?.split === split)
  if (!rows.length || rows.some(row => typeof row.grade?.score !== 'number' || !Number.isFinite(row.grade.score))) return null
  return rows.reduce((sum, row) => sum + row.grade.score, 0) / rows.length
}
export const scoreText = score => typeof score === 'number' && Number.isFinite(score) ? score.toFixed(3) : '—'
export const activeRun = run => ['queued', 'running'].includes(run?.status)
export const runStatus = run => ({ queued: '排队中', running: '运行中', interrupted: '已停止', failed: '失败', completed: '已完成' }[run?.status] || '—')
export const runStage = run => {
  if (!activeRun(run)) return runStatus(run)
  const stage = run?.stage || ''
  if (stage.includes('design') || stage.includes('suite') || stage.includes('training_case')) return '准备题集'
  if (stage.includes('tun') || stage.includes('candidate') || stage.includes('proposal') || stage.includes('experiment')) return '生成候选'
  if (stage.includes('eval') || stage.includes('case') || stage.includes('baseline') || stage.includes('execution')) return '执行评测'
  if (stage.includes('stability')) return '稳定性复测'
  return '优化中'
}

export function packageChanges(before, after) {
  function resources(bundle) {
    const definition = bundle?.manifest?.agents?.[bundle.manifest.entrypoint?.agent]
    if (!definition) return {}
    return { '系统提示词': definition.instructions.inline ?? bundle.files?.[definition.instructions.path] ?? '',
      '启用技能': JSON.stringify(definition.skills || [], null, 2),
      ...Object.fromEntries(Object.entries(bundle.files || {}).filter(([path]) => path.startsWith('skills/'))) }
  }
  const old = resources(before), next = resources(after)
  return [...new Set([...Object.keys(old), ...Object.keys(next)])].sort((a, b) => {
    const order = ['系统提示词', '启用技能']
    return (order.includes(a) ? order.indexOf(a) : 2) - (order.includes(b) ? order.indexOf(b) : 2) || a.localeCompare(b)
  }).filter(path => old[path] !== next[path]).map(path => ({ path, before: old[path] || '', after: next[path] || '',
    kind: !(path in old) ? '新增' : !(path in next) ? '删除' : '修改' }))
}

export function lineDiff(before, after, limit = 1000) {
  const old = before.split('\n'), next = after.split('\n'), lines = []
  const append = (kind, text) => { if (lines.length <= limit) lines.push({ kind, text }) }
  if (old.length * next.length <= 150000) {
    const table = Array.from({ length: old.length + 1 }, () => new Uint16Array(next.length + 1))
    for (let i = old.length - 1; i >= 0; i--) for (let j = next.length - 1; j >= 0; j--) {
      table[i][j] = old[i] === next[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1])
    }
    let i = 0, j = 0
    while (i < old.length || j < next.length) {
      if (i < old.length && j < next.length && old[i] === next[j]) { append('same', old[i]); i++; j++ }
      else if (i < old.length && (j === next.length || table[i + 1][j] >= table[i][j + 1])) append('remove', old[i++])
      else append('add', next[j++])
    }
  } else {
    old.forEach(line => append('remove', line)); next.forEach(line => append('add', line))
  }
  return { lines: lines.slice(0, limit), truncated: lines.length > limit }
}
