<template>
  <div 
    class="group relative flex flex-col h-full bg-muted/40 border-r transition-all duration-300 ease-in-out"
    :class="[isCollapsed ? 'w-[70px]' : 'w-[170px]']"
  >
    <!-- Header -->
    <div class="p-4 flex items-center justify-between" :class="{'justify-center': isCollapsed}">
      <div v-if="!isCollapsed" class="flex items-center gap-2 overflow-hidden">
        <img :src="themeStore.isDark ? '/sage_logo.svg' : '/sage_logo_white.svg'" alt="Sage Logo" class="h-8 w-8 shrink-0" />
        <h2 
          class="text-xl font-bold bg-gradient-to-r from-primary to-purple-600 bg-clip-text text-transparent truncate"
        >
          Sage
        </h2>
      </div>
      <div v-else class="flex justify-center w-full">
         <img :src="themeStore.isDark ? '/sage_logo.svg' : '/sage_logo_white.svg'" alt="Sage Logo" class="h-8 w-8 shrink-0" />
      </div>

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
        <div v-if="activeSessionItems.length > 0" class="space-y-2">
          <div v-if="!isCollapsed" class="px-2 text-[11px] font-medium tracking-wide text-muted-foreground/80">
            进行中的会话
          </div>
          <div v-if="!isCollapsed" class="space-y-1">
            <Button
              v-for="session in activeSessionItems"
              :key="session.id"
              variant="ghost"
              class="w-full justify-start h-9 px-2 text-sm font-normal text-muted-foreground border border-transparent hover:border-border hover:bg-background hover:text-foreground"
              :class="cn(
                isActiveSessionCurrent(session) && 'bg-background text-primary border-border shadow-sm font-medium'
              )"
              @click="handleActiveSessionClick(session)"
            >
              <component
                :is="getSessionStatusIcon(session.sessionStatus)"
                class="mr-2 h-4 w-4 shrink-0"
                :class="getSessionStatusClass(session.sessionStatus)"
              />
              <span class="truncate">{{ session.rawName }}</span>
            </Button>
          </div>
          <div v-else class="space-y-1 flex flex-col items-center">
            <Button
              v-for="session in activeSessionItems"
              :key="session.id"
              variant="ghost"
              size="icon"
              :title="session.rawName"
              class="transition-all duration-200 text-muted-foreground hover:text-foreground"
              :class="isActiveSessionCurrent(session) ? 'bg-background shadow text-primary' : ''"
              @click="handleActiveSessionClick(session)"
            >
              <component
                :is="getSessionStatusIcon(session.sessionStatus)"
                class="h-4 w-4"
                :class="getSessionStatusClass(session.sessionStatus)"
              />
            </Button>
          </div>
        </div>
        <template v-for="item in predefinedServices" :key="item.id">
          
          <!-- Collapsed Mode -->
          <div v-if="isCollapsed" class="flex justify-center group/item relative">
            <!-- Item with children (Category) -->
            <DropdownMenu v-if="item.children">
               <DropdownMenuTrigger as-child>
                  <Button 
                    :id="item.tourId"
                    variant="ghost" 
                    size="icon" 
                    :class="[
                      'transition-all duration-200',
                      isCategoryActive(item) ? 'bg-background shadow text-primary' : 'text-muted-foreground hover:text-foreground'
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
                    @click="handleMenuClick(service.url, t(service.nameKey), service.isInternal, service.query)"
                    :class="{'bg-muted font-medium text-primary': isCurrentService(service.url, service.isInternal)}"
                  >
                     {{ t(service.nameKey) }}
                  </DropdownMenuItem>
               </DropdownMenuContent>
            </DropdownMenu>

            <!-- Item without children (Direct Link) -->
            <Button
               v-else
               :id="item.tourId"
               variant="ghost"
               size="icon"
               :title="t(item.nameKey)"
               :class="[
                 'transition-all duration-200',
                 isCurrentService(item.url, item.isInternal) ? 'bg-background shadow text-primary' : 'text-muted-foreground hover:text-foreground'
               ]"
               @click="handleMenuClick(item.url, t(item.nameKey), item.isInternal, item.query)"
            >
               <component :is="getCategoryIcon(item.key)" class="h-4 w-4" />
            </Button>
          </div>

          <!-- Expanded Mode -->
          <template v-else>
            <!-- Item with children (Category) -->
            <Collapsible
              v-if="item.children"
              :id="item.tourId"
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
                      'hover:bg-background hover:shadow-sm hover:text-primary transition-all duration-200',
                      isCurrentService(service.url, service.isInternal) && 'bg-background shadow text-primary font-semibold'
                    )"
                    @click="handleMenuClick(service.url, t(service.nameKey), service.isInternal, service.query)"
                  >
                    <span class="truncate">{{ t(service.nameKey) }}</span>
                  </Button>
                </div>
              </CollapsibleContent>
            </Collapsible>

            <!-- Item without children (Direct Link) -->
            <Button
              v-else
              :id="item.tourId"
              variant="ghost"
            class="w-full justify-start h-10 px-3 font-medium text-muted-foreground hover:text-foreground hover:bg-background hover:shadow-sm transition-all duration-200 mb-1"
            :class="cn(
              isCurrentService(item.url, item.isInternal) && 'bg-background shadow text-primary font-bold'
            )"
              @click="handleMenuClick(item.url, t(item.nameKey), item.isInternal, item.query)"
            >
              <component :is="getCategoryIcon(item.key)" class="mr-2 h-4 w-4" />
              <span class="flex-1 text-left truncate">{{ t(item.nameKey) }}</span>
            </Button>
          </template>

        </template>
      </div>
    </ScrollArea>

    <!-- Collapse Toggle Button -->
    <div class="p-2 border-t flex justify-center">
      <Button
        variant="ghost"
        size="icon"
        class="h-8 w-8 text-muted-foreground hover:text-foreground transition-all duration-200"
        @click="isCollapsed = !isCollapsed"
        :title="isCollapsed ? '展开' : '收起'"
      >
        <ChevronLeft v-if="!isCollapsed" class="h-4 w-4" />
        <ChevronRight v-else class="h-4 w-4" />
      </Button>
    </div>

  </div>
  
  <LoginModal 
    :visible="showLoginModal" 
    @close="showLoginModal = false"
    @login-success="handleLoginSuccess"
  />
