import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router.js'
import './styles.css'
import { readThemePreference, resolveTheme } from './theme.js'

document.documentElement.dataset.theme = resolveTheme(readThemePreference(localStorage), window.matchMedia('(prefers-color-scheme: dark)').matches)

createApp(App).use(router).mount('#app')
