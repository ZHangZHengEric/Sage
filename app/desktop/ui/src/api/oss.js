import request from '../utils/request.js'


/**
 * 通用文件上传
 * @param {File} file - 要上传的文件
 * @param {string} agentId - 可选的 Agent ID，如果提供，文件将保存到该 Agent 沙箱的 upload_files 文件夹
 * @returns {Promise<string>} - 返回拼接后的公网 URL
 */
async function uploadFile(file, agentId = null) {
    const formData = new FormData()
    formData.append('file', file)
    if (agentId) {
        formData.append('agent_id', agentId)
    }
    const res = await request.post('/api/oss/upload', formData)
    return res.url
}

export const ossApi = {
    uploadFile
}
