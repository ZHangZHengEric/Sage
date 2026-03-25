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
                <DialogContent class="max-w-3xl h-[85vh] flex flex-col p-0">
                    <DialogHeader class="px-6 pt-6 pb-4 shrink-0">
                        <DialogTitle>{{ t('system.envVariables') || '环境变量配置' }}</DialogTitle>
                        <DialogDescription>
                            {{ t('system.envVariablesTip') || '管理您的环境变量，配置完成后需要重启 Sage 才能生效' }}
                        </DialogDescription>
                    </DialogHeader>
                    
                    <!-- Scrollable Content Area -->
                    <div class="flex-1 overflow-y-auto px-6 pb-4 min-h-0">
                        <!-- Alert for restart requirement -->
                        <Alert variant="warning" class="mb-4">
                            <AlertCircle class="h-4 w-4" />
                            <AlertTitle>{{ t('system.restartRequired') || '需要重启' }}</AlertTitle>
                            <AlertDescription>
                                {{ t('system.restartRequiredDesc') || '环境变量修改后需要重启 Sage 才能生效' }}
                            </AlertDescription>
                        </Alert>

                        <!-- Preset Environment Variables -->
                        <div class="mb-4">
                            <div class="flex items-center justify-between mb-2">
                                <Label class="text-sm font-medium">{{ t('system.presetEnvVars') || '预设环境变量' }}</Label>
                                <span class="text-xs text-muted-foreground">{{ t('system.clickToAdd') || '点击快速添加' }}</span>
                            </div>
                            <div class="flex flex-wrap gap-2">
                                <Button
                                    v-for="preset in presetEnvVars"
                                    :key="preset.key"
                                    variant="outline"
                                    size="sm"
                                    class="text-xs"
                                    @click="addPresetEnvVar(preset)"
                                    :title="preset.description"
                                >
                                    <Plus class="w-3 h-3 mr-1" />
                                    {{ preset.key }}
                                </Button>
                            </div>
                        </div>

                        <!-- Environment Variables List -->
                        <div class="space-y-3 py-2">
                            <div v-if="envVars.length === 0" class="text-center py-8 text-muted-foreground">
                                <Settings class="w-12 h-12 mx-auto mb-2 opacity-50" />
                                <p>{{ t('system.noEnvVars') || '暂无环境变量' }}</p>
                                <p class="text-sm">{{ t('system.addEnvVarHint') || '点击上方预设按钮或手动添加' }}</p>
                            </div>
                            
                            <div
                                v-for="(envVar, index) in envVars"
                                :key="index"
                                class="flex items-start gap-2 p-3 border rounded-lg bg-muted/30"
                            >
                                <div class="flex-1 grid grid-cols-[1fr,1fr] gap-2">
                                    <div class="space-y-1">
                                        <Label class="text-xs text-muted-foreground">{{ t('system.envKey') || '变量名' }}</Label>
                                        <Input
                                            v-model="envVar.key"
                                            placeholder="KEY_NAME"
                                            class="font-mono text-sm"
                                        />
                                    </div>
                                    <div class="space-y-1">
                                        <Label class="text-xs text-muted-foreground">{{ t('system.envValue') || '变量值' }}</Label>
                                        <Input
                                            v-model="envVar.value"
                                            :type="envVar.showValue ? 'text' : 'password'"
                                            placeholder="value"
                                            class="font-mono text-sm"
                                        />
                                    </div>
                                </div>
                                <div class="flex items-center gap-1 pt-6">
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        class="h-8 w-8"
                                        @click="envVar.showValue = !envVar.showValue"
                                        :title="envVar.showValue ? (t('system.hide') || '隐藏') : (t('system.show') || '显示')"
                                    >
                                        <Eye v-if="envVar.showValue" class="w-4 h-4" />
                                        <EyeOff v-else class="w-4 h-4" />
                                    </Button>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        class="h-8 w-8 text-destructive hover:text-destructive"
                                        @click="removeEnvVar(index)"
                                        :title="t('common.delete') || '删除'"
                                    >
                                        <Trash2 class="w-4 h-4" />
                                    </Button>
                                </div>
                            </div>
                        </div>

                        <!-- Add Button -->
                        <Button
                            variant="outline"
                            class="w-full mt-3"
                            @click="addEmptyEnvVar"
                        >
                            <Plus class="w-4 h-4 mr-2" />
                            {{ t('system.addEnvVar') || '添加环境变量' }}
                        </Button>
                    </div>

                    <DialogFooter class="px-6 py-4 border-t shrink-0">
                        <Button variant="outline" @click="showEnvDialog = false">
                            {{ t('common.cancel') || '取消' }}
                        </Button>
                        <Button @click="saveEnvContent" :disabled="savingEnv">
                            {{ savingEnv ? (t('common.saving') || '保存中...') : (t('common.save') || '保存') }}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <!-- Restart Confirmation Dialog -->
            <Dialog v-model:open="showRestartDialog">
                <DialogContent class="max-w-md">
                    <DialogHeader>
                        <DialogTitle>{{ t('system.restartConfirmTitle') || '保存成功' }}</DialogTitle>
                        <DialogDescription>
                            {{ t('system.restartConfirmDesc') || '环境变量已保存，需要重启 Sage 才能生效。是否立即重启？' }}
                        </DialogDescription>
                    </DialogHeader>
                    <DialogFooter class="mt-4">
                        <Button variant="outline" @click="showRestartDialog = false">
                            {{ t('system.restartLater') || '稍后重启' }}
                        </Button>
                        <Button @click="restartApp" variant="default">
                            <RotateCcw class="w-4 h-4 mr-2" />
                            {{ t('system.restartNow') || '立即重启' }}
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
import { relaunch } from '@tauri-apps/plugin-process'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Input } from '@/components/ui/input'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import { RefreshCw, Loader2, DownloadCloud, Settings, Plus, Trash2, Eye, EyeOff, AlertCircle, RotateCcw } from 'lucide-vue-next'
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
const showRestartDialog = ref(false)
const envVars = ref([])
const savingEnv = ref(false)

