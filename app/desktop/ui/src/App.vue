<template>
  <div v-if="!isBackendReady" class="flex h-screen w-full items-center justify-center bg-background text-foreground flex-col gap-4">
    <div class="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent"></div>
    <div class="text-sm text-muted-foreground animate-pulse">正在连接服务...</div>
  </div>
  <div v-else class="app flex h-screen overflow-hidden bg-background text-foreground">
    <!-- Desktop Sidebar -->
    <Sidebar 
      v-if="!isSharedPage && !isOnboarding"
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
      v-if="!isSharedPage && !isOnboarding"
      class="lg:hidden" 
      @new-chat="handleNewChat" 
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
import { Toaster } from '@/components/ui/sonner'
// import { isLoggedIn } from './utils/auth.js'
import request from './utils/request.js'
import { systemAPI } from './api/system'
// import { Menu } from 'lucide-vue-next'
// import { Button } from '@/components/ui/button'

const router = useRouter()
const route = useRoute()

const isBackendReady = ref(false)

const checkSystemInitialization = async () => {
  try {
    const res = await systemAPI.getSystemInfo()
    if (!res.has_model_provider || !res.has_agent) {
       // If system is not initialized, we MUST go to Setup
       if (route.name !== 'Setup') {
         router.replace('/setup')
       }
    } else {
       // System IS initialized
       // If user is currently on Setup page, redirect to home
       if (route.name === 'Setup') {
          router.replace('/')
          return
       }
    }
  } catch (e) {
    console.error('Failed to check system info', e)
  }
}

const checkBackend = async () => {
  try {
    // 尝试直接使用 fetch 调用，绕过拦截器，避免控制台报错
    const apiPrefix = import.meta.env.VITE_BACKEND_API_PREFIX || ''
    const url = `${apiPrefix}/active`
    
    // 如果是开发环境且有前缀，Vite代理会处理
    // 生产环境可能需要完整URL，但在Tauri中通常是localhost
    
    const response = await fetch(url)
    if (response.ok) {
      isBackendReady.value = true
      checkSystemInitialization()
      return
    }
  } catch (e) {
    // 忽略错误
  }
  
  // 失败重试
  setTimeout(checkBackend, 1000)
}

const isSharedPage = computed(() => route.name === 'SharedChat' || route.path?.startsWith('/share/'))
const isOnboarding = computed(() => route.name === 'Onboarding' || route.name === 'Setup')

// Check login status on mount and route change
watch(() => [route.path, route.name], () => {
  // Navigation guards are handled in checkSystemInitialization and router
})

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

onMounted(() => {
  checkBackend()
})
</script>


