<template>
  <div class="sidebar">
    <div class="sidebar-header">
      <h2>{{ t('app.title') }}</h2>
      <div v-if="currentUser" class="user-info">
        <div class="user-details">
          <div class="user-name">用户名：{{ currentUser.nickname || currentUser.username }}</div>
        </div>
        <button @click="handleLogout" class="logout-btn">{{ t('auth.logout') }}</button>
      </div>
    </div>

    <nav class="sidebar-nav">
      <ul class="menu-list">
        <li v-for="category in predefinedServices" :key="category.id" class="menu-category">
          <div class="category-header" @click="toggleCategory(category.key)">
            <span class="category-icon">{{ category.icon }}</span>
            <span class="category-name">{{ t(category.nameKey) }}</span>
            <span class="category-toggle" :class="{ expanded: expandedCategories[category.key] }">▼</span>
          </div>
          <ul v-show="expandedCategories[category.key]" class="submenu-list">
            <li v-for="service in category.children" :key="service.id" class="submenu-item" :class="{ active: isCurrentService(service.url, service.isInternal) }">
              <a href="#" class="submenu-link" @click.prevent="handleMenuClick(service.url, t(service.nameKey), service.isInternal)">
                {{ t(service.nameKey) }}
              </a>
            </li>
          </ul>
        </li>
      </ul>
    </nav>

    <div class="sidebar-footer">
      <button class="language-toggle" @click="toggleLanguage">
        <el-icon :size="16">
          <Globe />
        </el-icon>
        <span>{{ isZhCN ? t('sidebar.langToggleZh') : t('sidebar.langToggleEn') }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Connection as Globe } from '@element-plus/icons-vue'
import { useLanguage } from '../utils/i18n.js'
import { getCurrentUser, logout } from '../utils/auth.js'

const router = useRouter()
const route = useRoute()
const { language, toggleLanguage, t, isZhCN } = useLanguage()
const emit = defineEmits(['new-chat'])

const currentUser = ref(getCurrentUser())

const handleUserUpdated = () => {
  currentUser.value = getCurrentUser()
}

onMounted(() => {
  if (typeof window !== 'undefined') {
    window.addEventListener('user-updated', handleUserUpdated)
  }
})

onUnmounted(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('user-updated', handleUserUpdated)
  }
})

const predefinedServices = ref([
  {
    id: 'cat1',
    key: 'chat_and_config',
    nameKey: 'sidebar.chatAndConfig',
    icon: '💬',
    children: [
      { id: 'svc_chat', nameKey: 'sidebar.newChat', url: 'Chat', isInternal: true },
      { id: 'svc_agent', nameKey: 'sidebar.agentConfig', url: 'AgentConfig', isInternal: true }
    ]
  },
  {
    id: 'cat2',
    key: 'tools_and_services',
    nameKey: 'sidebar.toolsAndServices',
    icon: '🧰',
    children: [
      { id: 'svc_tools', nameKey: 'sidebar.toolsList', url: 'Tools', isInternal: true },
      { id: 'svc_mcps', nameKey: 'sidebar.mcpsManage', url: 'Mcps', isInternal: true }
    ]
  },
  {
    id: 'cat3',
    key: 'knowledge_base',
    nameKey: 'sidebar.knowledgeBase',
    icon: '📚',
    children: [
      { id: 'svc_kdb', nameKey: 'sidebar.knowledgeBaseManage', url: 'KnowledgeBase', isInternal: true }
    ]
  },
  {
    id: 'cat4',
    key: 'history',
    nameKey: 'sidebar.sessions',
    icon: '🕘',
    children: [
      { id: 'svc_history', nameKey: 'sidebar.history', url: 'History', isInternal: true }
    ]
  }
  ,
  {
    id: 'cat5',
    key: 'api_reference',
    nameKey: 'sidebar.apiReference',
    icon: '📘',
    children: [
      { id: 'svc_api_agent_chat', nameKey: 'sidebar.apiAgentChat', url: 'ApiAgentChat', isInternal: true }
    ]
  }
])