// 预设环境变量列表 - 只包含系统实际使用的
const presetEnvVars = [
    // 搜索引擎 API Keys (MCP Search Server 使用)
    { key: 'SERPAPI_API_KEY', description: 'SerpApi Google搜索 (searchapi.io)', category: 'search' },
    { key: 'SERPER_API_KEY', description: 'Serper Google搜索 (serper.dev)', category: 'search' },
    { key: 'TAVILY_API_KEY', description: 'Tavily搜索 (tavily.com)', category: 'search' },
    { key: 'BRAVE_API_KEY', description: 'Brave搜索 (brave.com/search/api)', category: 'search' },
    { key: 'ZHIPU_API_KEY', description: '智谱AI搜索 (bigmodel.cn)', category: 'search' },
    { key: 'BOCHA_API_KEY', description: '博查搜索 (bochaai.com)', category: 'search' },
    { key: 'SHUYAN_API_KEY', description: '数眼搜索 (shuyanai.com)', category: 'search' },
    // 图片生成 API Keys (Unified Image Generation Server 使用)
    { key: 'MINIMAX_API_KEY', description: 'Minimax(海螺AI)图片生成 API Key (platform.minimaxi.com)', category: 'image' },
    { key: 'MINIMAX_MODEL', description: 'Minimax图片生成模型 (如: image-01)', category: 'image' },
    { key: 'QWEN_API_KEY', description: '阿里云百炼图片生成 API Key (bailian.console.aliyun.com)', category: 'image' },
    { key: 'QWEN_MODEL', description: '阿里云图片生成模型 (如: wanx2.1-t2i-plus)', category: 'image' },
    { key: 'SEEDREAM_API_KEY', description: '火山引擎Seedream图片生成 API Key (console.volcengine.com/ark)', category: 'image' },
    { key: 'SEEDREAM_MODEL', description: 'Seedream图片生成模型 (如: doubao-seedream-5.0-lite)', category: 'image' },
    // 代理设置 (Tauri 读取用于系统代理配置)
    { key: 'HTTP_PROXY', description: 'HTTP代理地址 (如: http://127.0.0.1:7890)', category: 'proxy' },
    { key: 'HTTPS_PROXY', description: 'HTTPS代理地址 (如: http://127.0.0.1:7890)', category: 'proxy' },
    { key: 'ALL_PROXY', description: '全局代理地址 (SOCKS5 等)', category: 'proxy' },
]

const formatBytes = (bytes, decimals = 2) => {
  if (!+bytes) return '0 B'
  const k = 1024
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`
}

// 解析环境变量内容为对象数组
const parseEnvContent = (content) => {
    const vars = []
    const lines = content.split('\n')
    for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed || trimmed.startsWith('#')) continue
        const equalIndex = trimmed.indexOf('=')
        if (equalIndex > 0) {
            const key = trimmed.substring(0, equalIndex).trim()
            const value = trimmed.substring(equalIndex + 1).trim()
            if (key) {
                vars.push({ key, value, showValue: false })
            }
        }
    }
    return vars
}

// 将对象数组转换为环境变量内容
const stringifyEnvVars = (vars) => {
    const lines = vars
        .filter(v => v.key.trim())
        .map(v => `${v.key.trim()}=${v.value}`)
    return lines.join('\n')
}

const openEnvEditor = async () => {
  try {
    const content = await invoke('get_sage_env_content')
    envVars.value = parseEnvContent(content || '')
    showEnvDialog.value = true
  } catch (error) {
    toast.error(t('system.loadEnvError') || '加载环境变量失败: ' + error)
  }
}

const addEmptyEnvVar = () => {
    envVars.value.push({ key: '', value: '', showValue: false })
}

const addPresetEnvVar = (preset) => {
    // 检查是否已存在
    const exists = envVars.value.some(v => v.key === preset.key)
    if (exists) {
        toast.info(t('system.envVarExists') || '该环境变量已存在')
        return
    }
    envVars.value.push({ key: preset.key, value: '', showValue: false })
}

const removeEnvVar = (index) => {
    envVars.value.splice(index, 1)
}

const saveEnvContent = async () => {
  savingEnv.value = true
  try {
    const content = stringifyEnvVars(envVars.value)
    await invoke('save_sage_env_content', { content })
    showEnvDialog.value = false
    showRestartDialog.value = true
  } catch (error) {
    toast.error(t('system.saveEnvError') || '保存环境变量失败: ' + error)
  } finally {
    savingEnv.value = false
  }
}

const restartApp = async () => {
    try {
        await relaunch()
    } catch (error) {
        toast.error(t('system.restartError') || '重启失败: ' + error)
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
