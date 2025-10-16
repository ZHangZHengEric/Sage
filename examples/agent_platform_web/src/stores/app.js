import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAppStore = defineStore('app', () => {
  // 状态
  const language = ref('zhCN') // 默认中文
  const theme = ref('light') // 主题
  const sidebarCollapsed = ref(false) // 侧边栏折叠状态
  const loading = ref(false) // 全局加载状态
  const error = ref(null) // 全局错误状态
  
  // 计算属性
  const isZhCN = computed(() => language.value === 'zhCN')
  const isEnUS = computed(() => language.value === 'enUS')
  const isDarkTheme = computed(() => theme.value === 'dark')
  
  // 方法
  const setLanguage = (lang) => {
    language.value = lang
    // 保存到本地存储
    localStorage.setItem('language', lang)
  }
  
  const toggleLanguage = () => {
    const newLang = language.value === 'zhCN' ? 'enUS' : 'zhCN'
    setLanguage(newLang)
  }
  
  const setTheme = (newTheme) => {
    theme.value = newTheme
    localStorage.setItem('theme', newTheme)
    // 更新HTML类名
    document.documentElement.className = newTheme
  }
  
  const toggleTheme = () => {
    const newTheme = theme.value === 'light' ? 'dark' : 'light'
    setTheme(newTheme)
  }
  
  const toggleSidebar = () => {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }
  
  const setSidebarCollapsed = (collapsed) => {
    sidebarCollapsed.value = collapsed
  }
  
  const setLoading = (isLoading) => {
    loading.value = isLoading
  }
  
  const setError = (errorMessage) => {
    error.value = errorMessage
  }
  
  const clearError = () => {
    error.value = null
  }
  
  // 初始化
  const initialize = () => {
    // 从本地存储恢复语言设置
    const savedLanguage = localStorage.getItem('language')
    if (savedLanguage && ['zhCN', 'enUS'].includes(savedLanguage)) {
      language.value = savedLanguage
    }
    
    // 从本地存储恢复主题设置
    const savedTheme = localStorage.getItem('theme')
    if (savedTheme && ['light', 'dark'].includes(savedTheme)) {
      setTheme(savedTheme)
    }
  }
  
  return {
    // 状态
    language,
    theme,
    sidebarCollapsed,
    loading,
    error,
    
    // 计算属性
    isZhCN,
    isEnUS,
    isDarkTheme,
    
    // 方法
    setLanguage,
    toggleLanguage,
    setTheme,
    toggleTheme,
    toggleSidebar,
    setSidebarCollapsed,
    setLoading,
    setError,
    clearError,
    initialize
  }
})