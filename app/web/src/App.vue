<template>
  <div class="app flex h-screen overflow-hidden bg-background text-foreground">
    <!-- Desktop Sidebar -->
    <Sidebar 
      v-if="!isSharedPage"
      class="hidden lg:flex shrink-0" 
      @new-chat="handleNewChat" 
    />
    
    <main class="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-background pb-[64px] lg:pb-0">
      <div class="flex-1 overflow-hidden relative flex flex-col">
        <router-view v-slot="{ Component }">
          <component 
            :is="Component" 
            @select-conversation="handleSelectConversation" 
            :selected-conversation="selectedConversation" 
            :chat-reset-token="chatResetToken"
          />
        </router-view>
      </div>
    </main>

    <!-- Mobile Tab Bar -->
    <MobileTabBar 
      v-if="!isSharedPage"
      class="lg:hidden" 
      @new-chat="handleNewChat" 
    />

    <LoginModal
        :visible="showLoginModal"
        @close="showLoginModal = false"
        @login-success="handleLoginSuccess"
    />
    <Teleport to="body">
      <Toaster position="top-center" richColors />
    </Teleport>
  </div>

</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import Sidebar from './views/Sidebar.vue'
import MobileTabBar from './components/mobile/MobileTabBar.vue'
import LoginModal from './components/LoginModal.vue'
import { Toaster } from '@/components/ui/sonner'
import { isLoggedIn } from './utils/auth.js'
// import { Menu } from 'lucide-vue-next'
// import { Button } from '@/components/ui/button'

const router = useRouter()
const route = useRoute()

const isSharedPage = computed(() => route.name === 'SharedChat' || route.path?.startsWith('/share/'))

// 登录模态框显示状态
const showLoginModal = ref(false)

// Check login status on mount and route change
watch(() => [route.path, route.name], () => {
  if (isSharedPage.value) {
    showLoginModal.value = false
  } else {
    showLoginModal.value = !isLoggedIn()
  }
}, { immediate: true })

// 选中的conversation数据
const selectedConversation = ref(null)

const handleNewChat = () => {
  selectedConversation.value = null
  // 触发重置 token，强制 Chat 组件清理状态
  chatResetToken.value = Date.now()
}

const chatResetToken = ref(0)


const handleSelectConversation = (conversation) => {
  selectedConversation.value = conversation
  router.push({ name: 'Chat' })
}


// 登录成功处理（从LoginModal接收）
const handleLoginSuccess = (userData) => {
  showLoginModal.value = false
}

const handleUserUpdated = () => {
  if (isSharedPage.value) {
    showLoginModal.value = false
  } else {
    showLoginModal.value = !isLoggedIn()
  }
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


