<template>
  <div class="app">
    <Sidebar @new-chat="handleNewChat" />
    <main class="main-content">
      <router-view @select-conversation="handleSelectConversation" :selected-conversation="selectedConversation" />
    </main>

    <!-- 登录模态框 - 临时隐藏 -->
    <LoginModal
        :visible="showLoginModal"
        @close="showLoginModal = false"
        @login-success="handleLoginSuccess"
    />
  </div>

</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import Sidebar from './views/Sidebar.vue'
import LoginModal from './components/LoginModal.vue'
import { isLoggedIn } from './utils/auth.js'

const router = useRouter()

// 登录模态框显示状态
const showLoginModal = ref(!isLoggedIn())

// 选中的conversation数据
const selectedConversation = ref(null)

const handleNewChat = () => {
  selectedConversation.value = null
}

const handleSelectConversation = (conversation) => {
  selectedConversation.value = conversation
  router.push({ name: 'Chat' })
}


// 登录成功处理（从LoginModal接收）
const handleLoginSuccess = (userData) => {
  showLoginModal.value = false
}

const handleUserUpdated = () => {
  showLoginModal.value = !isLoggedIn()
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
</script>

<style>
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}
.app {
    display: flex;
    height: 100vh;
}

.main-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    background-color: #ffffff;
    overflow-y: auto;
}

</style>
