// Cookie 处理已改为 js-cookie 库

const apiPrefix = import.meta.env.VITE_BACKEND_API_PREFIX || '';  // 默认空字符串，如果没有设置前缀

// API基础配置
const CONFIG = {
    baseURL: apiPrefix, // url = base url + request url
    withCredentials: true, // send cookies when cross-domain requests
    timeout: 1000 * 60 * 10 // request timeout
}

// 请求配置常量
export const REQUEST_CONFIG = {
    // 默认超时时间
    DEFAULT_TIMEOUT: 1000 * 60 * 10, // 10分钟

    // 重试配置
    RETRY_COUNT: 3,
    RETRY_DELAY: 1000,

    // 响应状态码
    SUCCESS_CODES: [200, 201, 204],

    // 错误处理配置
    SHOW_ERROR_MESSAGE: true,
    SHOW_SUCCESS_MESSAGE: false
}

// 业务状态码
export const BUSINESS_CODES = {
    SUCCESS: 200,
    UNAUTHORIZED: 401,
    FORBIDDEN: 403,
    NOT_FOUND: 404,
    SERVER_ERROR: 500,
    TIMEOUT: 408
}

// 创建请求实例
class Request {
    constructor(config = {}) {
        this.baseURL = config.baseURL || CONFIG.baseURL
        this.timeout = config.timeout || CONFIG.timeout
        this.withCredentials = config.withCredentials !== false

        // 请求拦截器
        this.requestInterceptors = []
        this.responseInterceptors = []
        this.errorInterceptors = []

        // 添加默认拦截器
        this.addDefaultInterceptors()
    }

    // 添加默认拦截器
    addDefaultInterceptors() {
        this.requestInterceptors.push((config) => {
            const isFormData = config && config.data && (typeof FormData !== 'undefined') && (config.data instanceof FormData)
            // 从本地存储获取语言（Pinia store 会同步写入 localStorage）
            const savedLanguage = (typeof localStorage !== 'undefined') ? localStorage.getItem('language') : null
            const preferEn = savedLanguage === 'enUS' || savedLanguage === 'en' || savedLanguage === 'en-US'
            const preferPt = savedLanguage === 'ptBR' || savedLanguage === 'pt' || savedLanguage === 'pt-BR'
            const acceptLanguage = preferPt
                ? 'pt-BR,pt;q=0.9'
                : (preferEn ? 'en-US,en;q=0.9' : 'zh-CN,zh;q=0.9')
            const xAcceptLanguage = preferPt ? 'pt' : (preferEn ? 'en' : 'zh')
            const headers = {
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': acceptLanguage,
                'X-accept-language': xAcceptLanguage,
                ...config.headers
            }
            const token = (typeof localStorage !== 'undefined') ? localStorage.getItem('access_token') : null
            if (token) {
                headers['Authorization'] = `Bearer ${token}`
            }
            if (!isFormData) {
                headers['Content-Type'] = 'application/json;charset=UTF-8'
            }
            return {...config, headers}
        })

        // 响应拦截器 - 统一处理响应数据
        this.responseInterceptors.push((response, config) => {
            // 检查业务状态码
            if (response.code !== undefined) {
                if (response.code === 200) {
                    return {
                        success: true,
                        data: response.data,
                        message: response.message,
                        requestId: response.request_id
                    }
                } else {
                    // 全局弹窗提示
                    if (response.message) {
                        // alert(response.message)
                        console.error(response.message)
                    }
                    return {
                        success: false,
                        code: response.code,
                        message: response.message || '请求失败',
                        requestId: response.request_id
                    }
                }
            }

            // 如果没有业务状态码，直接返回数据
            return {success: true, data: response}
        })

        // 错误拦截器 - 统一处理错误
        this.errorInterceptors.push((error, config) => {
            console.log(JSON.stringify(error, null, 2))

            let message = '网络请求失败'
            let code = 'NETWORK_ERROR'

            if (error.name === 'AbortError') {
                message = '请求超时'
                code = 'TIMEOUT'
            } else if (error.message === 'Failed to fetch') {
                message = '网络连接失败，请检查网络状态'
                code = 'NETWORK_ERROR'
            } else if (error.status) {
                switch (error.status) {
                    case 401:
                        message = '未授权，请重新登录'
                        code = 'UNAUTHORIZED'
                        // 清除登录状态（但不能清除 HttpOnly cookie）
                        localStorage.removeItem('userInfo')
                        localStorage.removeItem('isLoggedIn')
                        localStorage.removeItem('loginTime')
                        if (typeof window !== 'undefined') {
                            window.dispatchEvent(new CustomEvent('user-updated'))
                        }
                        break
                    case 403:
                        message = '权限不足'
                        code = 'FORBIDDEN'
                        break
                    case 404:
                        message = '请求的资源不存在'
                        code = 'NOT_FOUND'
                        break
                    case 500:
                        // alert(error.response.message)
                        message = error.response.message || '服务器内部错误'
                        code = 'SERVER_ERROR'
                        break
                    default:
                        message = `请求失败 (${error.status})`
                }
            }

            return {
                success: false,
                code,
                message,
                error
            }
        })
    }

