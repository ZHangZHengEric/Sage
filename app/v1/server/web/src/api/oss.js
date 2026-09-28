import request from '../utils/request.js'


/**
 * 通用文件上传
 * @param {File} file - 要上传的文件
 * @returns {Promise<string>} - 返回响应对象 { success: true, data: { url: ... } }
 */
async function upload(file, path) {
    const formData = new FormData()
    formData.append('file', file)
    if (path) {
        formData.append('path', path)
    }
    return request.post('/api/oss/upload', formData)
}

async function importFromUrl(remoteUrl, agentId = null) {
    const body = { url: remoteUrl }
    if (agentId != null && String(agentId) !== '') {
        body.agent_id = String(agentId)
    }
    return request.post('/api/oss/import_url', body)
}

async function importSandboxUpload(agentId, filename) {
    return request.post('/api/oss/import_sandbox_upload', {
        agent_id: String(agentId),
        filename: String(filename),
    })
}

export const ossAPI = {
    upload,
    uploadFile: upload,
    importFromUrl,
    importSandboxUpload,
}

// Keep backward compatibility for other components using ossApi
export const ossApi = ossAPI
