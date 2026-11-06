import { createApp } from 'vue'
import App from './App.vue'
import { api } from './api.js'
import { clearSession, setSession } from './auth.js'
import { router } from './router.js'
import './styles.css'
import { readThemePreference, resolveTheme } from './theme.js'

document.documentElement.dataset.theme = resolveTheme(readThemePreference(localStorage), window.matchMedia('(prefers-color-scheme: dark)').matches)

async function start() {
  clearSession()
  try {
    setSession(await api.session())
  } catch {
    // The public login page is also available when the server is unreachable.
  }
  createApp(App).use(router).mount('#app')
}

start()
