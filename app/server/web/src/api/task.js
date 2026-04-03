import request from '../utils/request.js'

export const taskAPI = {
  getWorkspaceFiles: (agentId) => {
    return request.post(`/api/agent/${agentId}/file_workspace`, {})
  },

  downloadFile: async (agentId, filePath) => {
    if (filePath && (filePath.startsWith('http://') || filePath.startsWith('https://'))) {
      const response = await fetch(filePath, {
        method: 'GET',
        mode: 'cors',
      })
      if (!response.ok) {
        throw new Error(`下载文件失败: ${response.status}`)
      }
      return response.blob()
    }

    const apiPrefix = import.meta.env.VITE_BACKEND_API_PREFIX || ''
    const url = `${apiPrefix}/api/agent/${agentId}/file_workspace/download?file_path=${encodeURIComponent(filePath)}`

    const headers = {
      Accept: 'application/json',
    }

    if (typeof localStorage !== 'undefined') {
      const token = localStorage.getItem('access_token')
      if (token) {
        headers.Authorization = `Bearer ${token}`
      }
    }

    const response = await fetch(url, {
      method: 'GET',
      credentials: 'include',
      headers
    })

    if (!response.ok) {
      try {
        const errorData = await response.json()
        throw new Error(errorData.detail || errorData.message || `下载文件失败: ${response.status}`)
      } catch (e) {
        throw new Error(`下载文件失败: ${response.status}`)
      }
    }

    return response.blob()
  },

  deleteWorkspaceFile: (agentId, sessionId, filePath) => {
    let url = ''
    if (agentId) {
      url = `/api/agent/${agentId}/file_workspace/delete?file_path=${encodeURIComponent(filePath)}`
    } else if (sessionId) {
      url = `/api/sessions/${sessionId}/file_workspace/delete?file_path=${encodeURIComponent(filePath)}`
    } else {
      throw new Error('agentId or sessionId is required')
    }
    return request.delete(url)
  },

  uploadWorkspaceFile: (agentId, file, targetPath = '') => {
    const formData = new FormData()
    formData.append('file', file)
    if (targetPath) {
      formData.append('target_path', targetPath)
    }
    return request.post(`/api/agent/${agentId}/file_workspace/upload`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
  }

}