</template>

<script>
// 禁用属性继承，因为组件使用了 Dialog (teleport) 导致多根节点
export default {
  inheritAttrs: false
}
</script>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import LoginModal from '../components/LoginModal.vue'
import { 
  MessageSquare, 
  Bot, 
  Wrench, 
  Zap, 
  Clock, 
  ChevronDown,
  LogOut,
  Settings,
  LayoutGrid,
  Users,
  KeyRound,
  LoaderCircle,
  CircleCheckBig,
  ChevronLeft,
  ChevronRight
} from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'

import { getCurrentUser, logout } from '../utils/auth.js'
import { userAPI } from '@/api/user'
import { chatAPI } from '@/api/chat'
import { toast } from 'vue-sonner'
import { useSidebarActiveSessions } from '@/composables/sidebar/useSidebarActiveSessions'
import { useThemeStore } from '@/stores/theme'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuPortal
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

import { useTour } from '../utils/tour'

const themeStore = useThemeStore()

const router = useRouter()
const route = useRoute()
const { t } = useLanguage()
const { startSidebarTour } = useTour()
const emit = defineEmits(['new-chat'])

const currentUser = ref(getCurrentUser())
const isCollapsed = ref(false)
const handleActiveSessionNavigate = (session) => {
  handleMenuClick(session.url, session.rawName, session.isInternal, session.query)
}

