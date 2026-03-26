import Cookies from 'js-cookie'

export function getCookie(key) {
  return Cookies.get(key)
}
export function setCookie(key,value) {
  return Cookies.set(key,value)
}
export function removeCookie(key) {
   Cookies.remove(key)
}


import { userAPI } from '../api/user.js'

export const getApiPrefix = () => import.meta.env.VITE_BACKEND_API_PREFIX || ''

export const buildOAuthLoginUrl = (providerId, nextPath = null) => {
  const apiPrefix = getApiPrefix()
  const nextUrl = nextPath || (
    typeof window !== 'undefined'
      ? `${window.location.pathname}${window.location.search}${window.location.hash}`
      : '/agent/chat'
  )
  const redirectUri = typeof window !== 'undefined'
    ? `${window.location.origin}${apiPrefix}/api/auth/upstream/callback/${providerId}`
    : `${apiPrefix}/api/auth/upstream/callback/${providerId}`

  return `${apiPrefix}/api/auth/upstream/login/${encodeURIComponent(providerId)}?next=${encodeURIComponent(nextUrl)}&redirect_uri=${encodeURIComponent(redirectUri)}`
}

// 登录 API - 不再检查前端 cookie
export const loginAPI = async (username, password) => {
  try {
    const res = await userAPI.login(username, password)
    // res is data
    const { access_token, refresh_token, expires_in } = res || {}
    if (access_token) localStorage.setItem('access_token', access_token)
    if (refresh_token) localStorage.setItem('refresh_token', refresh_token)
    localStorage.setItem('token_expires_in', String(expires_in || 0))
    localStorage.setItem('isLoggedIn', 'true')
    localStorage.setItem('loginTime', Date.now().toString())
    
    try {
      const me = await userAPI.checkLogin()
      if (me) {
        const userInfo = { ...me.user, has_provider: me.has_provider, has_agent: me.has_agent }
        localStorage.setItem('userInfo', JSON.stringify(userInfo))
        setCookie('username', (userInfo.username) || username)
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('user-updated'))
        }
      }
    } catch (e) { console.error('Failed to fetch user info after login', e) }

    lastCheckTime = 0
    lastCheckResult = null
    return { success: true, data: res }
  } catch (error) {
    return { success: false, message: error.message || '网络请求失败，请检查网络连接' }
  }
}

export const sendRegisterVerificationCodeAPI = async (email) => {
  try {
    const res = await userAPI.sendRegisterVerificationCode(email)
    return { success: true, data: res }
  } catch (error) {
    return { success: false, message: error.message || '验证码发送失败，请稍后重试' }
  }
}

export const registerAPI = async (username, password, email = '', phonenum = '', verificationCode = '') => {
  try {
    await userAPI.register(username, password, email, phonenum, verificationCode)
    const loginRes = await loginAPI(username, password)
    return loginRes
  } catch (error) {
    return { success: false, message: error.message || '网络请求失败，请检查网络连接' }
  }
}

// 检查登录状态 API - 完全依赖服务器验证
export const checkLoginAPI = async () => {
  try {
    const result = await userAPI.checkLogin()
    const previousUserInfo = localStorage.getItem('userInfo')
    const previousLoginFlag = localStorage.getItem('isLoggedIn')
    
    // 服务器确认登录有效，更新本地状态
    localStorage.setItem('isLoggedIn', 'true')
    localStorage.setItem('loginTime', Date.now().toString())
    
    // 如果服务器返回了用户信息，更新本地用户信息
    if (result && result.user) {
      const userInfo = { ...result.user, has_provider: result.has_provider, has_agent: result.has_agent }
      const serializedUserInfo = JSON.stringify(userInfo)
      localStorage.setItem('userInfo', serializedUserInfo)
      if (typeof window !== 'undefined' && (serializedUserInfo !== previousUserInfo || previousLoginFlag !== 'true')) {
        window.dispatchEvent(new CustomEvent('user-updated'))
      }
    }
    
    return { success: true, data: result }
  } catch (error) {
    
    // 网络错误时的处理策略
    if (error.code === 'UNAUTHORIZED' || error.code === 'FORBIDDEN') {
      // 明确的认证失败，清除本地状态
      clearLocalLoginState()
      return { success: false, message: '登录状态已失效', code: error.code }
    } else {
      // 网络错误等，不清除本地状态
      return { success: false, message: '网络错误，无法验证登录状态', isNetworkError: true }
    }
  }
}