    // 执行请求拦截器
    async executeRequestInterceptors(config) {
        let result = config
        for (const interceptor of this.requestInterceptors) {
            result = await interceptor(result)
        }
        return result
    }

    // 执行响应拦截器
    async executeResponseInterceptors(response, config) {
        let result = response
        for (const interceptor of this.responseInterceptors) {
            result = await interceptor(result, config)
        }
        return result
    }

    // 执行错误拦截器
    async executeErrorInterceptors(error, config) {
        let result = error
        for (const interceptor of this.errorInterceptors) {
            result = await interceptor(result, config)
        }
        return result
    }

    // 处理响应
    handleResponse(response) {
        // request.js已经处理了响应格式化，直接返回
        if (response.success) {
            return response.data
        } else {
            // 如果不成功，抛出错误让上层处理
            const error = new Error(response.message || '请求失败')
            error.code = response.code
            error.response = response
            throw error
        }
    }

    // 处理错误
    async handleError(error, method, url) {
        console.error(`API ${method} ${url} 失败:`, error)

        // 如果是request.js返回的格式化错误响应，直接抛出
        if (error.success === false) {
            throw error
        }

        // 其他错误，包装后抛出
        const wrappedError = new Error(error.message || '网络请求失败')
        wrappedError.code = error.code || 'NETWORK_ERROR'
        wrappedError.originalError = error
        throw wrappedError
    }

    // 基础请求方法
    async request(config) {
        let timeoutId = null
        let externalSignal = null
        let abortFromExternal = null
        try {
            // 处理配置
            const finalConfig = await this.executeRequestInterceptors({
                baseURL: this.baseURL,
                timeout: this.timeout,
                credentials: this.withCredentials ? 'include' : 'omit',
                ...config
            })

            // 处理查询参数
            if (finalConfig.params) {
                const queryString = new URLSearchParams(finalConfig.params).toString()
                if (queryString) {
                    finalConfig.url += (finalConfig.url.includes('?') ? '&' : '?') + queryString
                }
            }

            // 构建完整URL
            const url = finalConfig.url.startsWith('http')
                ? finalConfig.url
                : `${finalConfig.baseURL}${finalConfig.url}`


            // 创建AbortController用于超时控制，并兼容外部取消
            const controller = new AbortController()
            externalSignal = finalConfig.signal
            abortFromExternal = () => controller.abort()
            if (externalSignal) {
                if (externalSignal.aborted) {
                    controller.abort()
                } else {
                    externalSignal.addEventListener('abort', abortFromExternal, { once: true })
                }
            }
            timeoutId = finalConfig.timeout ? setTimeout(() => controller.abort(), finalConfig.timeout) : null

            // 构建fetch选项
            const fetchOptions = {
                method: finalConfig.method || 'GET',
                headers: finalConfig.headers,
                credentials: finalConfig.credentials,
                signal: controller.signal
            }

            const isFormData = finalConfig && finalConfig.data && (typeof FormData !== 'undefined') && (finalConfig.data instanceof FormData)
            if (finalConfig.data && ['POST', 'PUT', 'PATCH'].includes(fetchOptions.method)) {
                fetchOptions.body = isFormData ? finalConfig.data : JSON.stringify(finalConfig.data)
                if (isFormData && fetchOptions.headers && 'Content-Type' in fetchOptions.headers) {
                    delete fetchOptions.headers['Content-Type']
                }
            }

            // 发送请求
            const response = await fetch(url, fetchOptions)

            // 检查响应状态
            if (!response.ok) {
                let errorData = null
                try {
                    const contentType = response.headers.get('content-type') || ''
                    if (contentType.includes('application/json')) {
                        errorData = await response.json()
                    } else {
                        const text = await response.text()
                        errorData = {detail: text}
                    }
                } catch (e) {
                    errorData = null
                }

                const detailMessage = errorData && (errorData.detail || errorData.message)
                    ? (errorData.detail || errorData.message)
                    : `HTTP ${response.status}`

                throw Object.assign(new Error(detailMessage), {
                    status: response.status,
                    statusText: response.statusText,
                    response: errorData
                })
            }

            // 解析响应
            const data = await response.json()

            // 执行响应拦截器
            return await this.executeResponseInterceptors(data, finalConfig)

        } catch (error) {
            // 执行错误拦截器
            return await this.executeErrorInterceptors(error, config)
        } finally {
            if (timeoutId) clearTimeout(timeoutId)
            if (externalSignal) externalSignal.removeEventListener('abort', abortFromExternal)
        }
    }

