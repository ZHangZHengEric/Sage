import { computed } from 'vue'
import { useLanguageStore } from '../stores/language'
import { storeToRefs } from 'pinia'

// Re-export store for compatibility
export { useLanguageStore }

export function useLanguage() {
  const store = useLanguageStore()
  const { language, isZhCN, isEnUS } = storeToRefs(store)

  return {
    language,
    currentLanguage: language,
    t: store.t,
    toggleLanguage: store.toggleLanguage,
    setLanguage: store.setLanguage,
    isZh: isZhCN,
    isEn: isEnUS,
    isZhCN,
    isEnUS
  }
}
