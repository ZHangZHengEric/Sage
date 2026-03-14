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
          <keep-alive :include="['Chat']">
            <component 
              :is="Component" 
              @select-conversation="handleSelectConversation" 
              :selected-conversation="selectedConversation" 
              :chat-reset-token="chatResetToken"
            />
          </keep-alive>
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

  <!-- Close Dialog -->
  <Dialog :open="showCloseDialog" @update:open="showCloseDialog = $event">
    <DialogContent class="sm:max-w-[360px] p-5">
      <DialogHeader class="pb-2">
        <DialogTitle class="flex items-center gap-2 text-base">
          <AlertCircle class="h-4 w-4 text-yellow-500" />
          您点击了关闭按钮，您想要：
        </DialogTitle>
      </DialogHeader>
      <div class="space-y-3">
        <div class="space-y-2">
          <div 
            class="flex items-center space-x-2 p-2.5 rounded-md cursor-pointer transition-colors"
            :class="closeAction === 'hide' ? 'border-primary bg-primary/5' : 'border-border hover:bg-accent'"
            @click="closeAction = 'hide'"
          >
            <div class="w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0" :class="closeAction === 'hide' ? 'border-primary' : 'border-muted-foreground'">
              <div v-if="closeAction === 'hide'" class="w-2 h-2 rounded-full bg-primary" />
            </div>
            <Label class="cursor-pointer text-sm">最小化到托盘</Label>
          </div>
          <div 
            class="flex items-center space-x-2 p-2.5 rounded-md cursor-pointer transition-colors"
            :class="closeAction === 'exit' ? 'border-primary bg-primary/5' : 'border-border hover:bg-accent'"
            @click="closeAction = 'exit'"
          >
            <div class="w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0" :class="closeAction === 'exit' ? 'border-primary' : 'border-muted-foreground'">
              <div v-if="closeAction === 'exit'" class="w-2 h-2 rounded-full bg-primary" />
            </div>
            <Label class="cursor-pointer text-sm">退出</Label>
          </div>
        </div>
        <div class="flex items-center space-x-2">
          <Checkbox id="remember" v-model:checked="rememberChoice" class="h-4 w-4 hover:border-transparent focus-visible:ring-0 focus-visible:ring-offset-0" />
          <Label for="remember" class="cursor-pointer text-xs text-muted-foreground">不再提示</Label>
        </div>
      </div>
      <DialogFooter class="gap-2 pt-3">
        <Button variant="outline" size="sm" @click="showCloseDialog = false">取消</Button>
        <Button size="sm" @click="handleCloseConfirm">确定</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>

</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import Sidebar from './views/Sidebar.vue'
import MobileTabBar from './components/mobile/MobileTabBar.vue'
import { Toaster } from '@/components/ui/sonner'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { AlertCircle } from 'lucide-vue-next'
// import { isLoggedIn } from './utils/auth.js'
import request, { setBaseURL } from './utils/request.js'
import { systemAPI } from './api/system'
import { listen } from '@tauri-apps/api/event'
import { invoke } from '@tauri-apps/api/core'
import { confirm } from '@tauri-apps/plugin-dialog'
import { open } from '@tauri-apps/plugin-shell'
import { useLanguage } from './utils/i18n'

const { t } = useLanguage()
const router = useRouter()
const route = useRoute()
const isMacOS = /mac/i.test(navigator.platform || '')

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
  // 仅当当前已在「新会话」页（无 session_id）时触发完整重置；从历史会话或从设置/历史等页点「新对话」回来时不重置
  if (route.name === 'Chat' && !route.query.session_id) {
    chatResetToken.value = Date.now()
  }
  if (route.query.session_id) {
    router.replace({
      query: { ...route.query, session_id: undefined }
    })
  }
}

const chatResetToken = ref(0)

// Close dialog state
const showCloseDialog = ref(false)
const closeAction = ref('hide')
const rememberChoice = ref(false)

const handleCloseConfirm = async () => {
  showCloseDialog.value = false
  await invoke('handle_close_dialog_result', {
    result: {
      action: closeAction.value,
      remember: rememberChoice.value
    }
  })
}

const handleSelectConversation = (conversation) => {
  selectedConversation.value = conversation
  router.push({ name: 'Chat' })
}

  let unlisten = null
  let unlistenPermission = null
  let unlistenCloseDialog = null

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
      
      let permissionDialogShown = false
       
       unlistenPermission = await listen('imessage-permission-denied', async () => {
           if (permissionDialogShown) return
           permissionDialogShown = true
           
           const confirmed = await confirm(
               t('permission.fullDiskAccess.message'),
               {
                   title: t('permission.fullDiskAccess.title'),
                   kind: 'warning',
                   okLabel: t('permission.openSettings'),
                   cancelLabel: t('permission.cancel')
               }
           );
           
           if (confirmed) {
               if (isMacOS) {
                 await open('x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles')
               }
           }
       })

      // Listen for show close dialog event
      unlistenCloseDialog = await listen('show-close-dialog', () => {
        showCloseDialog.value = true
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
    if (unlistenPermission) unlistenPermission()
    if (unlistenCloseDialog) unlistenCloseDialog()
  })
</script>
