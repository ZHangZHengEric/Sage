import { computed } from 'vue'
import { useAppStore } from '../stores/index.js'
import { zhCN, enUS } from './i18n.js'

// 翻译对象映射
const translations = {
  zhCN: zhCN,
  enUS: enUS
}

export function useLanguage() {
  const appStore = useAppStore()
  
  // 当前翻译对象
  const currentTranslation = computed(() => {
    return translations[appStore.language] || translations.zhCN
  })
  
  // 翻译函数
  const t = (key, params = {}) => {
    const translation = currentTranslation.value
    let text = translation[key] || key
    
    // 处理参数替换
    if (params && typeof params === 'object') {
      Object.keys(params).forEach(param => {
        const regex = new RegExp(`\\{${param}\\}`, 'g')
        text = text.replace(regex, params[param])
      })
    }
    
    return text
  }

  // 切换语言
  const toggleLanguage = () => {
    appStore.toggleLanguage()
  }

  // 设置语言
  const setLanguage = (lang) => {
    if (translations[lang]) {
      appStore.setLanguage(lang)
    }
  }

  return {
    language: computed(() => appStore.language),
    currentLanguage: computed(() => appStore.language),
    t,
    toggleLanguage,
    setLanguage,
    isZh: computed(() => appStore.isZhCN),
    isEn: computed(() => appStore.isEnUS),
    isZhCN: computed(() => appStore.isZhCN),
    isEnUS: computed(() => appStore.isEnUS)
  }
}