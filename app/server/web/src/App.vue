<template>
  <div class="app flex h-screen overflow-hidden bg-background text-foreground">
    <!-- Desktop Sidebar -->
    <Sidebar 
      v-if="showDesktopSidebar"
      class="hidden lg:flex shrink-0" 
      :expanded-width="sidebarExpandedWidth"
      :is-resizing="isSidebarResizing"
      @new-chat="handleNewChat" 
      @collapse-change="handleSidebarCollapseChange"
    />

    <div
      v-if="showDesktopSidebar && !isSidebarCollapsed"
      class="hidden lg:block relative w-0 shrink-0"
    >
      <div
        class="group absolute inset-y-0 left-[-4px] z-20 flex w-2.5 cursor-ew-resize select-none items-stretch justify-center opacity-0 transition-opacity duration-150 hover:opacity-100"
        role="separator"
        aria-orientation="vertical"
        aria-label="调整侧边栏宽度"
        @pointerdown.stop.prevent="startSidebarResize"
      >
        <div class="h-full w-px rounded-full bg-border/70 transition-colors duration-150 group-hover:bg-primary/60" :class="isSidebarResizing ? 'bg-primary/80' : ''" />
      </div>
    </div>
    
    <main
      class="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-background"
      :class="hideShell ? 'pb-0' : 'pb-[64px] lg:pb-0'"
    >
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

const router = useRouter()
const route = useRoute()

const isSharedPage = computed(() => route.name === 'SharedChat' || route.path?.startsWith('/share/'))
const isLoginPage = computed(() => route.name === 'Login')
const hideShell = computed(() => isSharedPage.value || isLoginPage.value)
const showDesktopSidebar = computed(() => !hideShell.value)

const SIDEBAR_WIDTH_STORAGE_KEY = 'sage.web.sidebar.expandedWidth'
const SIDEBAR_MIN_WIDTH = 220
const SIDEBAR_MAX_WIDTH = 420
const SIDEBAR_DEFAULT_WIDTH = 246

const clampSidebarWidth = (value) => {
  const viewportMax = Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, window.innerWidth - 420))
  return Math.min(Math.max(Math.round(value), SIDEBAR_MIN_WIDTH), viewportMax)
}

const loadSidebarWidth = () => {
  const raw = window.localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY)
  const parsed = Number.parseInt(raw, 10)
  if (Number.isFinite(parsed)) {
    return clampSidebarWidth(parsed)
  }
  return SIDEBAR_DEFAULT_WIDTH
}

const saveSidebarWidth = (value) => {
  window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(clampSidebarWidth(value)))
}

const sidebarExpandedWidth = ref(loadSidebarWidth())
const isSidebarCollapsed = ref(false)
const isSidebarResizing = ref(false)

const showSetupModal = ref(false)

const maybeShowSetupModal = () => {
  if (hideShell.value) {
    showSetupModal.value = false
    return
  }

  const user = getCurrentUser()
  showSetupModal.value = Boolean(user && user.has_provider === false)
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

const handleSidebarCollapseChange = (collapsed) => {
  isSidebarCollapsed.value = collapsed
}

const startSidebarResize = (event) => {
  if (event.button !== 0) return
  event.preventDefault()

  const startX = event.clientX
  const startWidth = sidebarExpandedWidth.value
  const previousUserSelect = document.body.style.userSelect
  const previousCursor = document.body.style.cursor

  isSidebarResizing.value = true
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'ew-resize'

  const handlePointerMove = (moveEvent) => {
    sidebarExpandedWidth.value = clampSidebarWidth(startWidth + (moveEvent.clientX - startX))
  }

  const handlePointerUp = () => {
    isSidebarResizing.value = false
    document.body.style.userSelect = previousUserSelect
    document.body.style.cursor = previousCursor
    saveSidebarWidth(sidebarExpandedWidth.value)
    window.removeEventListener('pointermove', handlePointerMove)
    window.removeEventListener('pointerup', handlePointerUp)
  }

  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', handlePointerUp)
}

const handleUserUpdated = () => {
  maybeShowSetupModal()
}

onMounted(() => {
  if (typeof window !== 'undefined') {
    window.addEventListener('user-updated', handleUserUpdated)
    window.addEventListener('resize', handleWindowResize)
  }
})

onUnmounted(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('user-updated', handleUserUpdated)
    window.removeEventListener('resize', handleWindowResize)
  }
})

const handleWindowResize = () => {
  const clampedWidth = clampSidebarWidth(sidebarExpandedWidth.value)
  if (clampedWidth !== sidebarExpandedWidth.value) {
    sidebarExpandedWidth.value = clampedWidth
    saveSidebarWidth(clampedWidth)
  }
}
</script>
