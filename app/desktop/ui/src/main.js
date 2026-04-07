import { createApp } from 'vue'
import './assets/index.css'
import 'vue-sonner/style.css'
import App from './App.vue'

// 导入路由和状态管理
import router from './router'
import { createPinia } from 'pinia'
import { useLanguageStore } from './utils/i18n.js'
import { useThemeStore } from './stores/theme.js'
import { startMemoryDebugReporter } from './utils/memoryDebug.js'
import { getCurrentWebviewWindow } from '@tauri-apps/api/webviewWindow'

// 导入Tauri API
import { listen } from '@tauri-apps/api/event'

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

    if (window.__TAURI__) {
      document.documentElement.style.background = 'transparent'
      document.body.style.background = 'transparent'
      const currentWindow = getCurrentWebviewWindow()
      await currentWindow.setBackgroundColor([0, 0, 0, 0])
    }

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
  const isInDropZone = target.closest('.workspace-drop-zone') !== null || target.closest('.message-input-drop-zone') !== null
  if (!isInDropZone) {
    e.preventDefault()
  }
})

// 监听Tauri拖拽事件（桌面端）
if (window.__TAURI__) {
  listen('tauri-drag-enter', (event) => {
    console.log('Tauri drag enter:', event.payload)
    // 可以在这里设置全局拖拽状态
  })
  
  listen('tauri-drag-drop', (event) => {
    console.log('Tauri drag drop:', event.payload)
    // 将文件路径存储在全局，供组件使用
    window.__TAURI_DRAG_FILES__ = event.payload
    // 触发一个自定义事件，通知组件有文件被拖拽
    window.dispatchEvent(new CustomEvent('tauri-files-dropped', { detail: event.payload }))
  })
  
  listen('tauri-drag-leave', () => {
    console.log('Tauri drag leave')
  })
}

// 挂载应用并初始化
app.mount('#app')
initializeApp()
startMemoryDebugReporter()
