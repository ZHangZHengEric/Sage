<template>
  <div 
    class="group relative flex flex-col h-full bg-slate-100/60 border-r-0 transition-all duration-300 ease-in-out"
    :class="[isCollapsed ? 'w-[70px]' : 'w-[240px]']"
  >
    <!-- Header -->
    <div class="p-4 flex items-center justify-between" :class="{'justify-center': isCollapsed}">
      <div v-if="!isCollapsed" class="flex items-center gap-2 overflow-hidden">
        <img src="/sage_logo.svg" alt="Sage Logo" class="h-8 w-8 shrink-0" />
        <h2 
          class="text-xl font-bold bg-gradient-to-r from-primary to-purple-600 bg-clip-text text-transparent truncate"
        >
          Sage
        </h2>
      </div>
      <div v-else class="flex justify-center w-full">
         <img src="/sage_logo.svg" alt="Sage Logo" class="h-8 w-8 shrink-0" />
      </div>

      <Button 
        v-if="!isCollapsed"
        variant="ghost" 
        size="icon" 
        @click="toggleCollapse"
        :title="isCollapsed ? '展开' : '收起'"
        class="text-muted-foreground hover:text-foreground shrink-0 ml-1"
      >
        <PanelLeftClose class="h-4 w-4" />
      </Button>
      <Button 
         v-else
         variant="ghost"
         size="icon"
         @click="toggleCollapse"
         title="展开"
         class="absolute -right-3 top-6 bg-background border shadow-sm rounded-full h-6 w-6 p-0 hover:bg-accent z-50 flex items-center justify-center"
      >
         <PanelLeftOpen class="h-3 w-3" />
      </Button>
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
          
          <!-- Collapsed Mode -->
          <div v-if="isCollapsed" class="flex justify-center group/item relative">
            <!-- Item with children (Category) -->
            <DropdownMenu v-if="item.children">
               <DropdownMenuTrigger as-child>
                  <Button 
                    variant="ghost" 
                    size="icon" 
                    :class="[
                      'transition-all duration-200',
                      isCategoryActive(item) ? 'bg-white shadow text-primary' : 'text-muted-foreground hover:text-foreground'
                    ]"
                  >
                     <component :is="getCategoryIcon(item.key)" class="h-4 w-4" />
                  </Button>
               </DropdownMenuTrigger>
               <DropdownMenuContent side="right" align="start" class="w-48 ml-2">
                  <DropdownMenuLabel>{{ t(item.nameKey) }}</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem 
                    v-for="service in item.children" 
                    :key="service.id"
                    @click="handleMenuClick(service.url, t(service.nameKey), service.isInternal)"
                    :class="{'bg-muted font-medium text-primary': isCurrentService(service.url, service.isInternal)}"
                  >
                     {{ t(service.nameKey) }}
                  </DropdownMenuItem>
               </DropdownMenuContent>
            </DropdownMenu>

            <!-- Item without children (Direct Link) -->
            <Button
               v-else
               variant="ghost"
               size="icon"
               :title="t(item.nameKey)"
               :class="[
                 'transition-all duration-200',
                 isCurrentService(item.url, item.isInternal) ? 'bg-white shadow text-primary' : 'text-muted-foreground hover:text-foreground'
               ]"
               @click="handleMenuClick(item.url, t(item.nameKey), item.isInternal)"
            >
               <component :is="getCategoryIcon(item.key)" class="h-4 w-4" />
            </Button>
          </div>

          <!-- Expanded Mode -->
          <template v-else>
            <!-- Item with children (Category) -->
            <Collapsible
              v-if="item.children"
              v-model:open="expandedCategories[item.key]"
              class="space-y-1"
            >
              <CollapsibleTrigger class="flex items-center w-full px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded-md transition-colors group">
                <component :is="getCategoryIcon(item.key)" class="mr-2 h-4 w-4" />
                <span class="flex-1 text-left truncate">{{ t(item.nameKey) }}</span>
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
                    <span class="truncate">{{ t(service.nameKey) }}</span>
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
              <span class="flex-1 text-left truncate">{{ t(item.nameKey) }}</span>
            </Button>
          </template>

        </template>
      </div>
    </ScrollArea>

    <!-- Footer User Profile -->
    <div class="p-4 mt-auto" v-if="currentUser">
      <DropdownMenu v-model:open="isDropdownOpen">
        <DropdownMenuTrigger as-child>
          <div 
            class="flex items-center gap-3 p-2 rounded-xl cursor-pointer hover:bg-white hover:shadow-sm transition-all duration-200 w-full group"
            :class="{'justify-center': isCollapsed}"
          >
            <Avatar class="h-9 w-9 border-2 border-white shadow-sm group-hover:border-primary/20 transition-colors shrink-0">
              <AvatarImage :src="currentUser.avatar" />
              <AvatarFallback class="bg-primary/10 text-primary font-bold">
                {{ (currentUser.nickname?.[0] || currentUser.username?.[0] || 'U').toUpperCase() }}
              </AvatarFallback>
            </Avatar>
            <div v-if="!isCollapsed" class="flex-1 min-w-0 text-left">
              <p class="text-sm font-medium truncate text-foreground/80 group-hover:text-foreground">
                {{ currentUser.nickname || currentUser.username }}
              </p>
            </div>
            <ChevronDown 
              v-if="!isCollapsed"
              class="w-4 h-4 text-muted-foreground/50 group-hover:text-muted-foreground transition-transform duration-200" 
              :class="{ '-rotate-90': !isDropdownOpen, 'rotate-180': isDropdownOpen }"
            />
          </div>
        </DropdownMenuTrigger>
        <DropdownMenuContent class="w-56" :side="isCollapsed ? 'right' : 'top'" align="end" :sideOffset="isCollapsed ? 10 : 0">
          <DropdownMenuLabel class="font-normal" v-if="isCollapsed">
             <div class="flex flex-col space-y-1">
                <p class="text-sm font-medium leading-none">{{ currentUser.nickname || currentUser.username }}</p>
                <p class="text-xs leading-none text-muted-foreground">User Profile</p>
             </div>
          </DropdownMenuLabel>
          <DropdownMenuSeparator v-if="isCollapsed" />
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
  KeyRound,
  PanelLeftClose,
  PanelLeftOpen
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
const isCollapsed = ref(false)

const handleUserUpdated = () => {
  currentUser.value = getCurrentUser()
}

const toggleCollapse = () => {
  isCollapsed.value = !isCollapsed.value
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
    console.error(error)
    toast.error(error.message || '修改失败')
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
    { id: 'svc_agent', key: 'agent_list', nameKey: 'sidebar.agentList', url: 'AgentConfig', isInternal: true },
    {
      id: 'cat_personal',
      key: 'personal_center',
      nameKey: 'sidebar.personalCenter',
      children: [
        { id: 'svc_model_provider', nameKey: 'modelProvider.menuTitle', url: 'ModelProviderList', isInternal: true },
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
    agent_list: Bot,
    personal_center: Users,
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

const isCategoryActive = (item) => {
  if (!item.children) return false
  return item.children.some(child => isCurrentService(child.url, child.isInternal))
}

const handleMenuClick = (url, name, isInternal) => {
  if (isInternal) {
    if (url === 'Chat') {
      emit('new-chat')
      // 如果已经在 Chat 页面，触发重置后直接返回，避免重复 push
      if (route.name === 'Chat') return
    }
    
    // 如果已经在当前页面，且是AgentConfig，添加刷新参数触发重置
    if (route.name === url && url === 'AgentConfig') {
      router.replace({ 
        name: url, 
        query: { ...route.query, refresh: Date.now() } 
      })
      return
    }
    
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
