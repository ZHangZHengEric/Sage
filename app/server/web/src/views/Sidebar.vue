<template>
  <div
    class="sidebar-shell group relative hidden h-full shrink-0 flex-col overflow-hidden border-r border-white/10 transition-all ease-in-out dark:border-white/10 lg:flex"
    :class="isResizing ? 'duration-0' : 'duration-300'"
    :style="sidebarShellStyle"
  >
    <div class="pointer-events-none absolute inset-0 opacity-30">
      <div class="absolute inset-x-0 top-[-12%] h-40" :style="sidebarTopGlowStyle" />
      <div class="absolute inset-x-0 bottom-[-10%] h-48" :style="sidebarBottomGlowStyle" />
    </div>

    <div class="relative h-4 shrink-0" />

    <Dialog v-model:open="showChangePasswordDialog">
      <DialogContent class="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{{ t('profile.changePasswordTitle') }}</DialogTitle>
          <DialogDescription>
            {{ t('profile.changePasswordDesc') }}
          </DialogDescription>
        </DialogHeader>
        <div class="grid gap-4 py-4">
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="old-password" class="text-right">
              {{ t('profile.currentPassword') }}
            </Label>
            <Input id="old-password" v-model="changePasswordForm.oldPassword" type="password" class="col-span-3" />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="new-password" class="text-right">
              {{ t('profile.newPassword') }}
            </Label>
            <Input id="new-password" v-model="changePasswordForm.newPassword" type="password" class="col-span-3" />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="confirm-password" class="text-right">
              {{ t('profile.confirmNewPassword') }}
            </Label>
            <Input id="confirm-password" v-model="changePasswordForm.confirmPassword" type="password" class="col-span-3" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showChangePasswordDialog = false">{{ t('common.cancel') }}</Button>
          <Button type="submit" :disabled="changingPassword" @click="handleChangePassword">
            <span v-if="changingPassword">{{ t('profile.changingPassword') }}</span>
            <span v-else>{{ t('profile.confirmChangePassword') }}</span>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <ScrollArea class="relative z-10 flex-1 px-2.5 pb-3">
      <div class="space-y-3 pt-0.5">
        <div v-if="activeSessionItems.length > 0" class="space-y-2">
          <div v-if="!isCollapsed" class="px-2.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-foreground/40">
            {{ t('sidebar.activeSessions') }}
          </div>
          <div v-if="!isCollapsed" class="space-y-1">
            <Button
              v-for="session in activeSessionItems"
              :key="session.id"
              variant="ghost"
              class="h-9 w-full justify-start rounded-[16px] border border-transparent px-2.5 text-[14px] font-medium text-muted-foreground transition-all duration-200 hover:border-white/10 hover:bg-[rgba(255,255,255,0.07)] hover:text-foreground dark:hover:bg-[rgba(255,255,255,0.06)]"
              :class="cn(
                isActiveSessionCurrent(session) && 'border-white/10 bg-[rgba(255,255,255,0.10)] text-foreground shadow-[0_8px_20px_rgba(15,23,42,0.08)] dark:bg-[rgba(255,255,255,0.07)]'
              )"
              @click="handleActiveSessionClick(session)"
            >
              <component :is="getSessionStatusIcon(session.sessionStatus)" class="mr-2 h-4 w-4 shrink-0" :class="getSessionStatusClass(session.sessionStatus)" />
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
              class="h-9 w-9 rounded-[14px] text-muted-foreground transition-all duration-200 hover:bg-[rgba(255,255,255,0.07)] hover:text-foreground dark:hover:bg-[rgba(255,255,255,0.06)]"
              :class="isActiveSessionCurrent(session) ? 'bg-[rgba(255,255,255,0.10)] text-foreground shadow-[0_6px_16px_rgba(15,23,42,0.10)] dark:bg-[rgba(255,255,255,0.07)]' : ''"
              @click="handleActiveSessionClick(session)"
            >
              <component :is="getSessionStatusIcon(session.sessionStatus)" class="h-4 w-4" :class="getSessionStatusClass(session.sessionStatus)" />
            </Button>
          </div>
        </div>

        <template v-for="item in predefinedServices" :key="item.id">
          <div v-if="isCollapsed" class="group/item relative flex justify-center">
            <DropdownMenu v-if="item.children">
              <DropdownMenuTrigger as-child>
                <Button
                  variant="ghost"
                  size="icon"
                  :class="[
                    'h-9 w-9 rounded-[14px] transition-all duration-200',
                    isCategoryActive(item) ? 'bg-[rgba(255,255,255,0.10)] text-foreground shadow-[0_6px_16px_rgba(15,23,42,0.10)] dark:bg-[rgba(255,255,255,0.07)]' : 'text-muted-foreground hover:bg-[rgba(255,255,255,0.07)] hover:text-foreground dark:hover:bg-[rgba(255,255,255,0.06)]'
                  ]"
                >
                  <component :is="getCategoryIcon(item.key)" class="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent side="right" align="start" class="w-48 ml-2">
                <DropdownMenuLabel>{{ item.rawName || t(item.nameKey) }}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  v-for="service in item.children"
                  :key="service.id"
                  :class="{ 'bg-muted font-medium text-primary': isCurrentService(service.url, service.isInternal) }"
                  @click="handleMenuClick(service.url, service.rawName || t(service.nameKey), service.isInternal, service.query)"
                >
                  {{ service.rawName || t(service.nameKey) }}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            <Button
              v-else
              variant="ghost"
              size="icon"
              :title="item.rawName || t(item.nameKey)"
              :class="[
                'h-9 w-9 rounded-[14px] transition-all duration-200',
                isCurrentService(item.url, item.isInternal) ? 'bg-[rgba(255,255,255,0.10)] text-foreground shadow-[0_6px_16px_rgba(15,23,42,0.10)] dark:bg-[rgba(255,255,255,0.07)]' : 'text-muted-foreground hover:bg-[rgba(255,255,255,0.07)] hover:text-foreground dark:hover:bg-[rgba(255,255,255,0.06)]'
              ]"
              @click="handleMenuClick(item.url, item.rawName || t(item.nameKey), item.isInternal, item.query)"
            >
              <component :is="getCategoryIcon(item.key)" class="h-4 w-4" />
            </Button>
          </div>

          <template v-else>
            <Collapsible v-if="item.children" v-model:open="expandedCategories[item.key]" class="space-y-1">
              <CollapsibleTrigger class="group flex w-full items-center rounded-[16px] px-2.5 py-2 text-[14px] font-medium text-muted-foreground transition-all duration-200 hover:bg-[rgba(255,255,255,0.07)] hover:text-foreground dark:hover:bg-[rgba(255,255,255,0.06)]">
                <component :is="getCategoryIcon(item.key)" class="mr-2 h-4 w-4" />
                <span class="flex-1 text-left truncate">{{ item.rawName || t(item.nameKey) }}</span>
                <ChevronDown class="h-4 w-4 text-muted-foreground/50 transition-transform duration-200 group-hover:text-foreground/60" :class="{ '-rotate-90': !expandedCategories[item.key] }" />
              </CollapsibleTrigger>

              <CollapsibleContent class="space-y-1">
                <div v-for="service in item.children" :key="service.id">
                  <Button
                    variant="ghost"
                    class="mb-0.5 h-8.5 w-full justify-start rounded-[14px] pl-8 text-[13px] font-medium text-muted-foreground"
                    :class="cn(
                      'transition-all duration-200 hover:bg-[rgba(255,255,255,0.07)] hover:text-foreground dark:hover:bg-[rgba(255,255,255,0.06)]',
                      isCurrentService(service.url, service.isInternal) && 'bg-[rgba(255,255,255,0.10)] text-foreground shadow-[0_6px_16px_rgba(15,23,42,0.08)] dark:bg-[rgba(255,255,255,0.07)]'
                    )"
                    @click="handleMenuClick(service.url, service.rawName || t(service.nameKey), service.isInternal, service.query)"
                  >
                    <span class="truncate">{{ service.rawName || t(service.nameKey) }}</span>
                  </Button>
                </div>
              </CollapsibleContent>
            </Collapsible>

            <Button
              v-else
              variant="ghost"
              class="mb-0.5 h-9.5 w-full justify-start rounded-[16px] px-2.5 font-medium text-muted-foreground transition-all duration-200 hover:bg-[rgba(255,255,255,0.07)] hover:text-foreground dark:hover:bg-[rgba(255,255,255,0.06)]"
              :class="cn(
                isCurrentService(item.url, item.isInternal) && 'bg-[rgba(255,255,255,0.10)] text-foreground shadow-[0_6px_16px_rgba(15,23,42,0.08)] dark:bg-[rgba(255,255,255,0.07)]'
              )"
              @click="handleMenuClick(item.url, item.rawName || t(item.nameKey), item.isInternal, item.query)"
            >
              <component :is="getCategoryIcon(item.key)" class="mr-2 h-4 w-4" />
              <span class="flex-1 text-left truncate">{{ item.rawName || t(item.nameKey) }}</span>
            </Button>
          </template>
        </template>
      </div>
    </ScrollArea>

    <div class="relative z-10 px-2.5 pb-2">
      <div v-if="isCollapsed" class="group/item relative flex justify-center">
        <Button
          variant="ghost"
          size="icon"
          :title="t('sidebar.downloadClient')"
          :class="[
            'h-9 w-9 rounded-[14px] transition-all duration-200',
            isCurrentService('Download', true) ? 'bg-[rgba(255,255,255,0.10)] text-foreground shadow-[0_6px_16px_rgba(15,23,42,0.10)] dark:bg-[rgba(255,255,255,0.07)]' : 'text-muted-foreground hover:bg-[rgba(255,255,255,0.07)] hover:text-foreground dark:hover:bg-[rgba(255,255,255,0.06)]'
          ]"
          @click="handleMenuClick('Download', t('sidebar.downloadClient'), true)"
        >
          <Download class="h-4 w-4" />
        </Button>
      </div>
      <Button
        v-else
        variant="ghost"
        class="mb-0.5 h-9.5 w-full justify-start rounded-[16px] px-2.5 font-medium text-muted-foreground transition-all duration-200 hover:bg-[rgba(255,255,255,0.07)] hover:text-foreground dark:hover:bg-[rgba(255,255,255,0.06)]"
        :class="cn(
          isCurrentService('Download', true) && 'bg-[rgba(255,255,255,0.10)] text-foreground shadow-[0_6px_16px_rgba(15,23,42,0.08)] dark:bg-[rgba(255,255,255,0.07)]'
        )"
        @click="handleMenuClick('Download', t('sidebar.downloadClient'), true)"
      >
        <Download class="mr-2 h-4 w-4" />
        <span class="flex-1 text-left truncate">{{ t('sidebar.downloadClient') }}</span>
      </Button>
    </div>

    <div class="relative z-10 border-t border-white/10 px-3 pb-3 pt-2.5 dark:border-white/10">
      <div class="flex items-center gap-2.5" :class="isCollapsed ? 'justify-center' : ''">
        <div class="flex items-center gap-3 overflow-hidden">
          <img :src="logoUrl" alt="Sage Logo" class="h-9 w-9 shrink-0 rounded-xl" />
          <div v-if="!isCollapsed" class="min-w-0">
            <p class="truncate text-[14px] font-semibold tracking-[0.01em] text-foreground">Sage</p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          class="ml-auto h-7.5 w-7.5 shrink-0 rounded-[12px] text-muted-foreground transition-all duration-200 hover:bg-[rgba(255,255,255,0.07)] hover:text-foreground dark:hover:bg-[rgba(255,255,255,0.06)]"
          :title="isCollapsed ? t('common.expand') : t('common.collapse')"
          @click="toggleCollapse"
        >
          <PanelLeftClose v-if="!isCollapsed" class="h-4 w-4" />
          <PanelLeftOpen v-else class="h-4 w-4" />
        </Button>
      </div>
    </div>

    <div v-if="currentUser" class="relative z-10 px-3 pb-3">
      <DropdownMenu v-model:open="isDropdownOpen">
        <DropdownMenuTrigger as-child>
          <div
            class="flex w-full cursor-pointer items-center gap-3 rounded-[16px] border border-transparent p-2.5 transition-all duration-200 hover:border-white/10 hover:bg-[rgba(255,255,255,0.07)] group dark:hover:bg-[rgba(255,255,255,0.06)]"
            :class="{ 'justify-center': isCollapsed }"
          >
            <Avatar class="h-9 w-9 shrink-0 border border-white/10 bg-background/40">
              <AvatarImage :src="currentUser.avatar" />
              <AvatarFallback class="bg-primary/10 text-primary font-bold">
                {{ (currentUser.nickname?.[0] || currentUser.username?.[0] || 'U').toUpperCase() }}
              </AvatarFallback>
            </Avatar>
            <div v-if="!isCollapsed" class="flex-1 min-w-0 text-left">
              <p class="text-sm font-medium truncate text-foreground/85 group-hover:text-foreground">
                {{ currentUser.nickname || currentUser.username }}
              </p>
            </div>
            <ChevronDown
              v-if="!isCollapsed"
              class="w-4 h-4 text-muted-foreground/50 transition-transform duration-200 group-hover:text-muted-foreground"
              :class="{ '-rotate-90': !isDropdownOpen, 'rotate-180': isDropdownOpen }"
            />
          </div>
        </DropdownMenuTrigger>
        <DropdownMenuContent class="w-56" :side="isCollapsed ? 'right' : 'top'" align="end" :sideOffset="isCollapsed ? 10 : 0">
          <DropdownMenuLabel v-if="isCollapsed" class="font-normal">
            <div class="flex flex-col space-y-1">
              <p class="text-sm font-medium leading-none">{{ currentUser.nickname || currentUser.username }}</p>
              <p class="text-xs leading-none text-muted-foreground">{{ t('sidebar.userProfile') }}</p>
            </div>
          </DropdownMenuLabel>
          <DropdownMenuSeparator v-if="isCollapsed" />
          <DropdownMenuItem @click="toggleLanguage">
            <Globe class="mr-2 h-4 w-4" />
            <span>{{ isZhCN ? t('sidebar.langToggleZh') : t('sidebar.langToggleEn') }}</span>
          </DropdownMenuItem>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <Sun v-if="themeStore.theme === 'light'" class="mr-2 h-4 w-4" />
              <Moon v-else-if="themeStore.theme === 'dark'" class="mr-2 h-4 w-4" />
              <Monitor v-else class="mr-2 h-4 w-4" />
              <span>{{ t('sidebar.theme') }}</span>
            </DropdownMenuSubTrigger>
            <DropdownMenuPortal>
              <DropdownMenuSubContent>
                <DropdownMenuItem @click="themeStore.setTheme('light')">
                  <Sun class="mr-2 h-4 w-4" />
                  <span>{{ t('sidebar.themeLight') }}</span>
                  <Check v-if="themeStore.theme === 'light'" class="ml-auto h-4 w-4" />
                </DropdownMenuItem>
                <DropdownMenuItem @click="themeStore.setTheme('dark')">
                  <Moon class="mr-2 h-4 w-4" />
                  <span>{{ t('sidebar.themeDark') }}</span>
                  <Check v-if="themeStore.theme === 'dark'" class="ml-auto h-4 w-4" />
                </DropdownMenuItem>
                <DropdownMenuItem @click="themeStore.setTheme('system')">
                  <Monitor class="mr-2 h-4 w-4" />
                  <span>{{ t('sidebar.themeSystem') }}</span>
                  <Check v-if="themeStore.theme === 'system'" class="ml-auto h-4 w-4" />
                </DropdownMenuItem>
              </DropdownMenuSubContent>
            </DropdownMenuPortal>
          </DropdownMenuSub>
          <DropdownMenuItem @select.prevent="showChangePasswordDialog = true">
            <KeyRound class="mr-2 h-4 w-4" />
            <span>{{ t('profile.changePassword') }}</span>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem class="text-red-600" @click="handleLogout">
            <LogOut class="mr-2 h-4 w-4" />
            <span>{{ t('auth.logout') }}</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
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
  PanelLeftOpen,
  Sun,
  Moon,
  Monitor,
  Check,
  LoaderCircle,
  CircleCheckBig,
  Activity,
  Download
} from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { useThemeStore } from '../stores/theme.js'
import { getCurrentUser, logout } from '../utils/auth.js'
import { userAPI } from '@/api/user'
import { toast } from 'vue-sonner'
import { useSidebarActiveSessions } from '@/composables/sidebar/useSidebarActiveSessions'
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
const themeStore = useThemeStore()
const props = defineProps({
  expandedWidth: {
    type: Number,
    default: 246
  },
  collapsedWidth: {
    type: Number,
    default: 78
  },
  isResizing: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['new-chat', 'collapse-change'])
const logoUrl = computed(() => {
  const logoName = themeStore.isDark ? 'sage_logo.svg' : 'sage_logo_white.svg'
  return `${import.meta.env.BASE_URL}${logoName}`
})
const observabilityProxyUrl = '/jaeger/'

const currentUser = ref(getCurrentUser())
const isCollapsed = ref(false)
watch(
  isCollapsed,
  (value) => {
    emit('collapse-change', value)
  },
  { immediate: true }
)
const isDropdownOpen = ref(false)
const showChangePasswordDialog = ref(false)
const changePasswordForm = ref({
  oldPassword: '',
  newPassword: '',
  confirmPassword: ''
})
const changingPassword = ref(false)

const sidebarShellStyle = computed(() => ({
  width: `${isCollapsed.value ? props.collapsedWidth : props.expandedWidth}px`,
  minWidth: `${isCollapsed.value ? props.collapsedWidth : props.expandedWidth}px`,
  maxWidth: `${isCollapsed.value ? props.collapsedWidth : props.expandedWidth}px`,
  backgroundColor: themeStore.isDark ? 'rgba(4, 4, 5, 0.94)' : 'rgba(255, 255, 255, 0.85)',
  backgroundImage: themeStore.isDark
    ? 'linear-gradient(180deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0.01))'
    : 'linear-gradient(180deg, rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0.03))',
  boxShadow: themeStore.isDark
    ? 'inset -1px 0 0 rgba(255, 255, 255, 0.06)'
    : 'inset -1px 0 0 rgba(255, 255, 255, 0.35)'
}))

const sidebarTopGlowStyle = computed(() => ({
  background: themeStore.isDark
    ? 'radial-gradient(circle at top left, rgba(255,255,255,0.05), transparent 60%)'
    : 'radial-gradient(circle at top left, rgba(96,165,250,0.08), transparent 60%)'
}))

const sidebarBottomGlowStyle = computed(() => ({
  background: themeStore.isDark
    ? 'radial-gradient(circle at bottom, rgba(255,255,255,0.03), transparent 60%)'
    : 'radial-gradient(circle at bottom, rgba(45,212,191,0.04), transparent 60%)'
}))

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
  onSessionClick: handleActiveSessionNavigate
})

