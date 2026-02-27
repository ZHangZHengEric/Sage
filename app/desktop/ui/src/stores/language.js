import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import zhCN from '../locales/zh-CN'
import enUS from '../locales/en-US'

export const useLanguageStore = defineStore('app-language', () => {
  // 状态
  const language = ref('zhCN') // 默认中文

  // 计算属性
  const isZhCN = computed(() => language.value === 'zhCN')
  const isEnUS = computed(() => language.value === 'enUS')

  // 获取翻译
  const t = (key, params = {}) => {
    const messages = language.value === 'zhCN' ? zhCN : enUS
    let text = messages[key] || key
    
    // 处理参数替换
    if (params) {
      Object.keys(params).forEach(param => {
        text = text.replace(`{${param}}`, params[param])
      })
    }
    
    return text
  }

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

  // 初始化
  const initialize = () => {
    // 从本地存储恢复语言设置
    const savedLanguage = localStorage.getItem('language')
    if (savedLanguage && ['zhCN', 'enUS'].includes(savedLanguage)) {
      language.value = savedLanguage
    }
  }

  return {
    // 状态
    language,

    // 计算属性
    isZhCN,
    isEnUS,

    // 方法
    setLanguage,
    toggleLanguage,
    initialize,
    t
  }
})
