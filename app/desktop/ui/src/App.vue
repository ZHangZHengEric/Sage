<template>
  <div v-if="!isBackendReady" class="flex h-screen w-full items-center justify-center bg-background text-foreground flex-col gap-4">
    <div class="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent"></div>
    <div class="text-sm text-muted-foreground animate-pulse">正在启动Sage...</div>
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
import request, { setBaseURL } from './utils/request.js'
import { systemAPI } from './api/system'
import { listen } from '@tauri-apps/api/event'
import { invoke } from '@tauri-apps/api/tauri'

const router = useRouter()
const route = useRoute()

const isBackendReady = ref(false)
const currentApiPrefix = ref(import.meta.env.VITE_BACKEND_API_PREFIX || '')
const retryCount = ref(0)
const MAX_RETRIES = 30 // 1 minute timeout (2s * 30)

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
  if (isBackendReady.value) return

  // If in Tauri environment but API prefix is still default (relative path starting with /), 
  // do NOT poll the default backend port. Wait for port update event instead.
  if (window.__TAURI__ && currentApiPrefix.value.startsWith('/')) {
    console.log('In Tauri environment, waiting for backend port update...')
    return
  }

  // If failed too many times, stop checking
  if (retryCount.value > MAX_RETRIES) {
    console.warn('Backend check failed too many times, please restart app or check backend status.')
    return
  }

  try {
    // 尝试直接使用 fetch 调用，绕过拦截器，避免控制台报错
    const url = `${currentApiPrefix.value}/active`
    
    // 如果是开发环境且有前缀，Vite代理会处理
    // 生产环境可能需要完整URL，但在Tauri中通常是localhost
    
    const response = await fetch(url)
    if (response.ok) {
      isBackendReady.value = true
      retryCount.value = 0 // Reset retry count
      checkSystemInitialization()
      return
    }
  } catch (e) {
    // 忽略错误
  }
  
  retryCount.value++
  // 失败重试
  setTimeout(checkBackend, 2000)
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

  let unlisten = null

  onMounted(async () => {
    // Listen for Tauri backend ready event
    try {
      const updatePort = (port) => {
          console.log('Backend ready on port', port)
          const newUrl = `http://127.0.0.1:${port}`
          currentApiPrefix.value = newUrl
          setBaseURL(newUrl)
          // Check backend immediately
          retryCount.value = 0
          checkBackend()
      }

      // Wait for the backend port event
      unlisten = await listen('sage-desktop-ready', (event) => {
         updatePort(event.payload.port)
      })

      // Also try to get port actively, in case we missed the event
      try {
          const port = await invoke('get_server_port')
          if (port) {
              console.log('Got port from command:', port)
              updatePort(port)
          }
      } catch (err) {
          console.log('Failed to get port from command (maybe sidecar not ready yet):', err)
      }
    } catch (e) {
    console.warn('Tauri event listener failed (likely running in browser)', e)
    // Only check backend if we are NOT in Tauri environment (browser mode)
    // if (!window.__TAURI__) {
    //     checkBackend()
    // }
  }
  })

  onUnmounted(() => {
    if (unlisten) unlisten()
  })
</script>


