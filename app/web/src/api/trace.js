import { baseAPI } from './base.js'

async function getSessionTraces(sessionId) {
  return await baseAPI.get(`/api/trace/${sessionId}`)
}

export const traceApi = {
  getSessionTraces
}