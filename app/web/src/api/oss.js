import { baseAPI } from './base.js'


/**
 * 通用文件上传
 * @param {File} file - 要上传的文件
 * @returns {Promise<string>} - 返回响应对象 { success: true, data: { url: ... } }
 */
async function upload(file) {
    const formData = new FormData()
    formData.append('file', file)
    // baseAPI.post returns response data directly due to interceptors
    // But backend returns { code: 200, data: { url: ... } } usually
    // Let's check baseAPI implementation or assume standard response wrapper
    // The backend oss_router returns Response.succ(data={"url": url}) which is { code: 200, data: { url: ... } }
    // The request interceptor unwraps it to { success: true, data: ..., message: ... }
    
    // However, the original uploadFile implementation:
    // const res = await baseAPI.post(...)
    // return res.url
    // This implies baseAPI.post returns the data object directly if success?
    // Let's look at request.js:
    // if (response.code === 200) return { success: true, data: response.data ... }
    
    // So the previous implementation `return res.url` was likely wrong if it expected `res` to be the data object directly, 
    // unless the interceptor behavior is different.
    // Given VersionList.vue expects `res.success` and `res.data.url`, we should return the full response object from baseAPI.post
    
    return baseAPI.post('/api/oss/upload', formData)
}

export const ossAPI = {
    upload,
    uploadFile: upload // Keep alias for compatibility if needed
}

// Keep backward compatibility for other components using ossApi
export const ossApi = ossAPI
