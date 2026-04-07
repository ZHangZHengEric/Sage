<template>
  <div v-if="!isBackendReady" class="flex h-screen w-full items-center justify-center bg-background text-foreground flex-col gap-4">
    <template v-if="isBackendFailed">
      <AlertCircle class="h-12 w-12 text-red-500" />
      <div class="text-lg font-medium text-red-600">后端启动失败</div>
      <div class="text-sm text-muted-foreground max-w-md text-center">{{ backendError || '无法连接到后端服务，请检查应用是否完整安装或尝试重启应用' }}</div>
      <Button variant="outline" size="sm" @click="retryBackendConnection">
        <RefreshCw class="h-4 w-4 mr-2" />
        重试连接
      </Button>
    </template>
    <template v-else>
      <div class="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent"></div>
      <div class="text-sm text-muted-foreground animate-pulse">正在启动Sage...</div>
      <div v-if="retryCount > 5" class="text-xs text-muted-foreground">
        启动时间较长，请耐心等待 ({{ retryCount }}/{{ MAX_RETRIES }})
      </div>
    </template>
  </div>
  <div v-else class="app app-shell flex h-screen overflow-hidden bg-background text-foreground">
    <!-- NPX Install Progress Dialog -->
    <Dialog :open="showNpxInstallDialog" @update:open="showNpxInstallDialog = $event">
      <DialogContent class="sm:max-w-[420px] p-6" :closeable="false">
        <DialogHeader class="pb-4">
          <DialogTitle class="flex items-center gap-2 text-base">
            <Package class="h-5 w-5 text-primary" />
            {{ npxInstallStatus === 'installing' ? '正在安装依赖包...' : npxInstallStatus === 'completed' ? '依赖包安装完成' : '安装依赖包' }}
          </DialogTitle>
          <DialogDescription class="text-sm text-muted-foreground pt-1">
            {{ npxInstallDescription }}
          </DialogDescription>
        </DialogHeader>
        
        <div class="space-y-4">
          <!-- Progress Bar -->
          <div v-if="npxInstallStatus === 'installing'" class="space-y-2">
            <div class="flex justify-between text-xs text-muted-foreground">
              <span>{{ npxCurrentPackage || '准备中...' }}</span>
              <span>{{ npxInstallProgress }}%</span>
            </div>
            <Progress :value="npxInstallProgress" class="h-2" />
          </div>
          
          <!-- Package List -->
          <div class="max-h-[200px] overflow-y-auto space-y-1.5">
            <div 
              v-for="(pkg, index) in npxPackages" 
              :key="pkg.name"
              class="flex items-center justify-between p-2 rounded-md text-sm"
              :class="pkg.status === 'installing' ? 'bg-primary/10 border border-primary/20' : pkg.status === 'success' ? 'bg-green-50 dark:bg-green-950/20' : pkg.status === 'failed' ? 'bg-red-50 dark:bg-red-950/20' : 'bg-muted/50'"
            >
              <div class="flex items-center gap-2">
                <div v-if="pkg.status === 'installing'" class="h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent"></div>
                <CheckCircle v-else-if="pkg.status === 'success'" class="h-4 w-4 text-green-500" />
                <XCircle v-else-if="pkg.status === 'failed'" class="h-4 w-4 text-red-500" />
                <MinusCircle v-else-if="pkg.status === 'skipped'" class="h-4 w-4 text-muted-foreground" />
                <Circle v-else class="h-4 w-4 text-muted-foreground" />
                <span :class="pkg.status === 'installing' ? 'font-medium' : ''">{{ pkg.name }}</span>
              </div>
              <span class="text-xs text-muted-foreground">
                {{ pkg.status === 'installing' ? '安装中...' : pkg.status === 'success' ? '已安装' : pkg.status === 'failed' ? '失败' : pkg.status === 'skipped' ? '已存在' : '等待中' }}
              </span>
            </div>
          </div>
          
          <!-- Error Message -->
          <div v-if="npxInstallError" class="p-3 rounded-md bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400 text-xs">
            {{ npxInstallError }}
          </div>
        </div>
        
        <DialogFooter class="gap-2 pt-4">
          <Button 
            v-if="npxInstallStatus === 'installing'" 
            variant="outline" 
            size="sm" 
            @click="skipNpxInstall"
            :disabled="isSkipping"
          >
            {{ isSkipping ? '跳过中...' : '跳过安装' }}
          </Button>
          <Button 
            v-if="npxInstallStatus === 'completed' || npxInstallStatus === 'skipped'" 
            size="sm" 
            @click="showNpxInstallDialog = false"
          >
            确定
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { AlertCircle, Package, CheckCircle, XCircle, MinusCircle, Circle, RefreshCw } from 'lucide-vue-next'
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
const backendError = ref('')
const isBackendFailed = ref(false)

// NPX Install Dialog State
const showNpxInstallDialog = ref(false)
const npxInstallStatus = ref('idle') // 'idle' | 'installing' | 'completed' | 'skipped'
const npxInstallProgress = ref(0)
const npxCurrentPackage = ref('')
const npxPackages = ref([])
const npxInstallError = ref('')
const npxInstallDescription = ref('正在准备安装依赖包...')
const isSkipping = ref(false)

