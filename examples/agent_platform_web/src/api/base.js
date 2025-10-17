/**
 * API基础服务
 * 封装通用的API调用逻辑，使用统一的request.js进行参数处理
 */

import request from '../utils/request.js'

// 请求配置
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
/**
 * 基础API服务类
 */
export class BaseAPI {
  constructor() {
    this.request = request
  }

  /**
   * GET请求
   * @param {string} url - 请求URL
   * @param {Object} params - 查询参数
   * @param {Object} config - 请求配置
   * @returns {Promise<any>}
   */
  async get(url, params = {}, config = {}) {
    try {
      const response = await this.request.get(url, params, {
        timeout: REQUEST_CONFIG.DEFAULT_TIMEOUT,
        ...config
      })
      return this.handleResponse(response)
    } catch (error) {
      return this.handleError(error, 'GET', url)
    }
  }

  /**
   * POST请求
   * @param {string} url - 请求URL
   * @param {Object} data - 请求数据
   * @param {Object} config - 请求配置
   * @returns {Promise<any>}
   */
  async post(url, data = {}, config = {}) {
    try {
      const response = await this.request.post(url, data, {
        timeout: REQUEST_CONFIG.DEFAULT_TIMEOUT,
        ...config
      })
      return this.handleResponse(response)
    } catch (error) {
      return this.handleError(error, 'POST', url)
    }
  }

  /**
   * PUT请求
   * @param {string} url - 请求URL
   * @param {Object} data - 请求数据
   * @param {Object} config - 请求配置
   * @returns {Promise<any>}
   */
  async put(url, data = {}, config = {}) {
    try {
      const response = await this.request.put(url, data, {
        timeout: REQUEST_CONFIG.DEFAULT_TIMEOUT,
        ...config
      })
      return this.handleResponse(response)
    } catch (error) {
      return this.handleError(error, 'PUT', url)
    }
  }

  /**
   * DELETE请求
   * @param {string} url - 请求URL
   * @param {Object} config - 请求配置
   * @returns {Promise<any>}
   */
  async delete(url, config = {}) {
    try {
      const response = await this.request.delete(url, {
        timeout: REQUEST_CONFIG.DEFAULT_TIMEOUT,
        ...config
      })
      return this.handleResponse(response)
    } catch (error) {
      return this.handleError(error, 'DELETE', url)
    }
  }

  /**
   * PATCH请求
   * @param {string} url - 请求URL
   * @param {Object} data - 请求数据
   * @param {Object} config - 请求配置
   * @returns {Promise<any>}
   */
  async patch(url, data = {}, config = {}) {
    try {
      const response = await this.request.patch(url, data, {
        timeout: REQUEST_CONFIG.DEFAULT_TIMEOUT,
        ...config
      })
      return this.handleResponse(response)
    } catch (error) {
      return this.handleError(error, 'PATCH', url)
    }
  }

  /**
   * 处理响应
   * @param {Object} response - 响应对象
   * @returns {any}
   */
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
      const finalConfig = await this.request.executeRequestInterceptors({
        baseURL: this.request.baseURL,
        timeout: this.request.timeout,
        credentials: this.request.withCredentials ? 'include' : 'omit',
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
        signal: controller,
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
   * 处理错误
   * @param {Error} error - 错误对象
   * @param {string} method - 请求方法
   * @param {string} url - 请求URL
   * @returns {Promise<never>}
   */
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
}

// 创建默认实例
export const baseAPI = new BaseAPI()

// 导出便捷方法
export const { get, post, put, delete: del, patch, postStream } = baseAPI