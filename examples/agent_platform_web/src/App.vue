<template>
  <div class="app">
    <Sidebar @new-chat="handleNewChat" />
    <el-main class="main-content">
      <router-view @select-conversation="handleSelectConversation" :selected-conversation="selectedConversation" />
    </el-main>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import Sidebar from './views/Sidebar.vue'

const router = useRouter()

// 选中的conversation数据
const selectedConversation = ref(null)

const handleNewChat = () => {
  selectedConversation.value = null
}

const handleSelectConversation = (conversation) => {
  selectedConversation.value = conversation
  router.push({ name: 'Chat' })
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
</style>
