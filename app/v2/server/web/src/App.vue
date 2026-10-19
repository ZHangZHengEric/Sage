<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from './api.js'
import { clearSession, getUser, isAdmin } from './auth.js'
import AppIcon from './components/AppIcon.vue'

const route = useRoute()
const router = useRouter()
const publicPage = computed(() => route.path === '/login')
const user = computed(() => { route.path; return getUser() })
const admin = computed(() => { route.path; return isAdmin() })
const collapsed = ref(localStorage.getItem('sage.server_v2.sidebar.collapsed') === 'true')
const mobileMenu = ref(false)
const accountMenu = ref(null)
const groups = [
  { label: '工作空间', icon: 'grid', links: [
    { to: '/models', label: '模型供应商', icon: 'model' },
    { to: '/tools', label: '工具', icon: 'tools', paths: ['/tools', '/mcp', '/a2a'] },
    { to: '/skills', label: '技能', icon: 'skill' },
  ] },
  { label: '系统设置', icon: 'settings', admin: true, links: [
    { to: '/plugins', label: '插件管理', icon: 'settings' },
    { to: '/users', label: '用户管理', icon: 'user' },
  ] },
  { label: '开发者', icon: 'code', links: [
    { to: '/studio', label: 'Studio', icon: 'code' },
    { to: '/keys', label: 'API 密钥', icon: 'key' },
  ] },
]
const visibleGroups = computed(() => groups.filter(group => !group.admin || admin.value))
function toggleSidebar() {
  if (accountMenu.value) accountMenu.value.open = false
  collapsed.value = !collapsed.value
  localStorage.setItem('sage.server_v2.sidebar.collapsed', String(collapsed.value))
}
function newChat() {
  mobileMenu.value = false
  router.push({ path: '/', query: { new: String(Date.now()) } })
}
function closeAccountMenu() {
  if (accountMenu.value) accountMenu.value.open = false
  mobileMenu.value = false
}
function dismissAccountMenu(event) {
  if (accountMenu.value && !accountMenu.value.contains(event.target)) accountMenu.value.open = false
}
onMounted(() => document.addEventListener('pointerdown', dismissAccountMenu))
onUnmounted(() => document.removeEventListener('pointerdown', dismissAccountMenu))
async function logout() {
  try { await api.logout() } catch { /* Clear the local session even when offline. */ }
  clearSession()
  router.push('/login')
}
</script>

<template>
  <router-view v-if="publicPage" />
  <div v-else class="shell" :class="{ 'sidebar-collapsed': collapsed, 'mobile-menu-open': mobileMenu }">
    <aside id="app-sidebar" class="app-sidebar" aria-label="主导航">
      <header class="sidebar-header">
        <div class="sidebar-brand"><img src="/sage_logo.svg" alt="" /><span>Sage</span></div>
        <button class="icon-button sidebar-toggle" type="button" :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'" :aria-expanded="!collapsed" aria-controls="app-sidebar" :title="collapsed ? '展开侧边栏' : '收起侧边栏'" @click="toggleSidebar"><AppIcon name="panel" /></button>
      </header>
      <nav class="sidebar-nav" @click="event => { if (event.target.closest('a')) mobileMenu = false }">
        <button class="nav-item" type="button" title="新建对话" @click="newChat"><AppIcon name="plus" /><span>新建对话</span></button>
        <router-link class="nav-item" to="/history" title="历史会话"><AppIcon name="history" /><span>历史会话</span></router-link>
        <router-link class="nav-item" to="/agents" title="智能体"><AppIcon name="agent" /><span>智能体</span></router-link>
        <details v-for="group in visibleGroups" :key="group.label" class="nav-group" open>
          <summary class="nav-item" :title="group.label"><AppIcon :name="group.icon" /><span>{{ group.label }}</span><AppIcon class="nav-chevron" name="chevron" /></summary>
          <div class="nav-children">
            <router-link v-for="link in group.links" :key="link.to" :to="link.to" class="nav-item" :class="{ 'router-link-active': link.paths?.includes(route.path) }" :title="link.label"><AppIcon :name="link.icon" /><span>{{ link.label }}</span></router-link>
          </div>
        </details>
      </nav>
      <footer class="sidebar-footer">
        <details ref="accountMenu" class="account-menu" @keydown.esc.stop.prevent="closeAccountMenu">
          <summary class="nav-item" :title="user?.username"><span class="account-avatar">{{ user?.username?.[0]?.toUpperCase() || 'U' }}</span><span class="account-name">{{ user?.username }}</span><AppIcon class="nav-chevron" name="chevron" /></summary>
          <div class="account-actions"><router-link class="nav-item" to="/settings" @click="closeAccountMenu"><AppIcon name="settings" />个人设置</router-link><button class="nav-item" type="button" @click="logout"><AppIcon name="logout" />退出登录</button></div>
        </details>
      </footer>
    </aside>
    <main class="stage" :class="{ 'stage-chat': route.path === '/' }"><router-view /></main>
    <nav class="mobile-tabbar" aria-label="移动导航">
      <button type="button" @click="newChat"><AppIcon name="chat" /><span>新对话</span></button>
      <router-link to="/history" @click="mobileMenu = false"><AppIcon name="history" /><span>会话</span></router-link>
      <router-link to="/agents" @click="mobileMenu = false"><AppIcon name="agent" /><span>智能体</span></router-link>
      <button type="button" :aria-expanded="mobileMenu" aria-controls="app-sidebar" @click="mobileMenu = !mobileMenu"><AppIcon name="user" /><span>{{ mobileMenu ? '关闭' : '我的' }}</span></button>
    </nav>
  </div>
</template>
