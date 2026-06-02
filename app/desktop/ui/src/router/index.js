import { createRouter, createWebHashHistory } from 'vue-router'
import ChatPage from '../views/Chat.vue'
import AgentConfigPage from '../views/AgentList.vue'
import ToolsPage from '../views/ToolList.vue'
import HistoryPage from '../views/ChatHistory.vue'
import SkillLibraryPage from '../views/SkillList.vue'
import SystemSettingsPage from '../views/SystemSettings.vue'
import ToolDetailPage from '../views/ToolDetail.vue'
import SharedChatPage from '../views/SharedChat.vue'
import TaskListPage from '../views/TaskList.vue'
import ModelProviderListPage from '../views/ModelProviderList.vue'
import MobileMePage from '../views/MobileMe.vue'
import SetupPage from '../views/Setup.vue'


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
    component: ToolDetailPage,
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
    path: '/agent/skills',
    name: 'Skills',
    component: SkillLibraryPage,
    meta: {
      title: 'skills.title'
    }
  },
  {
    path: '/share/:sessionId',
    name: 'SharedChat',
    component: SharedChatPage,
    meta: {
      title: 'chat.sharedChat',
      public: true
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
    path: '/personal/tasks',
    name: 'TaskList',
    component: TaskListPage,
    meta: {
      title: 'scheduledTask.title'
    }
  },
  {
    path: '/personal/model-providers',
    name: 'ModelProviderList',
    component: ModelProviderListPage,
    meta: {
      title: 'modelProvider.title'
    }
  },
  {
    path: '/me',
    name: 'MobileMe',
    component: MobileMePage,
    meta: {
      title: 'sidebar.userProfile'
    }
  },
  {
    path: '/setup',
    name: 'Setup',
    component: SetupPage,
    meta: {
      title: 'common.setup',
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
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes
})

// 路由守卫 - 设置页面标题
router.beforeEach((to, from, next) => {
  // 这里可以添加认证逻辑
  next()
})

export default router
