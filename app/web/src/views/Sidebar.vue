<template>
  <div class="flex flex-col w-[280px] h-full bg-slate-50/50 border-r">
    <!-- Header -->
    <div class="p-6 border-b bg-white/50 backdrop-blur-sm">
      <h2 class="text-xl font-bold bg-gradient-to-r from-primary to-purple-600 bg-clip-text text-transparent text-center mb-6">
        {{ t('app.title') }}
      </h2>
      
      <div v-if="currentUser" class="flex items-center gap-3 bg-white p-3 rounded-lg shadow-sm border">
        <Avatar class="h-9 w-9 border-2 border-primary/10">
          <AvatarImage :src="currentUser.avatar" />
          <AvatarFallback class="bg-primary/10 text-primary font-bold">
            {{ (currentUser.nickname?.[0] || currentUser.username?.[0] || 'U').toUpperCase() }}
          </AvatarFallback>
        </Avatar>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium truncate text-foreground">
            {{ currentUser.nickname || currentUser.username }}
          </p>
          <p class="text-xs text-muted-foreground truncate">User</p>
        </div>
        <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-destructive" @click="handleLogout" :title="t('auth.logout')">
          <LogOut class="w-4 h-4" />
        </Button>
      </div>
    </div>

    <!-- Navigation -->
    <ScrollArea class="flex-1 px-3 py-4">
      <div class="space-y-4">
        <Collapsible
          v-for="category in predefinedServices"
          :key="category.id"
          v-model:open="expandedCategories[category.key]"
          class="space-y-1"
        >
          <CollapsibleTrigger class="flex items-center w-full px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded-md transition-colors group">
            <component :is="getCategoryIcon(category.key)" class="mr-2 h-4 w-4" />
            <span class="flex-1 text-left">{{ t(category.nameKey) }}</span>
            <ChevronDown
              class="h-4 w-4 transition-transform duration-200 text-muted-foreground/50 group-hover:text-muted-foreground"
              :class="{ '-rotate-90': !expandedCategories[category.key] }"
            />
          </CollapsibleTrigger>
          
          <CollapsibleContent class="space-y-1">
            <div 
              v-for="service in category.children" 
              :key="service.id"
            >
              <Button
                variant="ghost"
                class="w-full justify-start h-9 pl-9 font-normal"
                :class="cn(
                  'hover:bg-primary/10 hover:text-primary',
                  isCurrentService(service.url, service.isInternal) && 'bg-primary/10 text-primary font-medium'
                )"
                @click="handleMenuClick(service.url, t(service.nameKey), service.isInternal)"
              >
                {{ t(service.nameKey) }}
              </Button>
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </ScrollArea>

    <!-- Footer -->
    <div class="p-4 border-t bg-white/50 backdrop-blur-sm">
      <Button variant="outline" class="w-full justify-start bg-white hover:bg-muted/50" @click="toggleLanguage">
        <Globe class="mr-2 h-4 w-4 text-muted-foreground" />
        <span>{{ isZhCN ? t('sidebar.langToggleZh') : t('sidebar.langToggleEn') }}</span>
      </Button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { 
  MessageSquare, 
  Bot, 
  Wrench, 
  Zap, 
  Book, 
  Clock, 
  Code, 
  Globe, 
  ChevronDown,
  LogOut,
  Settings,
  LayoutGrid
} from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { getCurrentUser, logout } from '../utils/auth.js'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { cn } from '@/utils/cn'

const router = useRouter()
const route = useRoute()
const { toggleLanguage, t, isZhCN } = useLanguage()
const emit = defineEmits(['new-chat'])

const currentUser = ref(getCurrentUser())

const handleUserUpdated = () => {
  currentUser.value = getCurrentUser()
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

const predefinedServices = ref([
  {
    id: 'cat1',
    key: 'chat_and_config',
    nameKey: 'sidebar.chatAndConfig',
    children: [
      { id: 'svc_chat', nameKey: 'sidebar.newChat', url: 'Chat', isInternal: true },
      { id: 'svc_agent', nameKey: 'sidebar.agentConfig', url: 'AgentConfig', isInternal: true }
    ]
  },
  {
    id: 'cat2',
    key: 'tools_and_services',
    nameKey: 'sidebar.toolsAndServices',
    children: [
      { id: 'svc_tools', nameKey: 'sidebar.toolsList', url: 'Tools', isInternal: true },
      { id: 'svc_mcps', nameKey: 'sidebar.mcpsManage', url: 'Mcps', isInternal: true }
    ]
  },
  {
    id: 'cat_skills',
    key: 'skills',
    nameKey: 'sidebar.skillLibrary',
    children: [
      { id: 'svc_skills', nameKey: 'sidebar.skillLibrary', url: 'Skills', isInternal: true }
    ]
  },
  {
    id: 'cat3',
    key: 'knowledge_base',
    nameKey: 'sidebar.knowledgeBase',
    children: [
      { id: 'svc_kdb', nameKey: 'sidebar.knowledgeBaseManage', url: 'KnowledgeBase', isInternal: true }
    ]
  },
  {
    id: 'cat4',
    key: 'history',
    nameKey: 'sidebar.sessions',
    children: [
      { id: 'svc_history', nameKey: 'sidebar.history', url: 'History', isInternal: true }
    ]
  },
  {
    id: 'cat5',
    key: 'api_reference',
    nameKey: 'sidebar.apiReference',
    children: [
      { id: 'svc_api_agent_chat', nameKey: 'sidebar.apiAgentChat', url: 'ApiAgentChat', isInternal: true }
    ]
  }
])

const expandedCategories = ref({
  chat_and_config: true,
  tools_and_services: false,
  knowledge_base: false,
  history: false,
  api_reference: false,
  skills: false
})

const getCategoryIcon = (key) => {
  const map = {
    chat_and_config: MessageSquare,
    tools_and_services: Wrench,
    skills: Zap,
    knowledge_base: Book,
    history: Clock,
    api_reference: Code
  }
  return map[key] || LayoutGrid
}

const isCurrentService = (url, isInternal) => {
  if (isInternal) return route.name === url || (route.name === 'KnowledgeBaseDetail' && url === 'KnowledgeBase')
  return false
}

const handleMenuClick = (url, name, isInternal) => {
  if (isInternal) {
    if (url === 'Chat') emit('new-chat')
    router.push({ name: url })
  } else {
    window.open(url, '_blank')
  }
}

const handleLogout = () => {
  logout()
  currentUser.value = null
  router.push({ name: 'Chat' })
}
</script>
