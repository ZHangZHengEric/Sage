<template>
  <div class="h-full flex flex-col bg-muted/30">

    
    <div class="p-6">
        <Card class="p-6 max-w-2xl">
            <!-- Update Setting -->
            <div class="flex items-center justify-between py-4 border-b">
                <div class="space-y-0.5">
                    <Label class="text-base">{{ t('system.update') }}</Label>
                    <p class="text-sm text-muted-foreground">
                        {{ t('system.currentVersion') }}: {{ currentVersion }}
                    </p>
                </div>
                <div class="flex flex-col items-end gap-2">
                    <template v-if="downloading">
                      <div class="w-[180px] flex flex-col items-end gap-1">
                          <Progress 
                            :model-value="totalBytes > 0 ? downloadProgress : 100" 
                            class="h-2" 
                            :class="{'animate-pulse': totalBytes === 0}"
                          />
                          <div class="flex justify-between w-full text-xs text-muted-foreground">
                              <span>{{ formatBytes(downloadedBytes) }}</span>
                              <span v-if="totalBytes > 0">{{ downloadProgress }}%</span>
                          </div>
                          <p v-if="updateStatus" class="text-xs text-muted-foreground w-full text-right truncate" :title="updateStatus">
                            {{ updateStatus }}
                          </p>
                      </div>
                    </template>
                    <template v-else>
                      <Button 
                          variant="outline" 
                          size="sm"
                          @click="checkForUpdates"
                          :disabled="checking"
                      >
                          <Loader2 v-if="checking" class="w-4 h-4 mr-2 animate-spin" />
                          <DownloadCloud v-else class="w-4 h-4 mr-2" />
                          {{ checking ? t('system.checking') : t('system.checkNow') }}
                      </Button>
                      <p v-if="updateStatus" class="text-xs text-muted-foreground">{{ updateStatus }}</p>
                    </template>
                </div>
            </div>
            
            <!-- User Avatar Setting -->
            <div class="flex items-center justify-between py-4 border-b">
                <div class="space-y-0.5">
                    <Label class="text-base">{{ t('system.userAvatar') || '用户头像' }}</Label>
                    <p class="text-sm text-muted-foreground">
                        {{ t('system.userAvatarDesc') || '选择或随机生成您的头像' }}
                    </p>
                </div>
                <div class="flex items-center gap-3">
                    <img 
                        :src="userAvatarUrl" 
                        alt="User Avatar" 
                        class="w-12 h-12 rounded-full border-2 border-primary/20"
                    />
                    <Button 
                        variant="outline" 
                        size="sm"
                        @click="randomizeAvatar"
                        :title="t('system.randomAvatar') || '随机头像'"
                    >
                        <RefreshCw class="w-4 h-4 mr-1" />
                        {{ t('system.random') || '随机' }}
                    </Button>
                </div>
            </div>
            
            <!-- Language Setting -->
            <div class="flex items-center justify-between py-4 border-b">
                <div class="space-y-0.5">
                    <Label class="text-base">{{ t('sidebar.language') }}</Label>
                    <p class="text-sm text-muted-foreground">
                        {{ t('system.languageDesc') }}
                    </p>
                </div>
                <Select :model-value="language" @update:model-value="setLanguage">
                  <SelectTrigger class="w-[180px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="zhCN">简体中文</SelectItem>
                    <SelectItem value="enUS">English</SelectItem>
                  </SelectContent>
                </Select>
            </div>

            <!-- Theme Setting -->
            <div class="flex items-center justify-between py-4 border-b">
                <div class="space-y-0.5">
                    <Label class="text-base">{{ t('sidebar.theme') }}</Label>
                    <p class="text-sm text-muted-foreground">
                        {{ t('system.themeDesc') }}
                    </p>
                </div>
                <Select :model-value="themeStore.theme" @update:model-value="themeStore.setTheme">
                  <SelectTrigger class="w-[180px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="light">{{ t('sidebar.themeLight') }}</SelectItem>
                    <SelectItem value="dark">{{ t('sidebar.themeDark') }}</SelectItem>
                    <SelectItem value="system">{{ t('sidebar.themeSystem') }}</SelectItem>
                  </SelectContent>
                </Select>
            </div>

            <!-- Environment Variables Setting -->
            <div class="flex items-center justify-between py-4">
                <div class="space-y-0.5">
                    <Label class="text-base">{{ t('system.envVariables') || '环境变量' }}</Label>
                    <p class="text-sm text-muted-foreground">
                        {{ t('system.envVariablesDesc') || '配置 .sage_env 环境变量文件' }}
                    </p>
                </div>
                <Button 
                    variant="outline" 
                    size="sm"
                    @click="openEnvEditor"
                >
                    <Settings class="w-4 h-4 mr-2" />
                    {{ t('system.configure') || '配置' }}
                </Button>
            </div>

            <!-- Environment Variables Editor Dialog -->
            <Dialog v-model:open="showEnvDialog">
                <DialogContent class="max-w-2xl max-h-[80vh]">
                    <DialogHeader>
                        <DialogTitle>{{ t('system.envVariables') || '环境变量配置' }}</DialogTitle>
                        <DialogDescription>
                            {{ t('system.envVariablesTip') || '每行一个变量，格式: KEY=VALUE' }}
                        </DialogDescription>
                    </DialogHeader>
                    <div class="py-4">
                        <Textarea 
                            v-model="envContent" 
                            class="font-mono text-sm min-h-[300px]"
                            :placeholder="envPlaceholder"
                        />
                    </div>
                    <DialogFooter>
                        <Button variant="outline" @click="showEnvDialog = false">
                            {{ t('common.cancel') || '取消' }}
                        </Button>
                        <Button @click="saveEnvContent" :disabled="savingEnv">
                            {{ savingEnv ? (t('common.saving') || '保存中...') : (t('common.save') || '保存') }}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </Card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useLanguage } from '../utils/i18n'
