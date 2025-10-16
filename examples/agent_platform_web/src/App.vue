<template>
  <div class="app">
    <Sidebar 
      :current-page="currentPage"
      @page-change="handlePageChange"
      :conversation-count="conversations.length"
      @new-chat="handleNewChat"
    />
    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import Sidebar from './components/Sidebar.vue'
import { useChatStore } from './stores'

const router = useRouter()
const route = useRoute()
const chatStore = useChatStore()

// 从路由配置中创建页面ID到路由名称的映射
const pageToRouteNameMap = {
  'chat': 'Chat',
  'agents': 'AgentConfig', 
  'tools': 'Tools',
  'history': 'History'
}

// 计算属性
const currentPage = computed(() => {
  const routeName = route.name
  if (routeName === 'Chat') return 'chat'
  if (routeName === 'AgentConfig') return 'agents'
  if (routeName === 'Tools') return 'tools'
  if (routeName === 'History') return 'history'
  return 'chat'
})

const conversations = computed(() => chatStore.conversations)

// 方法
const handlePageChange = (page) => {
  // 从路由配置中获取对应的路由名称
  const routeName = pageToRouteNameMap[page]
  if (routeName) {
    // 通过路由名称跳转，这样会自动使用路由配置中的路径
    router.push({ name: routeName })
  } else {
    // 如果没有找到对应的路由名称，回退到默认页面
    router.push({ name: 'Chat' })
  }
}

const handleNewChat = () => {
  chatStore.clearSession()
  router.push('/agent/chat')
}
</script>

<style>
.app {
  display: flex;
  height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen',
    'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue',
    sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.main-content {
  flex: 1;
  overflow: hidden;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen',
    'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue',
    sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

code {
  font-family: source-code-pro, Menlo, Monaco, Consolas, 'Courier New',
    monospace;
}


</style>
