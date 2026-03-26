<template>
  <div class="app flex h-screen overflow-hidden bg-background text-foreground">
    <!-- Desktop Sidebar -->
    <Sidebar 
      v-if="!hideShell"
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
      v-if="!hideShell"
      class="lg:hidden" 
      @new-chat="handleNewChat" 
    />
    <SetupModal
        :visible="showSetupModal"
        @close="showSetupModal = false"
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
import { getCurrentUser } from './utils/auth.js'
import SetupModal from './components/SetupModal.vue'
import { userAPI } from '@/api/user'

const router = useRouter()
const route = useRoute()

const isSharedPage = computed(() => route.name === 'SharedChat' || route.path?.startsWith('/share/'))
const isLoginPage = computed(() => route.name === 'Login')
const hideShell = computed(() => isSharedPage.value || isLoginPage.value)

const showSetupModal = ref(false)

const maybeShowSetupModal = async () => {
  if (hideShell.value) return
  try {
    const user = getCurrentUser()
    if (!user) return
    const configRes = await userAPI.getUserConfig()
    const config = configRes.config || {}

    if (user && user.has_provider === false && !config.is_setup_completed) {
      showSetupModal.value = true
    }
  } catch (e) {
    console.error('Failed to check user setup status:', e)
  }
}

watch(() => [route.path, route.name], () => {
  maybeShowSetupModal()
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

const handleUserUpdated = () => {
  maybeShowSetupModal()
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
