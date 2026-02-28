<template>
  <div class="fixed bottom-0 left-0 right-0 z-50 bg-background/80 backdrop-blur-lg border-t border-border/40 pb-safe shadow-[0_-5px_15px_rgba(0,0,0,0.02)]">
    <div class="grid grid-cols-5 h-[60px] items-end relative">
      <!-- 1. My Agents -->
      <router-link 
        :to="{ name: 'AgentConfig' }"
        class="flex flex-col items-center justify-center h-full pb-1 space-y-1 text-muted-foreground/60 transition-all duration-300 active:scale-90 group"
        active-class="!text-primary font-medium"
      >
        <div class="relative p-1 rounded-xl group-hover:bg-primary/5 transition-colors">
          <Bot class="w-5 h-5 transition-transform duration-300 group-active:scale-90" />
        </div>
        <span class="text-[10px] font-medium">{{ t('sidebar.agentList') }}</span>
      </router-link>

      <!-- 2. History -->
      <router-link 
        :to="{ name: 'History' }"
        class="flex flex-col items-center justify-center h-full pb-1 space-y-1 text-muted-foreground/60 transition-all duration-300 active:scale-90 group"
        active-class="!text-primary font-medium"
      >
        <div class="relative p-1 rounded-xl group-hover:bg-primary/5 transition-colors">
          <Clock class="w-5 h-5 transition-transform duration-300 group-active:scale-90" />
        </div>
        <span class="text-[10px] font-medium">{{ t('sidebar.sessions') }}</span>
      </router-link>

      <!-- 3. New Chat (Middle Circle) -->
      <div class="relative flex justify-center h-full pointer-events-none z-10">
        <button
          class="pointer-events-auto flex items-center justify-center w-10 h-10 rounded-full bg-gradient-to-br from-primary to-primary/90 text-primary-foreground shadow-xl shadow-primary/25 ring-4 ring-background transition-all duration-300 active:scale-95 hover:shadow-2xl hover:shadow-primary/40 hover:-translate-y-0.5"
          @click="handleNewChat">
          <MessageSquare class="w-6 h-6" />
        </button>
      </div>

      <!-- 4. Capabilities (Dropdown) -->
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <button 
            class="flex flex-col items-center justify-center h-full pb-1 space-y-1 text-muted-foreground/60 transition-all duration-300 active:scale-90 outline-none group"
            :class="{ '!text-primary font-medium': isCapabilitiesActive }"
          >
            <div class="relative p-1 rounded-xl group-hover:bg-primary/5 transition-colors">
              <Wrench class="w-5 h-5 transition-transform duration-300 group-active:scale-90" />
            </div>
            <span class="text-[10px] font-medium">{{ t('sidebar.capabilityModules') }}</span>
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="center" class="w-48 mb-4 rounded-xl shadow-xl border-border/50 bg-background/95 backdrop-blur-md">
          <DropdownMenuItem @click="router.push({ name: 'Tools' })" class="py-3 px-4 cursor-pointer">
            <Zap class="mr-3 h-4 w-4 text-orange-500" />
            <span class="font-medium">{{ t('sidebar.toolsList') }}</span>
          </DropdownMenuItem>
          <DropdownMenuItem @click="router.push({ name: 'Skills' })" class="py-3 px-4 cursor-pointer">
            <LayoutGrid class="mr-3 h-4 w-4 text-blue-500" />
            <span class="font-medium">{{ t('sidebar.skillList') }}</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <!-- 5. Me -->
      <router-link 
        :to="{ name: 'MobileMe' }"
        class="flex flex-col items-center justify-center h-full pb-1 space-y-1 text-muted-foreground/60 transition-all duration-300 active:scale-90 group"
        active-class="!text-primary font-medium"
      >
        <div class="relative p-1 rounded-xl group-hover:bg-primary/5 transition-colors">
          <User class="w-5 h-5 transition-transform duration-300 group-active:scale-90" />
        </div>
        <span class="text-[10px] font-medium">{{ t('sidebar.userProfile') || '我的' }}</span>
      </router-link>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { 
  Bot, 
  Clock, 
  MessageSquare, 
  Wrench, 
  User,
  Zap,
  LayoutGrid,
  Book
} from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

const router = useRouter()
const route = useRoute()
const { t } = useLanguage()

const emit = defineEmits(['new-chat'])

const handleNewChat = () => {
  if (route.name === 'Chat') {
    emit('new-chat')
  } else {
    router.push({ name: 'Chat' })
  }
}

const isCapabilitiesActive = computed(() => {
  return ['Tools', 'Skills', 'ToolDetailView'].includes(route.name)
})
</script>

<style scoped>
.pb-safe {
  padding-bottom: env(safe-area-inset-bottom);
}
</style>
