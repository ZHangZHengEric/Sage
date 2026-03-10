import { baseAPI } from './base.js'

export const systemAPI = {
  getSystemInfo: () => {
    return baseAPI.get('/api/system/info')
  },
  updateSettings: (settings) => {
    return baseAPI.post('/api/system/update_settings', settings)
  },
  getLatestVersion: () => {
    return baseAPI.get('/api/system/version/latest')
  },
  getVersions: () => {
    return baseAPI.get('/api/system/version')
  },
  createVersion: (data) => {
    return baseAPI.post('/api/system/version', data)
  },
  importGithubVersion: () => {
    return baseAPI.post('/api/system/version/import_github')
  },
  deleteVersion: (version) => {
    return baseAPI.delete(`/api/system/version/${version}`)
  }
}

export default systemAPI
