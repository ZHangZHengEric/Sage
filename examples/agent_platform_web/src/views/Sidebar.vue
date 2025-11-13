<template>
  <div class="sidebar">
    <div class="sidebar-header">
      <div class="logo">
        <div class="logo-icon">
          <el-icon :size="24">
            <Plus />
          </el-icon>
        </div>
        <h1 class="logo-text">Agent Platform</h1>
      </div>
    </div>

    <nav class="sidebar-nav">
      <button v-for="item in menuItems" :key="item.id" :class="['nav-item', { active: currentPage === item.id }]"
        @click="handleItemClick(item)">
        <el-icon :size="20" class="nav-icon">
          <component :is="item.icon" />
        </el-icon>
        <span class="nav-label">{{ item.label }}</span>
        <span v-if="item.badge" class="nav-badge">{{ item.badge }}</span>
      </button>
    </nav>

    <div class="sidebar-footer">
      <button class="language-toggle" @click="toggleLanguage">
        <el-icon :size="16">
          <Globe />
        </el-icon>
        <span>{{ language === 'zh-CN' ? '中 / En' : 'En / 中' }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  ChatDotRound as MessageSquare,
  Setting as Settings,
  Tools as Wrench,
  Clock as History,
  Plus,
  Connection as Globe
} from '@element-plus/icons-vue'
import { useLanguage } from '../utils/i18n.js'

const router = useRouter()
const route = useRoute()

// 从路由配置中创建页面ID到路由名称的映射
const pageToRouteNameMap = {
  'chat': 'Chat',
  'agents': 'AgentConfig',
  'tools': 'Tools',
  'knowledge': 'KnowledgeBase',
  'history': 'History',
  'mcps': 'Mcps'
}

// 计算当前页面
const currentPage = computed(() => {
  const routeName = route.name
  if (routeName === 'Chat') return 'chat'
  if (routeName === 'AgentConfig') return 'agents'
  if (routeName === 'Tools') return 'tools'
  if (routeName === 'KnowledgeBase' || routeName === 'KnowledgeBaseDetail') return 'knowledge'
  if (routeName === 'History') return 'history'
  if (routeName === 'Mcps') return 'mcps'
  return 'chat'
})

// Props (移除 currentPage prop，因为现在内部计算)
const props = defineProps({})

// Emits
const emit = defineEmits(['new-chat'])

// 语言相关
const { t, language, toggleLanguage } = useLanguage()

// 菜单项
const menuItems = computed(() => [
  {
    id: 'chat',
    label: t('sidebar.newChat'),
    icon: MessageSquare,
    badge: null
  },
  {
    id: 'agents',
    label: t('sidebar.agentConfig'),
    icon: Settings,
    badge: null
  },
  {
    id: 'tools',
    label: t('sidebar.tools'),
    icon: Wrench,
    badge: null
  },
  {
    id: 'knowledge',
    label: t('knowledgeBase.title'),
    icon: Wrench,
    badge: null
  },
  {
    id: 'mcps',
    label: t('sidebar.mcps'),
    icon: Wrench,
    badge: null
  },
  {
    id: 'history',
    label: t('sidebar.history'),
    icon: History,
    badge: null
  }
])

// 方法
const handleItemClick = (item) => {
  if (item.id === 'chat') {
    emit('new-chat')
  }

  // 直接处理路由跳转
  const routeName = pageToRouteNameMap[item.id]
  if (routeName) {
    // 通过路由名称跳转，这样会自动使用路由配置中的路径
    router.push({ name: routeName })
  } else {
    // 如果没有找到对应的路由名称，回退到默认页面
    router.push({ name: 'Chat' })
  }
}
</script>

<style scoped>
.sidebar {
  width: 280px;
  height: 100vh;
  background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
  border-right: 1px solid rgba(255, 255, 255, 0.1);
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
}

.sidebar::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
  pointer-events: none;
}

.sidebar-header {
  padding: 24px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  position: relative;
  z-index: 1;
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo-icon {
  width: 40px;
  height: 40px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
}

.logo-text {
  font-size: 20px;
  font-weight: 700;
  color: white;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.sidebar-nav {
  flex: 1;
  padding: 20px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  position: relative;
  z-index: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.7);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.3s ease;
  font-size: 14px;
  font-weight: 500;
  text-align: left;
  position: relative;
  overflow: hidden;
}

.nav-item::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.nav-item:hover::before {
  opacity: 1;
}

.nav-item:hover {
  color: white;
  background: rgba(255, 255, 255, 0.05);
  transform: translateX(4px);
}

.nav-item.active {
  color: white;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.2) 0%, rgba(118, 75, 162, 0.2) 100%);
  border: 1px solid rgba(102, 126, 234, 0.3);
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.2);
}

.nav-item.active::before {
  opacity: 1;
}

.nav-icon {
  flex-shrink: 0;
  position: relative;
  z-index: 1;
}

.nav-label {
  flex: 1;
  position: relative;
  z-index: 1;
}

.nav-badge {
  background: linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%);
  color: white;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
  min-width: 20px;
  text-align: center;
  position: relative;
  z-index: 1;
  box-shadow: 0 2px 8px rgba(255, 107, 107, 0.3);
}

.sidebar-footer {
  padding: 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.status-dot {
  width: 8px;
  height: 8px;
  background: #4ade80;
  border-radius: 50%;
  animation: pulse 2s infinite;
  box-shadow: 0 0 10px rgba(74, 222, 128, 0.5);
}

.status-text {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
  font-weight: 500;
}

.language-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.7);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.language-toggle:hover {
  background: rgba(255, 255, 255, 0.1);
  color: white;
}

.language-toggle span {
  flex: 1;
}

@keyframes pulse {

  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }

  50% {
    opacity: 0.7;
    transform: scale(1.1);
  }
}
</style>