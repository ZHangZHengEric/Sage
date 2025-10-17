import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import './style.css'
import App from './App.vue'

// 导入路由和状态管理
import router from './router'
import pinia, { useAppStore } from './stores'

const app = createApp(App)

// 注册Element Plus图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(ElementPlus)
app.use(router)
app.use(pinia)

// 初始化应用状态
const initializeApp = async () => {
  const appStore = useAppStore()
  
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
