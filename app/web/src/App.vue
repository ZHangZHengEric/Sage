<template>
  <div class="app flex h-screen overflow-hidden bg-background text-foreground">
    <!-- Desktop Sidebar -->
    <Sidebar 
      class="hidden lg:flex shrink-0" 
      @new-chat="handleNewChat" 
    />
    
    <!-- Mobile Sidebar Overlay -->
    <Transition 
      enter-active-class="transition-opacity duration-300"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-300"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="isMobileMenuOpen" class="fixed inset-0 z-50 bg-black/50 lg:hidden" @click="isMobileMenuOpen = false" />
    </Transition>

    <!-- Mobile Sidebar -->
    <Transition
      enter-active-class="transition-transform duration-300 ease-out"
      enter-from-class="-translate-x-full"
      enter-to-class="translate-x-0"
      leave-active-class="transition-transform duration-300 ease-in"
      leave-from-class="translate-x-0"
      leave-to-class="-translate-x-full"
    >
      <div v-if="isMobileMenuOpen" class="fixed inset-y-0 left-0 z-50 lg:hidden bg-background h-full shadow-xl">
         <Sidebar @new-chat="handleNewChat" />
      </div>
    </Transition>

    <main class="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-background">
      <!-- Mobile Header -->
      <div class="lg:hidden flex items-center p-4 border-b bg-background shrink-0">
         <Button variant="ghost" size="icon" @click="isMobileMenuOpen = true" class="-ml-2">
            <Menu class="h-6 w-6" />
         </Button>
         <span class="ml-2 font-semibold text-lg">Zavixai Agent</span>
      </div>

      <div class="flex-1 overflow-hidden relative flex flex-col">
        <router-view @select-conversation="handleSelectConversation" :selected-conversation="selectedConversation" />
      </div>
    </main>
    <Toaster position="top-center" richColors />

    <LoginModal
        :visible="showLoginModal"
        @close="showLoginModal = false"
        @login-success="handleLoginSuccess"
    />
  </div>

</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import Sidebar from './views/Sidebar.vue'
import LoginModal from './components/LoginModal.vue'
import { Toaster } from '@/components/ui/sonner'
import { isLoggedIn } from './utils/auth.js'
import { Menu } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

const router = useRouter()
const route = useRoute()

// 登录模态框显示状态
const showLoginModal = ref(!isLoggedIn())

// Mobile menu state
const isMobileMenuOpen = ref(false)

// Close menu on route change
watch(() => route.path, () => {
  isMobileMenuOpen.value = false
})

// 选中的conversation数据
const selectedConversation = ref(null)

const handleNewChat = () => {
  selectedConversation.value = null
  isMobileMenuOpen.value = false
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