const skipNpxInstall = async () => {
  try {
    isSkipping.value = true
    await invoke('skip_npx_installation')
    npxInstallStatus.value = 'skipped'
    npxInstallDescription.value = '已跳过依赖包安装，部分功能可能无法使用'
    showNpxInstallDialog.value = false
  } catch (e) {
    console.error('Failed to skip npx installation:', e)
    npxInstallError.value = '跳过安装失败: ' + e.message
  } finally {
    isSkipping.value = false
  }
}

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
          router.replace({
            name: 'Chat',
            query: {
              reload_new_chat: Date.now()
            }
          })
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

  // If failed too many times, show error
  if (retryCount.value >= MAX_RETRIES) {
    isBackendFailed.value = true
    backendError.value = '后端服务启动超时，请检查应用是否完整安装或尝试重启应用'
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
      isBackendFailed.value = false
      retryCount.value = 0 // Reset retry count
      checkSystemInitialization()
      return
    } else {
      console.warn('Backend returned error status:', response.status)
    }
  } catch (e) {
    console.warn('Backend connection error:', e.message)
  }
  
  retryCount.value++
  // 失败重试
  setTimeout(checkBackend, 2000)
}

const retryBackendConnection = () => {
  isBackendFailed.value = false
  backendError.value = ''
  retryCount.value = 0
  checkBackend()
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
  let unlistenResize = null
  let unlistenScaleFactor = null
  let unlistenNpxStarted = null
  let unlistenNpxProgress = null
  let unlistenNpxCompleted = null
  let unlistenNpxSkipped = null
  let unlistenBackendFailed = null

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
      
      // Listen for NPX install events
      unlistenNpxStarted = await listen('sage-npx-install-started', (event) => {
        showNpxInstallDialog.value = true
        npxInstallStatus.value = 'installing'
        npxInstallDescription.value = `正在安装 ${event.payload.total} 个依赖包，请稍候...`
        npxPackages.value = event.payload.packages.map(name => ({ name, status: 'pending' }))
      })
      
      unlistenNpxProgress = await listen('sage-npx-install-progress', (event) => {
        const { current, total, package: pkgName, status, error } = event.payload
        npxInstallProgress.value = Math.round((current / total) * 100)
        npxCurrentPackage.value = pkgName
        
        const pkg = npxPackages.value.find(p => p.name === pkgName)
        if (pkg) {
          pkg.status = status
        }
        
        if (status === 'installing') {
          npxInstallDescription.value = `正在安装 ${pkgName} (${current}/${total})...`
        } else if (status === 'failed' && error) {
          npxInstallError.value = `${pkgName} 安装失败: ${error}`
        }
      })
      
      unlistenNpxCompleted = await listen('sage-npx-install-completed', (event) => {
        npxInstallStatus.value = 'completed'
        const { installed, failed, total } = event.payload
        if (failed.length > 0) {
          npxInstallDescription.value = `安装完成: ${installed}/${total} 成功, ${failed.length} 失败`
          npxInstallError.value = `以下包安装失败: ${failed.join(', ')}`
        } else {
          npxInstallDescription.value = `所有依赖包安装完成 (${installed}/${total})`
        }
        npxInstallProgress.value = 100
      })
      
      unlistenNpxSkipped = await listen('sage-npx-install-skipped', () => {
        showNpxInstallDialog.value = false
      })
      
      // Listen for backend startup failure
      unlistenBackendFailed = await listen('sage-backend-startup-failed', (event) => {
        isBackendFailed.value = true
        backendError.value = event.payload.message || '后端服务启动失败'
        console.error('Backend startup failed:', event.payload)
      })
      
      // Check if already skipped
      try {
        const isSkipped = await invoke('is_npx_installation_skipped')
        if (!isSkipped) {
          // Will show dialog when install starts
        }
      } catch (e) {
        console.log('Failed to check npx skip status:', e)
      }
      
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

      // Listen for window resize events to force repaint
      unlistenResize = await listen('tauri-window-resized', () => {
        // Force a repaint by triggering a layout recalculation
        document.body.style.display = 'none'
        document.body.offsetHeight // Force reflow
        document.body.style.display = ''
      })

      // Listen for scale factor changes (DPI changes)
      unlistenScaleFactor = await listen('tauri-scale-factor-changed', () => {
        // Force a repaint
        document.body.style.display = 'none'
        document.body.offsetHeight // Force reflow
        document.body.style.display = ''
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
    if (unlistenResize) unlistenResize()
    if (unlistenScaleFactor) unlistenScaleFactor()
    if (unlistenNpxStarted) unlistenNpxStarted()
    if (unlistenNpxProgress) unlistenNpxProgress()
    if (unlistenNpxCompleted) unlistenNpxCompleted()
    if (unlistenNpxSkipped) unlistenNpxSkipped()
    if (unlistenBackendFailed) unlistenBackendFailed()
  })
</script>
