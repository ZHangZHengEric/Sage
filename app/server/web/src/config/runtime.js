const WEB_BASE_PATH = '/sage/'
const API_PREFIX = '/prod-api'

export const getWebBasePath = () => WEB_BASE_PATH

export const getBackendEndpoint = () => {
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  return `${origin}${API_PREFIX}`
}

export const getApiPrefix = () => API_PREFIX

export const getAssetUrl = (assetName) => {
  return `${getWebBasePath()}${String(assetName).replace(/^\/+/, '')}`
}
