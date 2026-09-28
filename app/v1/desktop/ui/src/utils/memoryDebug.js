const DEBUG_KEY = '__SAGE_MEMORY_DEBUG__'
const REPORT_INTERVAL_MS = 30000

const getMemoryApi = () => {
  if (typeof performance === 'undefined') return null
  return performance.memory || null
}

const createState = () => ({
  counters: Object.create(null),
  values: Object.create(null),
  reporterStarted: false,
  reporterId: null
})

const ensureState = () => {
  if (typeof window === 'undefined') return null
  if (!window[DEBUG_KEY]) {
    window[DEBUG_KEY] = createState()
  }
  return window[DEBUG_KEY]
}

export const setDebugCounter = (name, value) => {
  const state = ensureState()
  if (!state) return
  state.counters[name] = value
}

export const setDebugValue = (name, value) => {
  const state = ensureState()
  if (!state) return
  state.values[name] = value
}

const buildSnapshot = () => {
  const state = ensureState()
  if (!state) return null
  const memory = getMemoryApi()
  return {
    ts: new Date().toISOString(),
    counters: { ...state.counters },
    values: { ...state.values },
    jsHeapUsedMB: memory ? Math.round((memory.usedJSHeapSize / 1024 / 1024) * 10) / 10 : null,
    jsHeapTotalMB: memory ? Math.round((memory.totalJSHeapSize / 1024 / 1024) * 10) / 10 : null,
    jsHeapLimitMB: memory ? Math.round((memory.jsHeapSizeLimit / 1024 / 1024) * 10) / 10 : null
  }
}

export const reportMemorySnapshot = (reason = 'manual') => {
  const snapshot = buildSnapshot()
  if (!snapshot) return
  console.log(`[SageMemory][desktop][${reason}]`, snapshot)
}

export const startMemoryDebugReporter = () => {
  const state = ensureState()
  if (!state || state.reporterStarted) return
  state.reporterStarted = true
  reportMemorySnapshot('startup')
  state.reporterId = window.setInterval(() => {
    reportMemorySnapshot('interval')
  }, REPORT_INTERVAL_MS)
}

