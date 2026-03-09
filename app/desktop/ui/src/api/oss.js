import { baseAPI } from './base.js'


/**
 * 通用文件上传
 * @param {File} file - 要上传的文件
 * @returns {Promise<string>} - 返回拼接后的公网URL
 */
async function uploadFile(file) {
    const formData = new FormData()
    formData.append('file', file)
    const res = await baseAPI.post('/api/oss/upload', formData)
    return res.url
}

export const ossApi = {
    uploadFile
}
