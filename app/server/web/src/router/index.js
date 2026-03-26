import { createRouter, createWebHistory } from 'vue-router'
import { quickLoginCheck } from '../utils/auth.js'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
    meta: {
      title: 'auth.login',
      public: true
    }
  },
  {
    path: '/agent/chat',
    name: 'Chat',
    component: () => import('../views/Chat.vue'),
    meta: {
      title: 'chat.title'
    }
  },
  {
    path: '/agent/config',
    name: 'AgentConfig',
    component: () => import('../views/AgentList.vue'),
    meta: {
      title: 'agent.title'
    }
  },
  {
    path: '/agent/tools',
    name: 'Tools',
    component: () => import('../views/ToolList.vue'),
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
    component: () => import('../views/ChatHistory.vue'),
    meta: {
      title: 'history.title'
    }
  },
  {
    path: '/agent/knowledge-base',
    name: 'KnowledgeBase',
    component: () => import('../views/KnowledgeBaseList.vue'),
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
    component: () => import('../views/SkillList.vue'),
    meta: {
      title: 'skills.title'
    }
  },
  {
    path: '/agent/api-doc/agent-chat',
    name: 'ApiAgentChat',
    component: () => import('../views/ApiAgentChat.vue'),
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
    component: () => import('../views/UserList.vue'),
    meta: {
      title: 'sidebar.userList'
    }
  },
  {
    path: '/system/settings',
    name: 'SystemSettings',
    component: () => import('../views/SystemSettings.vue'),
    meta: {
      title: 'sidebar.systemSettings'
    }
  },
  {
    path: '/system/versions',
    name: 'VersionList',
    component: () => import('../views/VersionList.vue'),
    meta: {
      title: 'system.versionManagement'
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
  {
    path: '/download',
    name: 'Download',
    component: () => import('../views/Download.vue'),
    meta: {
      title: 'download.title',
      public: true
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

const shouldUseBrowserNavigation = (path) => (
  typeof path === 'string' && (path.startsWith('/jaeger/') || path.startsWith('/api/') || path.startsWith('/oauth2/'))
)

// 路由守卫 - 设置页面标题
router.beforeEach(async (to) => {
  if (to.meta?.public) {
    if (to.name === 'Login') {
      const loginResult = await quickLoginCheck(true)
      if (loginResult.isLoggedIn) {
        const nextPath = typeof to.query.next === 'string' && to.query.next.startsWith('/')
          ? to.query.next
          : '/agent/chat'
        if (shouldUseBrowserNavigation(nextPath)) {
          window.location.replace(nextPath)
          return false
        }
        return nextPath
      }
    }
    return true
  }

  const loginResult = await quickLoginCheck(true)
  if (!loginResult.isLoggedIn) {
    return {
      name: 'Login',
      query: {
        next: to.fullPath
      }
    }
  }
  return true
})

export default router
