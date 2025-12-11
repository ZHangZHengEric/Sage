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

/**
 * 上传图片到OSS
 * @param {File} file - 要上传的图片文件
 * @returns {Promise<string>} - 返回拼接后的图片公网URL
 */
async function uploadImage(file) {
    return uploadFile(file)
}

/**
 * 上传视频到OSS
 * @param {File} file - 要上传的视频文件
 * @returns {Promise<string>} - 返回拼接后的视频公网URL
 */
async function uploadVideo(file) {
    return uploadFile(file)
}

export const ossApi = {
    uploadImage,
    uploadVideo
}
