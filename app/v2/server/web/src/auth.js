import { shallowRef } from 'vue'

const user = shallowRef(null)

function removeLegacySession() {
  localStorage.removeItem('sage.server_v2.token')
  localStorage.removeItem('sage.server_v2.user')
}

export function getUser() {
  return user.value
}

export function setSession(value) {
  removeLegacySession()
  user.value = value
}

export function clearSession() {
  removeLegacySession()
  user.value = null
}

export function csrfHeaders() {
  const cookie = globalThis.document?.cookie || ''
  const value = cookie.split('; ').find(item => item.startsWith('sage_server_v2_csrf='))?.split('=')[1]
  return value ? { 'X-CSRF-Token': decodeURIComponent(value) } : {}
}

export function isAdmin() {
  return getUser()?.role === 'admin'
}