const expandedCategories = ref({
  chat_and_config: true,
  tools_and_services: false,
  knowledge_base: false,
  history: false,
  api_reference: false
})

const toggleCategory = (key) => {
  expandedCategories.value[key] = !expandedCategories.value[key]
}

const isCurrentService = (url, isInternal) => {
  if (isInternal) return route.name === url || (route.name === 'KnowledgeBaseDetail' && url === 'KnowledgeBase')
  return false
}

const handleMenuClick = (url, name, isInternal) => {
  if (isInternal) {
    if (url === 'Chat') emit('new-chat')
    router.push({ name: url })
  } else {
    window.open(url, '_blank')
  }
}

const handleLogout = () => {
  logout()
  currentUser.value = null
  router.push({ name: 'Chat' })
}
</script>

<style scoped>

/* 左侧菜单样式 */
.sidebar {
    width: 280px;
    background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%); 
    color: #334155;
    display: flex;
    flex-direction: column;
    box-shadow: 2px 0 8px rgba(0,0,0,0.06);
    z-index: 1000;
    border-right: 1px solid #e2e8f0;
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

.sidebar-header h2 {
  margin: 0;
  text-align: center;
  font-size: 20px;
  font-weight: 700;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
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
  display: flex;
  flex-direction: column;
  gap: 8px;
  position: relative;
  z-index: 1;
}

.menu-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.menu-category {
  margin: 0;
}

.category-header {
  display: flex;
  align-items: center;
  padding: 0.8rem 1.2rem;
  color: #334155;
  cursor: pointer;
  transition: all 0.2s ease;
  border-left: 3px solid transparent;
  background-color: transparent;
  font-weight: 500;
  border-radius: 0;
  margin: 0.1rem 0;
  font-size: 0.9rem;
}

.category-header:hover {
  background-color: rgba(102, 126, 234, 0.12);
  color: #1f2937;
}

.category-icon {
  font-size: 1rem;
  margin-right: 0.6rem;
  color: #475569;
  width: 20px;
  text-align: center;
}

.category-name {
  flex: 1;
  font-size: 0.9rem;
}

.category-toggle {
  font-size: 0.7rem;
  transition: transform 0.2s ease;
  color: #cbd5e1;
  width: 12px;
  text-align: center;
}

.category-toggle.expanded {
  transform: rotate(180deg);
}

.submenu-list {
  list-style: none;
  padding: 0;
  margin: 0;
  background-color: transparent;
  border-radius: 0;
  border: none;
}

.submenu-item {
  margin: 2px 0;
  cursor: pointer;
}

.submenu-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.6rem 1.2rem 0.6rem 2.8rem;
  color: #475569;
  text-decoration: none;
  transition: all 0.2s ease;
  border-left: 3px solid transparent;
  font-size: 0.85rem;
  border-radius: 0;
}

.submenu-item:hover .submenu-link {
  background-color: rgba(102, 126, 234, 0.08);
  color: #1f2937;
}

.submenu-item.active .submenu-link {
  background-color: rgba(102, 126, 234, 0.18);
  color: #1f2937;
  font-weight: 600;
}

.submenu-item.disabled {
  cursor: not-allowed;
}

.submenu-item.disabled .submenu-link {
  cursor: not-allowed;
  opacity: 0.9;
  color: white;
  background-color: rgba(102, 126, 234, 0.6);
  font-weight: 500;
}

.submenu-item.disabled:hover .submenu-link {
  background-color: rgba(102, 126, 234, 0.6);
  color: white;
}

.submenu-link.disabled {
  cursor: not-allowed;
  pointer-events: auto;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}

.user-details {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
}

.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #667eea;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}

.user-name {
  color: #1f2937;
  font-size: 14px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.logout-btn {
  margin-left: auto;
  background: transparent;
  color: #334155;
  border: transparent;
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
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
  background: rgba(51, 65, 85, 0.06);
  border-radius: 8px;
  border: 1px solid rgba(203, 213, 225, 0.8);
  color: #334155;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.language-toggle:hover {
  background: rgba(102, 126, 234, 0.08);
  color: #1f2937;
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