    // GET请求
    async get(url, params = {}, config = {}) {
        try {
            // 处理查询参数
            const queryString = Object.keys(params).length > 0
                ? '?' + new URLSearchParams(params).toString()
                : ''

            const response = await this.request({
                method: 'GET',
                url: url + queryString,
                ...config
            })
            return this.handleResponse(response)
        } catch (error) {
            return this.handleError(error, 'GET', url)
        }
    }

    // POST请求
    async post(url, data = {}, config = {}) {
        try {
            const response = await this.request({
                method: 'POST',
                url,
                data,
                ...config
            })
            return this.handleResponse(response)
        } catch (error) {
            return this.handleError(error, 'POST', url)
        }
    }

    // PUT请求
    async put(url, data = {}, config = {}) {
        try {
            const response = await this.request({
                method: 'PUT',
                url,
                data,
                ...config
            })
            return this.handleResponse(response)
        } catch (error) {
            return this.handleError(error, 'PUT', url)
        }
    }

    // DELETE请求
    async delete(url, config = {}) {
        try {
            const response = await this.request({
                method: 'DELETE',
                url,
                ...config
            })
            return this.handleResponse(response)
        } catch (error) {
            return this.handleError(error, 'DELETE', url)
        }
    }

    // PATCH请求
    async patch(url, data = {}, config = {}) {
        try {
            const response = await this.request({
                method: 'PATCH',
                url,
                data,
                ...config
            })
            return this.handleResponse(response)
        } catch (error) {
            return this.handleError(error, 'PATCH', url)
        }
    }

    /**
     * 流式POST请求
     * @param {string} url - 请求URL
     * @param {Object} data - 请求数据
     * @param {Object} config - 请求配置
     * @returns {Promise<Response>}
     */
    async postStream(url, data = {}, config = {}) {
        try {
            // 直接使用request.js的底层request方法，但不解析JSON
            const finalConfig = await this.executeRequestInterceptors({
                baseURL: this.baseURL,
                timeout: this.timeout,
                credentials: this.withCredentials ? 'include' : 'omit',
                method: 'POST',
                url,
                data,
                ...config
            })

            // 构建完整URL
            const fullUrl = finalConfig.url.startsWith('http')
                ? finalConfig.url
                : `${finalConfig.baseURL}${finalConfig.url}`

            // 创建AbortController用于超时控制
            const controller = config.signal || new AbortController()
            const timeoutId = !config.signal ? setTimeout(() => controller.abort(), finalConfig.timeout) : null

            // 构建fetch选项
            const fetchOptions = {
                method: 'POST',
                headers: finalConfig.headers,
                credentials: finalConfig.credentials,
                signal: controller.signal,
                body: JSON.stringify(finalConfig.data)
            }

            // 发送请求
            const response = await fetch(fullUrl, fetchOptions)
            if (timeoutId) clearTimeout(timeoutId)

            // 检查响应状态
            if (!response.ok) {
                let errorData = null
                try {
                    const contentType = response.headers.get('content-type') || ''
                    if (contentType.includes('application/json')) {
                        errorData = await response.json()
                    } else {
                        const text = await response.text()
                        errorData = {detail: text}
                    }
                } catch (e) {
                    errorData = null
                }

                const detailMessage = errorData && (errorData.detail || errorData.message)
                    ? (errorData.detail || errorData.message)
                    : `HTTP ${response.status}`

                throw Object.assign(new Error(detailMessage), {
                    status: response.status,
                    statusText: response.statusText,
                    response: errorData
                })
            }

            return response
        } catch (error) {
            return this.handleError(error, 'POST_STREAM', url)
        }
    }

