import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useThemeStore = defineStore('theme', () => {
  const theme = ref('system')
  const systemDark = ref(false)

  const updateSystemTheme = (e) => {
    systemDark.value = e.matches
    if (theme.value === 'system') {
      applyTheme()
    }
  }

  const isDark = computed(() => {
    if (theme.value === 'system') {
      return systemDark.value
    }
    return theme.value === 'dark'
  })

  const applyTheme = () => {
    const root = window.document.documentElement
    root.classList.remove('light', 'dark')

    if (theme.value === 'system') {
      root.classList.add(systemDark.value ? 'dark' : 'light')
    } else {
      root.classList.add(theme.value)
    }
  }
  
  const setTheme = (newTheme) => {
    theme.value = newTheme
    localStorage.setItem('theme', newTheme)
    applyTheme()
  }

  const initTheme = () => {
    const savedTheme = localStorage.getItem('theme')
    if (savedTheme) {
      theme.value = savedTheme
    }
    
    // Initial system check
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    systemDark.value = mediaQuery.matches
    
    // Listener
    mediaQuery.addEventListener('change', updateSystemTheme)
    
    applyTheme()
  }

  return {
    theme,
    isDark,
    setTheme,
    initTheme
  }
})
