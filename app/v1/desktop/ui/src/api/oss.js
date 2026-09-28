import request from '../utils/request.js'


/**
 * 通用文件上传
 * @param {File} file - 要上传的文件
 * @param {string} agentId - 可选的 Agent ID，如果提供，文件将保存到该 Agent 沙箱的 upload_files 文件夹
 * @returns {Promise<{url: string, filename: string, local_path?: string, http_url?: string, agent_id?: string}>}
 *   桌面端 sidecar 直接返回本地绝对路径作为 `url`（同时还有 `local_path`），让 markdown 引用 /
 *   image_url 都使用本地路径，agent 与前端渲染都不必再绕 http://127.0.0.1。`http_url` 仅作降级展示。
 */
async function uploadFile(file, agentId = null) {
    const formData = new FormData()
    formData.append('file', file)
    if (agentId) {
        formData.append('agent_id', agentId)
    }
    const res = await request.post('/api/oss/upload', formData)
    return res
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

export const ossApi = {
    uploadFile,
    importFromUrl,
    importSandboxUpload,
}
