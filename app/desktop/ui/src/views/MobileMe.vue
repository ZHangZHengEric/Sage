<template>
  <div class="flex flex-col h-full bg-background p-4 space-y-6 overflow-y-auto pb-24">
    <!-- User Profile Header -->
    <div class="flex items-center space-x-4 p-4 bg-muted/30 rounded-xl border">
      <Avatar class="h-16 w-16 border-2 border-background shadow-sm">
        <AvatarImage :src="currentUser?.avatar" />
        <AvatarFallback class="bg-primary/10 text-primary text-xl font-bold">
          {{ (currentUser?.nickname?.[0] || currentUser?.username?.[0] || 'U').toUpperCase() }}
        </AvatarFallback>
      </Avatar>
      <div class="flex-1 min-w-0">
        <h2 class="text-xl font-bold truncate">{{ currentUser?.nickname || currentUser?.username }}</h2>
        <p class="text-sm text-muted-foreground truncate">{{ currentUser?.email || 'User' }}</p>
      </div>
    </div>

    <!-- Settings Group -->
    <div class="space-y-2">
      <h3 class="text-sm font-medium text-muted-foreground px-1">通用设置</h3>
      <div class="bg-card rounded-xl border overflow-hidden">
        <div 
          class="flex items-center justify-between p-4 active:bg-muted/50 transition-colors cursor-pointer border-b last:border-0"
          @click="toggleLanguage"
        >
          <div class="flex items-center space-x-3">
            <div class="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg text-blue-600 dark:text-blue-400">
              <Globe class="w-5 h-5" />
            </div>
            <span>{{ isZhCN ? t('sidebar.langToggleZh') : t('sidebar.langToggleEn') }}</span>
          </div>
          <ChevronRight class="w-5 h-5 text-muted-foreground" />
        </div>
        
        <div 
          class="flex items-center justify-between p-4 active:bg-muted/50 transition-colors cursor-pointer border-b last:border-0"
          @click="showChangePasswordDialog = true"
        >
          <div class="flex items-center space-x-3">
            <div class="p-2 bg-orange-100 dark:bg-orange-900/30 rounded-lg text-orange-600 dark:text-orange-400">
              <KeyRound class="w-5 h-5" />
            </div>
            <span>修改密码</span>
          </div>
          <ChevronRight class="w-5 h-5 text-muted-foreground" />
        </div>
      </div>
    </div>

    <!-- System Management (Admin Only) -->
    <div v-if="currentUser?.role === 'admin'" class="space-y-2">
      <h3 class="text-sm font-medium text-muted-foreground px-1">系统管理</h3>
      <div class="bg-card rounded-xl border overflow-hidden">
        <div 
          class="flex items-center justify-between p-4 active:bg-muted/50 transition-colors cursor-pointer border-b last:border-0"
          @click="router.push({ name: 'UserList' })"
        >
          <div class="flex items-center space-x-3">
            <div class="p-2 bg-purple-100 dark:bg-purple-900/30 rounded-lg text-purple-600 dark:text-purple-400">
              <Users class="w-5 h-5" />
            </div>
            <span>{{ t('sidebar.userList') }}</span>
          </div>
          <ChevronRight class="w-5 h-5 text-muted-foreground" />
        </div>

        <div 
          class="flex items-center justify-between p-4 active:bg-muted/50 transition-colors cursor-pointer border-b last:border-0"
          @click="router.push({ name: 'SystemSettings' })"
        >
          <div class="flex items-center space-x-3">
            <div class="p-2 bg-slate-100 dark:bg-slate-800 rounded-lg text-slate-600 dark:text-slate-400">
              <Settings class="w-5 h-5" />
            </div>
            <span>{{ t('sidebar.systemSettings') }}</span>
          </div>
          <ChevronRight class="w-5 h-5 text-muted-foreground" />
        </div>
      </div>
    </div>

    <!-- Logout -->
    <div class="pt-4">
      <Button variant="destructive" class="w-full h-12 text-lg rounded-xl" @click="handleLogout">
        <LogOut class="mr-2 h-5 w-5" />
        {{ t('auth.logout') }}
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
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { 
  Globe, 
  ChevronRight, 
  LogOut, 
  Users, 
  Settings,
  KeyRound
} from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'
import { getCurrentUser, logout } from '@/utils/auth.js'
import { userAPI } from '@/api/user'
import { toast } from 'vue-sonner'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

const router = useRouter()
const { toggleLanguage, t, isZhCN } = useLanguage()
const currentUser = ref(getCurrentUser())

const handleUserUpdated = () => {
  currentUser.value = getCurrentUser()
}

const handleLogout = () => {
  logout()
  currentUser.value = null
  router.push({ name: 'Chat' })
}

// Password change logic
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
  window.addEventListener('user-updated', handleUserUpdated)
})

onUnmounted(() => {
  window.removeEventListener('user-updated', handleUserUpdated)
})
</script>
