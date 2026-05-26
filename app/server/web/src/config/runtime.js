const WEB_BASE_PATH = '/sage/'
const API_PREFIX = '/prod-api'
const GRAFANA_URL = import.meta.env.VITE_SAGE_GRAFANA_URL || 'http://127.0.0.1:30093'

export const getWebBasePath = () => WEB_BASE_PATH

export const getBackendEndpoint = () => {
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  return `${origin}${API_PREFIX}`
}

export const getApiPrefix = () => API_PREFIX

export const getGrafanaUrl = () => GRAFANA_URL

export const getAssetUrl = (assetName) => {
  return `${getWebBasePath()}${String(assetName).replace(/^\/+/, '')}`
}