import { useThemeStore } from '../stores/theme'
import { useUserStore } from '../stores/user'
import { useUpdaterStore } from '../stores/updater'
import { invoke } from '@tauri-apps/api/core'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Textarea } from '@/components/ui/textarea'
import { RefreshCw, Loader2, DownloadCloud, Settings } from 'lucide-vue-next'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { storeToRefs } from 'pinia'
import { toast } from 'vue-sonner'

const { t, language, setLanguage } = useLanguage()
const themeStore = useThemeStore()
const userStore = useUserStore()
const updaterStore = useUpdaterStore()

const {
  currentVersion,
  checking,
  downloading,
  downloadProgress,
  downloadedBytes,
  totalBytes,
  updateStatus
} = storeToRefs(updaterStore)

const showEnvDialog = ref(false)
const envContent = ref('')
const savingEnv = ref(false)
const envPlaceholder = `# SAGE Environment Variables
# Example:
# SAGE_DEFAULT_LLM_API_KEY=sk-xxxxx
# SAGE_DEFAULT_LLM_API_BASE_URL=https://api.deepseek.com/v1
# HTTP_PROXY=http://127.0.0.1:7890
# HTTPS_PROXY=http://127.0.0.1:7890`

const formatBytes = (bytes, decimals = 2) => {
  if (!+bytes) return '0 B'
  const k = 1024
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`
}

const openEnvEditor = async () => {
  try {
    const content = await invoke('get_sage_env_content')
    envContent.value = content || envPlaceholder
    showEnvDialog.value = true
  } catch (error) {
    toast.error(t('system.loadEnvError') || '加载环境变量失败: ' + error)
  }
}

const saveEnvContent = async () => {
  savingEnv.value = true
  try {
    await invoke('save_sage_env_content', { content: envContent.value })
    showEnvDialog.value = false
    toast.success(t('system.envSaved') || '环境变量已保存，重启后生效')
  } catch (error) {
    toast.error(t('system.saveEnvError') || '保存环境变量失败: ' + error)
  } finally {
    savingEnv.value = false
  }
}

const checkForUpdates = () => {
  updaterStore.checkForUpdates()
}

// 用户头像 URL
const userAvatarUrl = computed(() => {
  return userStore.avatarUrl
})

// 随机生成头像
const randomizeAvatar = () => {
  const newSeed = Math.random().toString(36).substring(2, 15)
  userStore.setAvatarSeed(newSeed)
}

onMounted(async () => {
  updaterStore.init()

  // 如果用户没有头像种子，生成一个随机的
  if (!userStore.avatarSeed) {
    randomizeAvatar()
  }
})
</script>
