import { createRouter, createWebHistory } from 'vue-router'
import ChatPage from '../views/Chat.vue'
import AgentConfigPage from '../views/AgentList.vue'
import ToolsPage from '../views/ToolList.vue'
import HistoryPage from '../views/ChatHistory.vue'
import KnowledgeBasePage from '../views/KnowledgeBaseList.vue'
import SkillLibraryPage from '../views/SkillList.vue'
import ApiAgentChatPage from '../views/ApiAgentChat.vue'
import UserListPage from '../views/UserList.vue'
import SystemSettingsPage from '../views/SystemSettings.vue'

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
    path: '/agent/tools/:toolName',
    name: 'ToolDetailView',
    component: () => import('../views/ToolDetail.vue'),
    meta: {
      title: 'tools.detailTitle'
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
  {
    path: '/agent/knowledge-base',
    name: 'KnowledgeBase',
    component: KnowledgeBasePage,
    meta: {
      title: 'knowledgeBase.title'
    }
  },
  {
    path: '/agent/knowledge-base/:kdbId',
    name: 'KnowledgeBaseDetail',
    component: () => import('../views/KnowledgeBaseDetail.vue'),
    meta: {
      title: 'knowledgeBase.title'
    }
  },
  {
    path: '/agent/skills',
    name: 'Skills',
    component: SkillLibraryPage,
    meta: {
      title: 'skills.title'
    }
  },
  {
    path: '/agent/api-doc/agent-chat',
    name: 'ApiAgentChat',
    component: ApiAgentChatPage,
    meta: {
      title: 'api.agentChatTitle'
    }
  },
  {
    path: '/share/:sessionId',
    name: 'SharedChat',
    component: () => import('../views/SharedChat.vue'),
    meta: {
      title: 'chat.sharedChat',
      public: true
    }
  },
  {
    path: '/system/users',
    name: 'UserList',
    component: UserListPage,
    meta: {
      title: 'sidebar.userList'
    }
  },
  {
    path: '/system/settings',
    name: 'SystemSettings',
    component: SystemSettingsPage,
    meta: {
      title: 'sidebar.systemSettings'
    }
  },
  {
    path: '/personal/model-providers',
    name: 'ModelProviderList',
    component: () => import('../views/ModelProviderList.vue'),
    meta: {
      title: 'modelProvider.title'
    }
  },
  {
    path: '/me',
    name: 'MobileMe',
    component: () => import('../views/MobileMe.vue'),
    meta: {
      title: 'sidebar.userProfile'
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
