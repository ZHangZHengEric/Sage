// Cookie 处理已改为 js-cookie 库

const apiPrefix =  '';  // 默认空字符串，如果没有设置前缀

// API基础配置
const CONFIG = {
    baseURL: apiPrefix, // url = base url + request url
    withCredentials: true, // send cookies when cross-domain requests
    timeout: 1000 * 60 * 10 // request timeout
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
        // 请求拦截器 - 添加通用头信息
        this.requestInterceptors.push((config) => {
            const headers = {
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json;charset=UTF-8',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'X-accept-language': 'zh',
                ...config.headers
            }

            // 注意：不再尝试从 cookie 获取 ticket，因为 HttpOnly cookie 无法被 JS 读取
            // 认证将完全依赖服务器端的 cookie 验证

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
                        alert(response.message)
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
                        const {removeCookie} = require('./auth.js')
                        localStorage.removeItem('userInfo')
                        localStorage.removeItem('isLoggedIn')
                        localStorage.removeItem('loginTime')
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
                        alert(error.response.message)
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

    // 基础请求方法
    async request(config) {
        try {
            // 处理配置
            const finalConfig = await this.executeRequestInterceptors({
                baseURL: this.baseURL,
                timeout: this.timeout,
                credentials: this.withCredentials ? 'include' : 'omit',
                ...config
            })

            // 构建完整URL
            const url = finalConfig.url.startsWith('http')
                ? finalConfig.url
                : `${finalConfig.baseURL}${finalConfig.url}`


            // 创建AbortController用于超时控制
            const controller = new AbortController()
            const timeoutId = setTimeout(() => controller.abort(), finalConfig.timeout)

            // 构建fetch选项
            const fetchOptions = {
                method: finalConfig.method || 'GET',
                headers: finalConfig.headers,
                credentials: finalConfig.credentials,
                signal: controller.signal
            }

            // 添加请求体
            if (finalConfig.data && ['POST', 'PUT', 'PATCH'].includes(fetchOptions.method)) {
                fetchOptions.body = JSON.stringify(finalConfig.data)
            }

            // 发送请求
            const response = await fetch(url, fetchOptions)
            clearTimeout(timeoutId)

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
        }
    }

    // GET请求
    get(url, params = {}, config = {}) {
        // 处理查询参数
        const queryString = Object.keys(params).length > 0
            ? '?' + new URLSearchParams(params).toString()
            : ''

        return this.request({
            method: 'GET',
            url: url + queryString,
            ...config
        })
    }

    // POST请求
    post(url, data = {}, config = {}) {
        return this.request({
            method: 'POST',
            url,
            data,
            ...config
        })
    }

    // PUT请求
    put(url, data = {}, config = {}) {
        return this.request({
            method: 'PUT',
            url,
            data,
            ...config
        })
    }

    // DELETE请求
    delete(url, config = {}) {
        return this.request({
            method: 'DELETE',
            url,
            ...config
        })
    }

    // PATCH请求
    patch(url, data = {}, config = {}) {
        return this.request({
            method: 'PATCH',
            url,
            data,
            ...config
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

// 便捷方法
export const get = (url, params, config) => request.get(url, params, config)
export const post = (url, data, config) => request.post(url, data, config)
export const put = (url, data, config) => request.put(url, data, config)
export const del = (url, config) => request.delete(url, config)
export const patch = (url, data, config) => request.patch(url, data, config)