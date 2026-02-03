<template>
  <div class="flex flex-col w-[280px] h-full bg-slate-100/60 border-r-0">
    <!-- Header -->
    <div class="p-6 bg-transparent">
      <h2 class="text-xl font-bold bg-gradient-to-r from-primary to-purple-600 bg-clip-text text-transparent text-center mb-2">
        Zavixai Agent
      </h2>
    </div>

    <!-- Change Password Dialog -->
    <Dialog v-model:open="showChangePasswordDialog">
      <DialogContent class="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>修改密码</DialogTitle>
          <DialogDescription>
            请输入当前密码和新密码以修改您的登录密码。
          </DialogDescription>
        </DialogHeader>
        <div class="grid gap-4 py-4">
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="old-password" class="text-right">
              旧密码
            </Label>
            <Input
              id="old-password"
              v-model="changePasswordForm.oldPassword"
              type="password"
              class="col-span-3"
            />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="new-password" class="text-right">
              新密码
            </Label>
            <Input
              id="new-password"
              v-model="changePasswordForm.newPassword"
              type="password"
              class="col-span-3"
            />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="confirm-password" class="text-right">
              确认新密码
            </Label>
            <Input
              id="confirm-password"
              v-model="changePasswordForm.confirmPassword"
              type="password"
              class="col-span-3"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showChangePasswordDialog = false">取消</Button>
          <Button type="submit" @click="handleChangePassword" :disabled="changingPassword">
            <span v-if="changingPassword">修改中...</span>
            <span v-else>确认修改</span>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Navigation -->
    <ScrollArea class="flex-1 px-3">
      <div class="space-y-4">
        <template v-for="item in predefinedServices" :key="item.id">
          <!-- Item with children (Category) -->
          <Collapsible
            v-if="item.children"
            v-model:open="expandedCategories[item.key]"
            class="space-y-1"
          >
            <CollapsibleTrigger class="flex items-center w-full px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded-md transition-colors group">
              <component :is="getCategoryIcon(item.key)" class="mr-2 h-4 w-4" />
              <span class="flex-1 text-left">{{ t(item.nameKey) }}</span>
              <ChevronDown
                class="h-4 w-4 transition-transform duration-200 text-muted-foreground/50 group-hover:text-muted-foreground"
                :class="{ '-rotate-90': !expandedCategories[item.key] }"
              />
            </CollapsibleTrigger>
            
            <CollapsibleContent class="space-y-1">
              <div 
                v-for="service in item.children" 
                :key="service.id"
              >
                <Button
                  variant="ghost"
                  class="w-full justify-start h-9 pl-9 mb-0.5 text-sm font-normal text-muted-foreground"
                  :class="cn(
                    'hover:bg-white hover:shadow-sm hover:text-primary transition-all duration-200',
                    isCurrentService(service.url, service.isInternal) && 'bg-white shadow text-primary font-semibold'
                  )"
                  @click="handleMenuClick(service.url, t(service.nameKey), service.isInternal)"
                >
                  {{ t(service.nameKey) }}
                </Button>
              </div>
            </CollapsibleContent>
          </Collapsible>

          <!-- Item without children (Direct Link) -->
          <Button
            v-else
            variant="ghost"
            class="w-full justify-start h-10 px-3 font-medium text-muted-foreground hover:text-foreground hover:bg-white hover:shadow-sm transition-all duration-200 mb-1"
            :class="cn(
              isCurrentService(item.url, item.isInternal) && 'bg-white shadow text-primary font-bold'
            )"
            @click="handleMenuClick(item.url, t(item.nameKey), item.isInternal)"
          >
            <component :is="getCategoryIcon(item.key)" class="mr-2 h-4 w-4" />
            <span class="flex-1 text-left">{{ t(item.nameKey) }}</span>
          </Button>
        </template>
      </div>
    </ScrollArea>

    <!-- Footer User Profile -->
    <div class="p-4 mt-auto" v-if="currentUser">
      <DropdownMenu v-model:open="isDropdownOpen">
        <DropdownMenuTrigger as-child>
          <div class="flex items-center gap-3 p-3 rounded-xl cursor-pointer hover:bg-white hover:shadow-sm transition-all duration-200 w-full group">
            <Avatar class="h-9 w-9 border-2 border-white shadow-sm group-hover:border-primary/20 transition-colors">
              <AvatarImage :src="currentUser.avatar" />
              <AvatarFallback class="bg-primary/10 text-primary font-bold">
                {{ (currentUser.nickname?.[0] || currentUser.username?.[0] || 'U').toUpperCase() }}
              </AvatarFallback>
            </Avatar>
            <div class="flex-1 min-w-0 text-left">
              <p class="text-sm font-medium truncate text-foreground/80 group-hover:text-foreground">
                {{ currentUser.nickname || currentUser.username }}
              </p>
            </div>
            <ChevronDown 
              class="w-4 h-4 text-muted-foreground/50 group-hover:text-muted-foreground transition-transform duration-200" 
              :class="{ '-rotate-90': !isDropdownOpen, 'rotate-180': isDropdownOpen }"
            />
          </div>
        </DropdownMenuTrigger>
        <DropdownMenuContent class="w-56" side="top" align="end">
          <DropdownMenuItem @click="toggleLanguage">
             <Globe class="mr-2 h-4 w-4" />
             <span>{{ isZhCN ? t('sidebar.langToggleZh') : t('sidebar.langToggleEn') }}</span>
          </DropdownMenuItem>
          <DropdownMenuItem @select.prevent="showChangePasswordDialog = true">
            <KeyRound class="mr-2 h-4 w-4" />
            <span>修改密码</span>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem @click="handleLogout" class="text-red-600">
            <LogOut class="mr-2 h-4 w-4" />
            <span>{{ t('auth.logout') }}</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
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
  LayoutGrid,
  Users,
  KeyRound
} from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { getCurrentUser, logout } from '../utils/auth.js'
import { userAPI } from '@/api/user'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
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