    /**
     * 流式GET请求
     * @param {string} url - 请求URL
     * @param {Object} config - 请求配置
     * @returns {Promise<Response>}
     */
    async getStream(url, config = {}) {
        try {
            const finalConfig = await this.executeRequestInterceptors({
                baseURL: this.baseURL,
                timeout: this.timeout,
                credentials: this.withCredentials ? 'include' : 'omit',
                method: 'GET',
                url,
                ...config
            })

            const fullUrl = finalConfig.url.startsWith('http')
                ? finalConfig.url
                : `${finalConfig.baseURL}${finalConfig.url}`

            const controller = config.signal || new AbortController()
            const timeoutId = !config.signal ? setTimeout(() => controller.abort(), finalConfig.timeout) : null

            const fetchOptions = {
                method: 'GET',
                headers: finalConfig.headers,
                credentials: finalConfig.credentials,
                signal: controller.signal
            }

            const response = await fetch(fullUrl, fetchOptions)
            if (timeoutId) clearTimeout(timeoutId)

            if (!response.ok) {
                let errorData = null
                try {
                    const contentType = response.headers.get('content-type') || ''
                    if (contentType.includes('application/json')) {
                        errorData = await response.json()
                    } else {
                        const text = await response.text()
                        errorData = {detail: text}
                    }
                } catch (e) {
                    errorData = null
                }

                const detailMessage = errorData && (errorData.detail || errorData.message)
                    ? (errorData.detail || errorData.message)
                    : `HTTP ${response.status}`

                throw Object.assign(new Error(detailMessage), {
                    status: response.status,
                    statusText: response.statusText,
                    response: errorData
                })
            }

            return response
        } catch (error) {
            return this.handleError(error, 'GET_STREAM', url)
        }
    }

    /**
     * SSE请求
     * @param {string} url - 请求URL
     * @param {Object} config - 请求配置
     * @returns {Promise<EventSource>}
     */
    async sse(url, config = {}) {
        // 直接复用 request.js 的拦截器逻辑构建 URL
        const finalConfig = await this.executeRequestInterceptors({
            baseURL: this.baseURL,
            timeout: this.timeout,
            credentials: this.withCredentials ? 'include' : 'omit',
            method: 'GET',
            url,
            ...config
        })

        const fullUrl = finalConfig.url.startsWith('http')
            ? finalConfig.url
            : `${finalConfig.baseURL}${finalConfig.url}`

        // 使用 EventSource
        return new EventSource(fullUrl, {
            withCredentials: finalConfig.credentials === 'include'
        })
    }

    // 添加请求拦截器
    addRequestInterceptor(interceptor) {
        this.requestInterceptors.push(interceptor)
    }

    // 添加响应拦截器
    addResponseInterceptor(interceptor) {
        this.responseInterceptors.push(interceptor)
    }

    // 添加错误拦截器
    addErrorInterceptor(interceptor) {
        this.errorInterceptors.push(interceptor)
    }
}

// 创建默认实例
const request = new Request()

// 导出默认实例和类
export default request
export {Request}

// 动态设置 Base URL
export const setBaseURL = (url) => {
    console.log('[Request] Updating Base URL to:', url)
    request.baseURL = url
}

// 便捷方法
export const get = (url, params, config) => request.get(url, params, config)
export const post = (url, data, config) => request.post(url, data, config)
export const put = (url, data, config) => request.put(url, data, config)
export const del = (url, config) => request.delete(url, config)
export const patch = (url, data, config) => request.patch(url, data, config)
export const postStream = (url, data, config) => request.postStream(url, data, config)
export const getStream = (url, config) => request.getStream(url, config)
export const sse = (url, config) => request.sse(url, config)
