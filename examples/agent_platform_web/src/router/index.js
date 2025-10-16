import { createRouter, createWebHistory } from 'vue-router'
import ChatPage from '../views/Chat.vue'
import AgentConfigPage from '../views/AgentConfig.vue'
import ToolsPage from '../views/Tools.vue'
import HistoryPage from '../views/ChatHistory.vue'

const routes = [
  {
    path: '/agent/chat',
    name: 'Chat',
    component: ChatPage,
    meta: {
      title: 'chat.title'
    }
  },
  {
    path: '/agent/config',
    name: 'AgentConfig',
    component: AgentConfigPage,
    meta: {
      title: 'agent.title'
    }
  },
  {
    path: '/agent/tools',
    name: 'Tools',
    component: ToolsPage,
    meta: {
      title: 'tools.title'
    }
  },
  {
    path: '/agent/history',
    name: 'History',
    component: HistoryPage,
    meta: {
      title: 'history.title'
    }
  },
  // 重定向根路径到聊天页面
  {
    path: '/:pathMatch(.*)*',
    redirect: '/agent/chat'
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

// 路由守卫 - 设置页面标题
router.beforeEach((to, from, next) => {
  // 这里可以添加认证逻辑
  next()
})

export default router