const isDropdownOpen = ref(false)
const showChangePasswordDialog = ref(false)
const changePasswordForm = ref({
  oldPassword: '',
  newPassword: '',
  confirmPassword: ''
})
const changingPassword = ref(false)

const handleChangePassword = async () => {
  if (!changePasswordForm.value.oldPassword || !changePasswordForm.value.newPassword) {
    toast.error('请输入密码')
    return
  }
  
  if (changePasswordForm.value.newPassword !== changePasswordForm.value.confirmPassword) {
    toast.error('两次输入的密码不一致')
    return
  }
  
  changingPassword.value = true
  try {
    await userAPI.changePassword(
      changePasswordForm.value.oldPassword, 
      changePasswordForm.value.newPassword
    )
    toast.success('密码修改成功，请重新登录')
    showChangePasswordDialog.value = false
    handleLogout()
  } catch (error) {
    // Error is handled by request interceptor usually, but if not:
    console.error(error)
    // If request.js throws error with message
    // toast.error(error.message || '密码修改失败')
  } finally {
    changingPassword.value = false
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

const predefinedServices = computed(() => {
  const services = [
    {
      id: 'svc_chat',
      key: 'new_chat',
      nameKey: 'sidebar.newChat',
      url: 'Chat',
      isInternal: true
    },
    { id: 'svc_history', nameKey: 'sidebar.sessions', url: 'History', isInternal: true },
    {
      id: 'cat2',
      key: 'agent_capabilities',
      nameKey: 'sidebar.capabilityModules',
      children: [
        { id: 'svc_agent', nameKey: 'sidebar.agentList', url: 'AgentConfig', isInternal: true },
        { id: 'svc_tools', nameKey: 'sidebar.toolsList', url: 'Tools', isInternal: true },
        { id: 'svc_skills', nameKey: 'sidebar.skillList', url: 'Skills', isInternal: true },
        { id: 'svc_kdb', nameKey: 'sidebar.knowledgeBaseList', url: 'KnowledgeBase', isInternal: true }
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
  ]

  if (currentUser.value?.role === 'admin') {
    services.push({
      id: 'cat_sys',
      key: 'system_management',
      nameKey: 'sidebar.systemManagement',
      children: [
        { id: 'svc_user_list', nameKey: 'sidebar.userList', url: 'UserList', isInternal: true },
        { id: 'svc_sys_settings', nameKey: 'sidebar.systemSettings', url: 'SystemSettings', isInternal: true }
      ]
    })
  }

  return services
})

const expandedCategories = ref({
  new_chat: true,
  agent_capabilities: false,
  knowledge_base: false,
  history: false,
  api_reference: false,
  skills: false,
  system_management: false
})

const getCategoryIcon = (key) => {
  const map = {
    new_chat: MessageSquare,
    agent_capabilities: Wrench,
    skills: Zap,
    knowledge_base: Book,
    history: Clock,
    api_reference: Code,
    system_management: Settings
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
