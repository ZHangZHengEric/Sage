import { createApp } from 'vue'
import './assets/index.css'
import 'vue-sonner/style.css'
import App from './App.vue'

// 导入路由和状态管理
import router from './router'
import { createPinia } from 'pinia'
import { useLanguageStore } from './utils/i18n.js'

const pinia = createPinia()

const app = createApp(App)

app.use(router)
app.use(pinia)

// 初始化应用状态
const initializeApp = async () => {
  const appStore = useLanguageStore()
  
  try {
    // 初始化应用设置
    appStore.initialize()
    console.log('Application initialized successfully')
  } catch (error) {
    console.error('Failed to initialize application:', error)
  }
}

// 挂载应用并初始化
app.mount('#app')
initializeApp()
