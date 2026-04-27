import request from '../utils/request.js'

export const systemAPI = {
  getSystemInfo: () => {
    return request.get('/api/system/info')
  },
  updateSettings: (settings) => {
    return request.post('/api/system/update_settings', settings)
  },
  getLatestVersion: () => {
    return request.get('/api/system/version/latest')
  },
  getVersions: () => {
    return request.get('/api/system/version')
  },
  createVersion: (data) => {
    return request.post('/api/system/version', data)
  },
  importGithubVersion: () => {
    return request.post('/api/system/version/import_github')
  },
  deleteVersion: (version) => {
    return request.delete(`/api/system/version/${version}`)
  }
}

export default systemAPI