const {
  activeSessionItems,
  handleActiveSessionClick,
  isActiveSessionCurrent,
  disableActiveSessionSelection
} = useSidebarActiveSessions({
  route,
  chatAPI,
  onSessionClick: handleActiveSessionNavigate
})

const handleUserUpdated = () => {
  currentUser.value = getCurrentUser()
}


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
  
  // Start tour after a short delay to ensure DOM is ready
  setTimeout(() => {
    startSidebarTour()
  }, 1000)
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
      isInternal: true,
      tourId: 'tour-sidebar-new-chat'
    },
    { id: 'svc_history', nameKey: 'sidebar.sessions', url: 'History', isInternal: true, tourId: 'tour-sidebar-history' },
    { id: 'svc_agent', key: 'agent_list', nameKey: 'sidebar.agentList', url: 'AgentConfig', isInternal: true, tourId: 'tour-sidebar-agent-list' },
    {
      id: 'cat_personal',
      key: 'personal_center',
      nameKey: 'sidebar.personalCenter',
      tourId: 'tour-sidebar-personal-center',
      children: [
        { id: 'svc_model_provider', nameKey: 'modelProvider.menuTitle', url: 'ModelProviderList', isInternal: true },
        { id: 'svc_scheduled_task', nameKey: 'scheduledTask.menuTitle', url: 'TaskList', isInternal: true },
        { id: 'svc_tools', nameKey: 'sidebar.toolsList', url: 'Tools', isInternal: true },
        { id: 'svc_skills', nameKey: 'sidebar.skillList', url: 'Skills', isInternal: true }
      ]
    },
    {
      id: 'svc_sys_settings',
      key: 'system_management',
      nameKey: 'sidebar.systemSettings',
      url: 'SystemSettings',
      isInternal: true,
      tourId: 'tour-sidebar-system-settings'
  
    }
  ]


  return services
})

const expandedCategories = ref({
  new_chat: true,
  agent_capabilities: false,
  history: false,
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
    history: Clock,
    system_management: Settings
  }
  return map[key] || LayoutGrid
}

const getSessionStatusIcon = (status) => status === 'completed' ? CircleCheckBig : LoaderCircle

const getSessionStatusClass = (status) =>
  status === 'completed' ? 'text-emerald-500' : 'text-blue-500 animate-spin'

const isCurrentService = (url, isInternal, query = {}) => {
  if (isInternal) {
    if (url === 'Chat' && query?.session_id) {
      return route.name === 'Chat' && route.query.session_id === query.session_id
    }
    return route.name === url
  }
  return false
}

const isCategoryActive = (item) => {
  if (!item.children) return false
  return item.children.some(child => isCurrentService(child.url, child.isInternal))
}

const handleMenuClick = (url, name, isInternal, query = {}) => {
  query = query || {}
  if (!(url === 'Chat' && query.session_id)) {
    disableActiveSessionSelection()
  }
  if (isInternal) {
    if (url === 'Chat' && !query.session_id) {
      emit('new-chat')
      if (route.name === 'Chat' && !route.query.session_id) return
    }
    
    // 如果已经在当前页面，且是AgentConfig，添加刷新参数触发重置
    if (route.name === url && url === 'AgentConfig') {
      router.replace({ 
        name: url, 
        query: { ...route.query, refresh: Date.now() } 
      })
      return
    }
    
    router.push({ name: url, query })
  } else {
    window.open(url, '_blank')
  }
}

const showLoginModal = ref(false)

const handleLogout = () => {
  if (currentUser.value && currentUser.value.isGuest) {
    showLoginModal.value = true
    return
  }
  
  logout()
  currentUser.value = null
  // 登出后自动转为 Guest
  localStorage.setItem('isGuest', 'true')
  currentUser.value = getCurrentUser()
  router.push({ name: 'Chat' })
}

const handleLoginSuccess = () => {
  showLoginModal.value = false
  currentUser.value = getCurrentUser()
}
</script>
