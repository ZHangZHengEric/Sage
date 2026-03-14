import { createApp } from 'vue'
import './assets/index.css'
import 'vue-sonner/style.css'
import App from './App.vue'

// 导入路由和状态管理
import router from './router'
import { createPinia } from 'pinia'
import { useLanguageStore } from './utils/i18n.js'
import { useThemeStore } from './stores/theme.js'

const pinia = createPinia()

const app = createApp(App)

app.use(router)
app.use(pinia)

// 初始化应用状态
const initializeApp = async () => {
  const appStore = useLanguageStore()
  const themeStore = useThemeStore()
  
  try {
    // 初始化应用设置
    appStore.initialize()
    themeStore.initTheme()
    console.log('Application initialized successfully')
  } catch (error) {
    console.error('Failed to initialize application:', error)
  }
}

// 阻止默认的拖拽行为，允许文件拖拽
window.addEventListener('dragover', (e) => {
  e.preventDefault()
})

window.addEventListener('drop', (e) => {
  // 只允许特定区域的drop事件
  const target = e.target
  const isInWorkspace = target.closest('.workspace-drop-zone') !== null
  if (!isInWorkspace) {
    e.preventDefault()
  }
})

// 挂载应用并初始化
app.mount('#app')
initializeApp()
