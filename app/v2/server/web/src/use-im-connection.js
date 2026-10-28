import { computed, onScopeDispose, ref } from 'vue'
import { api } from './api.js'

export const connectionStates = { unavailable: '不可用', disabled: '已停用', awaiting_pairing: '待本人配对', webhook_ready: '已配对' }
export const deliveryStates = { pending: '待发送', sending: '发送中', platform_accepted: '平台已接收', failed: '发送失败', unknown: '结果未知', superseded: '已丢弃或失效' }

export function useIMConnection(initial, { client = api, onChange = () => {} } = {}) {
  const connection = ref(initial), status = ref(null), error = ref(''), message = ref('')
  const busy = ref(false), refreshing = ref(false), probing = ref('')
  const deliveries = ref([]), cursor = ref(null), deliveriesLoading = ref(false), deliveryError = ref(''), unresolved = ref(true)
  const pairing = ref(null), expiresAt = ref(0), now = ref(Date.now())
  const secondsLeft = computed(() => Math.max(0, Math.ceil((expiresAt.value - now.value) / 1000)))
  let disposed = false, statusSequence = 0, deliverySequence = 0, timer = null, polling = false, lastPoll = 0
  function update(value) { connection.value = value; onChange(value) }
  function clearPairing() { pairing.value = null; expiresAt.value = 0 }
  onScopeDispose(() => { disposed = true; statusSequence++; deliverySequence++; clearInterval(timer); clearPairing() })

  async function refresh() {
    const sequence = ++statusSequence
    refreshing.value = true
    try {
      const [value, state] = await Promise.all([client.imConnection(initial.id), client.imConnectionStatus(initial.id)])
      if (disposed || sequence !== statusSequence) return
      // A concurrent change can make the two reads disagree. Never enable an
      // action using the older revision; the next refresh resolves the state.
      update(value)
      status.value = state.revision === value.revision && state.paired === value.paired ? state : null
      error.value = ''
      if (!value.enabled || value.paired) clearPairing()
    } catch (exc) {
      if (!disposed && sequence === statusSequence) { error.value = exc.message; status.value = null }
    } finally { if (!disposed && sequence === statusSequence) refreshing.value = false }
  }

  async function loadDeliveries(reset = true) {
    if (!reset && (deliveriesLoading.value || cursor.value === null)) return
    const sequence = ++deliverySequence, filter = unresolved.value
    deliveriesLoading.value = true; deliveryError.value = ''
    if (reset) { deliveries.value = []; cursor.value = null }
    try {
      const page = await client.imDeliveries(initial.id, { after: reset ? 0 : cursor.value, unresolved: filter })
      if (disposed || sequence !== deliverySequence) return
      deliveries.value = reset ? page.items : [...deliveries.value, ...page.items]
      cursor.value = page.next_cursor
    } catch (exc) { if (!disposed && sequence === deliverySequence) deliveryError.value = exc.message }
    finally { if (!disposed && sequence === deliverySequence) deliveriesLoading.value = false }
  }

  async function action(task) {
    if (disposed || busy.value) return false
    statusSequence++; refreshing.value = false
    busy.value = true; error.value = ''; message.value = ''
    try { await task(); return !disposed }
    catch (exc) {
      if (!disposed) error.value = exc.message
      return false
    } finally { if (!disposed) busy.value = false }
  }
  async function toggle() {
    return action(async () => {
      const value = connection.value
      const updated = await client.updateIMConnection(value.id, { revision: value.revision, enabled: !value.enabled })
      if (disposed) return
      update(updated); clearPairing(); status.value = null
      message.value = updated.enabled ? '连接已启用' : '连接已停用'
      await refresh()
    })
  }
  async function probe() {
    probing.value = ''
    const ok = await action(async () => {
      const result = await client.testIMConnection(initial.id)
      if (!result.credentials_valid) throw new Error('凭据测试未通过')
      if (!disposed) { probing.value = '通过（仅凭据）'; await refresh() }
    })
    if (!ok && !disposed) probing.value = '未通过'
    return ok
  }
  async function pair() {
    return action(async () => {
      clearPairing()
      const value = await client.pairIMConnection(initial.id)
      if (disposed) return
      pairing.value = value; now.value = Date.now()
      expiresAt.value = now.value + value.expires_in * 1000
    })
  }
  async function retry(row, allowDuplicate = false) {
    if (row.state === 'unknown' && !allowDuplicate) return false
    return action(async () => {
      await client.retryIMDelivery(row.id, row.revision, allowDuplicate)
      if (disposed) return
      message.value = '已提交重试'; await loadDeliveries()
    })
  }
  async function discard(row) {
    return action(async () => {
      await client.discardIMDelivery(row.id, row.revision)
      if (disposed) return
      message.value = '投递已丢弃'; await loadDeliveries()
    })
  }
  async function remove() {
    return action(() => client.deleteIMConnection(initial.id, connection.value.revision))
  }
  function start() {
    if (timer !== null || disposed) return
    void refresh(); void loadDeliveries()
    lastPoll = Date.now()
    timer = setInterval(() => {
      now.value = Date.now()
      if (pairing.value && secondsLeft.value === 0) clearPairing()
      if (now.value - lastPoll < 5000 || busy.value || refreshing.value || polling || document.visibilityState === 'hidden') return
      lastPoll = now.value
      polling = true
      void refresh().finally(() => { polling = false })
    }, 1000)
  }
  return { connection, status, error, message, busy, refreshing, probing, deliveries, cursor, deliveriesLoading, deliveryError, unresolved, pairing, secondsLeft, clearPairing, refresh, loadDeliveries, toggle, probe, pair, retry, discard, remove, start }
}