const handleUserUpdated = () => {
  currentUser.value = getCurrentUser()
}

const toggleCollapse = () => {
  isCollapsed.value = !isCollapsed.value
}

const handleChangePassword = async () => {
  if (!changePasswordForm.value.oldPassword || !changePasswordForm.value.newPassword) {
    toast.error(t('profile.passwordRequired'))
    return
  }

  if (changePasswordForm.value.newPassword !== changePasswordForm.value.confirmPassword) {
    toast.error(t('auth.passwordsMismatch'))
    return
  }

  changingPassword.value = true
  try {
    await userAPI.changePassword(
      changePasswordForm.value.oldPassword,
      changePasswordForm.value.newPassword
    )
    toast.success(t('profile.passwordChangedRelogin'))
    showChangePasswordDialog.value = false
    handleLogout()
  } catch (error) {
    console.error(error)
    toast.error(error.message || t('profile.passwordChangeFailed'))
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
        { id: 'svc_sys_settings', nameKey: 'sidebar.systemSettings', url: 'SystemSettings', isInternal: true },
        { id: 'svc_version_list', nameKey: 'system.versionManagement', url: 'VersionList', isInternal: true }
      ]
    })

    services.push({
      id: 'cat_ops',
      key: 'operation_management',
      nameKey: 'sidebar.operationManagement',
      children: [
        {
          id: 'svc_request_records',
          nameKey: 'sidebar.requestRecords',
          url: observabilityProxyUrl,
          isInternal: false
        }
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
  system_management: false,
  operation_management: false
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
    system_management: Settings,
    operation_management: Activity,
    download_client: Download
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
    return route.name === url || (route.name === 'KnowledgeBaseDetail' && url === 'KnowledgeBase')
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

    if (route.name === url && url === 'AgentConfig') {
      router.replace({
        name: url,
        query: { ...route.query, refresh: Date.now() }
      })
      return
    }

    if (url === 'Download') {
      router.push({ name: 'Download' })
      return
    }

    router.push({ name: url, query })
  } else {
    window.open(url, '_blank')
  }
}

const handleLogout = async () => {
  const nextPath = route.fullPath && route.fullPath !== '/login' ? route.fullPath : '/agent/chat'
  await logout()
  currentUser.value = null
  router.replace({
    name: 'Login',
    query: { next: nextPath }
  })
}
</script>

<style scoped>
.sidebar-shell {
  backdrop-filter: none;
}
</style>
