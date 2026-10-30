import { computed, onScopeDispose, ref } from 'vue'
import { api } from './api.js'
import { activeRun } from './rsi.js'

export function useRsi({ client = api, delay = 2000 } = {}) {
  const agent = ref(null), models = ref([]), runs = ref([]), run = ref(null), version = ref(null)
  const runId = ref(''), versionId = ref(''), offset = ref(0)
  const loading = ref(false), refreshing = ref(false), reading = ref(false), versionLoading = ref(false), busy = ref(false)
  const error = ref(''), readError = ref(''), actionError = ref(''), versionError = ref(''), notice = ref('')
  let agentId = '', context = 0, pageRead = 0, historyRead = 0, runRead = 0, versionRead = 0, timer, disposed = false, attempt
  const valid = stamp => !disposed && stamp === context
  const baseline = computed(() => run.value?.result?.iterations?.find(item => item.iteration === 0)?.package || null)
  const applied = computed(() => version.value && version.value.package_ref === agent.value?.package_ref)
  const conflicted = computed(() => run.value && agent.value && !applied.value && agent.value.package_ref !== run.value.base_package_ref)
  const canApply = computed(() => !busy.value && !versionLoading.value && run.value?.status === 'completed' &&
    version.value?.iteration > 0 && version.value.version_id === versionId.value && baseline.value && !applied.value && !conflicted.value)

  function stopPoll() { clearTimeout(timer); timer = undefined }
  function schedule() {
    stopPoll()
    if (!disposed && !busy.value && activeRun(run.value)) timer = setTimeout(() => void refreshRun(), delay)
  }
  function replaceHistory(value) {
    runs.value = runs.value.map(item => item.id === value.id ? { ...item, ...value, result: undefined } : item)
  }
  async function refreshHistory(nextOffset = offset.value) {
    const stamp = context, id = agentId, revision = ++historyRead
    try {
      const rows = await client.rsiRuns(id, nextOffset)
      if (!valid(stamp) || revision !== historyRead) return false
      runs.value = rows; offset.value = nextOffset
      return true
    } catch (exc) { if (valid(stamp) && revision === historyRead) error.value = exc.message; return false }
  }
  async function selectVersion(id) {
    const stamp = context, revision = ++versionRead, currentRun = runId.value
    versionId.value = id; version.value = null; versionError.value = ''; versionLoading.value = true
    try {
      const value = await client.rsiVersion(agentId, currentRun, id)
      if (valid(stamp) && revision === versionRead && currentRun === runId.value) version.value = value
    } catch (exc) { if (valid(stamp) && revision === versionRead) versionError.value = exc.message }
    finally { if (valid(stamp) && revision === versionRead) versionLoading.value = false }
  }
  async function refreshRun() {
    if (!runId.value || busy.value || disposed) return false
    const stamp = context, revision = ++runRead, id = runId.value
    try {
      const value = await client.rsiRun(agentId, id)
      if (!valid(stamp) || revision !== runRead) return false
      run.value = value; readError.value = ''; replaceHistory(value)
      if (value.status === 'completed' && !versionId.value) {
        const retained = value.versions.find(item => item.package_ref === value.candidate_ref) || value.versions.at(-1)
        if (retained) await selectVersion(retained.version_id)
      }
      return true
    } catch (exc) { if (valid(stamp) && revision === runRead) readError.value = exc.message; return false }
    finally { if (valid(stamp) && revision === runRead) { reading.value = false; schedule() } }
  }
  async function selectRun(id) {
    if (busy.value || disposed) return false
    stopPoll(); runRead++; versionRead++
    runId.value = id; run.value = null; version.value = null; versionId.value = ''
    versionLoading.value = false; readError.value = ''; actionError.value = ''; versionError.value = ''; notice.value = ''
    reading.value = true
    return await refreshRun()
  }
  async function refresh() {
    if (!agentId || busy.value || refreshing.value) return false
    const stamp = context, revision = ++pageRead, historyRevision = ++historyRead
    refreshing.value = true; error.value = ''
    try {
      const [detail, choices, rows] = await Promise.all([client.getAgent(agentId), client.listModels(false), client.rsiRuns(agentId, offset.value)])
      if (!valid(stamp) || revision !== pageRead) return false
      agent.value = detail; models.value = choices
      if (historyRevision === historyRead) runs.value = rows
      if (runId.value) await refreshRun()
      else if (rows.length) await selectRun(rows[0].id)
      return true
    } catch (exc) { if (valid(stamp) && revision === pageRead) error.value = exc.message; return false }
    finally { if (valid(stamp)) { loading.value = false; refreshing.value = false } }
  }
  async function load(id, selected = '') {
    context++; pageRead++; historyRead++; runRead++; versionRead++; stopPoll(); agentId = id; attempt = null
    agent.value = null; run.value = null; version.value = null; runs.value = []; models.value = []
    runId.value = selected; versionId.value = ''; offset.value = 0
    loading.value = true; refreshing.value = false; reading.value = false; versionLoading.value = false; busy.value = false
    readError.value = ''; actionError.value = ''; versionError.value = ''; notice.value = ''
    return await refresh()
  }
  async function mutate(operation) {
    if (busy.value || disposed || !agent.value) return false
    const stamp = context
    busy.value = true; actionError.value = ''; notice.value = ''; pageRead++; historyRead++; runRead++; stopPoll()
    try { await operation(stamp); return true }
    catch (exc) { if (valid(stamp)) actionError.value = exc.status === 409 ? '版本或运行状态已变更，请刷新后检查。智能体配置发生变化时，须基于最新配置新建实验。' : exc.message; return false }
    finally { if (valid(stamp)) { busy.value = false; schedule() } }
  }
  async function start(payload) {
    return await mutate(async stamp => {
      const identity = JSON.stringify(payload)
      if (!attempt || attempt.identity !== identity) attempt = { identity, request_id: crypto.randomUUID() }
      const value = await client.startRsi(agentId, { ...payload, request_id: attempt.request_id })
      if (!valid(stamp)) return
      attempt = null; versionRead++; version.value = null; versionId.value = ''; versionLoading.value = false
      runId.value = value.id; run.value = value; notice.value = '实验已启动'
      await refreshHistory(0)
    })
  }
  async function control(action) {
    if (!runId.value || (action === 'cancel' ? !activeRun(run.value) : !['failed', 'interrupted'].includes(run.value?.status))) return false
    return await mutate(async stamp => {
      const value = await (action === 'cancel' ? client.cancelRsi(agentId, runId.value) : client.resumeRsi(agentId, runId.value))
      if (!valid(stamp)) return
      run.value = value; replaceHistory(value); notice.value = action === 'cancel' ? '已请求停止，已完成的记录将保留' : '已恢复实验'
    })
  }
  async function apply() {
    if (!canApply.value) return false
    const selected = version.value, currentRun = run.value
    return await mutate(async stamp => {
      const value = await client.applyRsiVersion(agentId, currentRun.id, selected.version_id, currentRun.base_package_ref)
      if (!valid(stamp)) return
      agent.value = { ...agent.value, package_ref: value.package_ref }; notice.value = '候选版本已应用'
      try {
        const detail = await client.getAgent(agentId)
        if (valid(stamp)) agent.value = detail
      } catch (exc) { if (valid(stamp)) notice.value = `候选版本已应用，配置刷新失败：${exc.message}` }
    })
  }
  onScopeDispose(() => { disposed = true; context++; stopPoll() })
  return { agent, models, runs, run, version, runId, versionId, offset, baseline, applied, conflicted, canApply,
    loading, refreshing, reading, versionLoading, busy, error, readError, actionError, versionError, notice,
    load, refresh, refreshRun, refreshHistory, selectRun, selectVersion, start, control, apply }
}