// 清除本地登录状态的统一方法
const clearLocalLoginState = () => {
  removeCookie('username')
  removeCookie('ticket')
  removeCookie('refresh_token')
  localStorage.removeItem('userInfo')
  localStorage.removeItem('isLoggedIn')
  localStorage.removeItem('loginTime')
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('token_expires_in')
  lastCheckTime = 0
  lastCheckResult = null
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('user-updated'))
  }
}

// 退出登录
export const logout = async () => {
  try {
    await userAPI.logout()
  } catch (error) {
    console.error('服务端退出登录失败:', error)
  } finally {
    clearLocalLoginState()
  }
}

// 获取当前用户信息
export const getCurrentUser = () => {
  const userInfo = localStorage.getItem('userInfo')
  return userInfo ? JSON.parse(userInfo) : null
}

// 基于API的登录状态检查 - 主要方法
export const isLoggedInAPI = async () => {
  const user = getCurrentUser()
  const localLoginFlag = localStorage.getItem('isLoggedIn')

  try {
    // 调用API验证服务器端登录状态
    const result = await checkLoginAPI()
    
    if (result.success) {
      return { 
        isLoggedIn: true, 
        user: result.data || user,
        apiResult: result
      }
    } else {
      if (!user || localLoginFlag !== 'true') {
        return {
          isLoggedIn: false,
          user: null,
          apiResult: result
        }
      }
      return { 
        isLoggedIn: false, 
        user: null,
        apiResult: result
      }
    }
  } catch (error) {
    console.error('API验证过程出错:', error)
    
    // 如果是网络错误，可以选择信任本地状态（可配置）
    if (error.isNetworkError && user && localLoginFlag === 'true') {
      return { 
        isLoggedIn: true, 
        user: user,
        isNetworkError: true
      }
    } else {
      // 其他错误认为未登录
      return { 
        isLoggedIn: false, 
        user: null,
        error: error
      }
    }
  }
}

// 同步版本的登录状态检查（用于兼容现有代码）
export const isLoggedIn = () => {
  const user = getCurrentUser()
  const loginFlag = localStorage.getItem('isLoggedIn')
  const result = !!(user && loginFlag === 'true')
  
  return result
}


// 定期验证登录状态的工具函数
export const startPeriodicLoginCheck = (intervalMinutes = 30, onLoginExpired = null) => {
  const interval = intervalMinutes * 60 * 1000 // 转换为毫秒
  
  const checkInterval = setInterval(async () => {
    
    const user = getCurrentUser()
    if (!user) {
      clearInterval(checkInterval)
      return
    }
    
    try {
      const loginResult = await isLoggedInAPI()
      
      if (!loginResult.isLoggedIn) {
        clearInterval(checkInterval)
        
        if (onLoginExpired && typeof onLoginExpired === 'function') {
          onLoginExpired()
        }
      } else {
      }
    } catch (error) {
      console.error('定期登录检查出错:', error)
      // 网络错误不清除定时器，继续检查
    }
  }, interval)
  
  
  // 返回清理函数
  return () => {
    clearInterval(checkInterval)
  }
}

// 快速验证登录状态（带缓存）
let lastCheckTime = 0
let lastCheckResult = null
const CACHE_DURATION = 60 * 1000 // 缓存1分钟

export const quickLoginCheck = async (forceFresh = false) => {
  const now = Date.now()
  
  // 如果不强制刷新且缓存有效，返回缓存结果
  if (!forceFresh && lastCheckResult && (now - lastCheckTime) < CACHE_DURATION) {
    return lastCheckResult
  }
  
  const result = await isLoggedInAPI()
  
  // 更新缓存
  lastCheckTime = now
  lastCheckResult = result
  
  return result
}
