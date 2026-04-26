<template>
  <div class="h-full overflow-y-auto bg-background">
    <div class="mx-auto flex w-full max-w-4xl flex-col gap-5 px-6 py-5">
      <div class="flex items-end justify-between gap-4 border-b border-border/60 pb-4">
        <div class="space-y-1.5">
          <p class="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/65">
            SAGE
          </p>
          <div class="space-y-0.5">
            <h1 class="text-[1.75rem] font-semibold tracking-tight text-foreground">
              {{ t('system.title') }}
            </h1>
            <p class="max-w-2xl text-[13px] leading-5 text-muted-foreground">
              {{ t('system.subtitle') }}
            </p>
          </div>
        </div>
        <div class="hidden items-center gap-2 rounded-full border border-border/70 bg-muted/25 px-3 py-1.5 text-[11px] text-muted-foreground md:flex">
          <span class="h-2 w-2 rounded-full bg-emerald-500/80" />
          {{ t('system.currentVersion') }}: {{ currentVersion }}
        </div>
      </div>

      <div class="space-y-5">
        <section class="space-y-2">
          <div class="flex items-center gap-2.5">
            <DownloadCloud class="h-3.5 w-3.5 text-muted-foreground" />
            <h2 class="text-[12px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{{ t('system.update') }}</h2>
          </div>

          <div class="overflow-hidden rounded-[18px] border border-border/60 bg-muted/5">
            <div class="flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-center md:justify-between">
              <div class="flex items-center gap-2">
                <p class="text-sm font-medium text-foreground">{{ t('system.updateDesc') }}</p>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button type="button" class="inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground/80 transition-colors hover:text-foreground">
                        <CircleHelp class="h-3.5 w-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{{ t('system.updateIdle') }}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <div class="flex flex-col items-start gap-2 md:items-end">
                <template v-if="downloading">
                  <div class="w-full min-w-[220px] max-w-[260px] space-y-2">
                    <Progress
                      :model-value="totalBytes > 0 ? downloadProgress : 100"
                      class="h-2 bg-background/70"
                      :class="{ 'animate-pulse': totalBytes === 0 }"
                    />
                    <div class="flex justify-between text-[11px] text-muted-foreground">
                      <span>{{ formatBytes(downloadedBytes) }}</span>
                      <span v-if="totalBytes > 0">{{ downloadProgress }}%</span>
                    </div>
                  </div>
                </template>
                <template v-else>
                  <Button
                    variant="outline"
                    size="sm"
                    class="h-8.5 rounded-full border-border/70 bg-background/90 px-3.5 text-[13px] shadow-none hover:bg-muted/30"
                    @click="checkForUpdates"
                    :disabled="checking"
                  >
                    <Loader2 v-if="checking" class="mr-2 h-4 w-4 animate-spin" />
                    <DownloadCloud v-else class="mr-2 h-4 w-4" />
                    {{ checking ? t('system.checking') : t('system.checkNow') }}
                  </Button>
                </template>
              </div>
            </div>
          </div>
        </section>

        <section class="space-y-2">
          <div class="flex items-center gap-2.5">
            <Settings class="h-3.5 w-3.5 text-muted-foreground" />
            <h2 class="text-[12px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{{ t('system.preferences') }}</h2>
          </div>

          <div class="overflow-hidden rounded-[18px] border border-border/60 bg-transparent">
            <div class="flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-center md:justify-between">
              <div class="flex items-center gap-2">
                <Label class="text-sm font-medium">{{ t('system.userAvatar') }}</Label>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button type="button" class="inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground/80 transition-colors hover:text-foreground">
                        <CircleHelp class="h-3.5 w-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{{ t('system.userAvatarDesc') }}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <div class="flex items-center gap-3">
                <img
                  :src="userAvatarUrl"
                  alt="User Avatar"
                  class="h-10 w-10 rounded-full border border-border/70 bg-muted/40 object-cover"
                />
                <Button
                  variant="outline"
                  size="sm"
                  class="h-8.5 rounded-full border-border/70 bg-background/90 px-3.5 text-[13px] shadow-none hover:bg-muted/30"
                  @click="randomizeAvatar"
                  :title="t('system.randomAvatar')"
                >
                  <RefreshCw class="mr-2 h-4 w-4" />
                  {{ t('system.random') }}
                </Button>
              </div>
            </div>

            <div class="h-px bg-border/60" />

            <div class="flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-center md:justify-between">
              <div class="flex items-center gap-2">
                <Label class="text-sm font-medium">{{ t('sidebar.language') }}</Label>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button type="button" class="inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground/80 transition-colors hover:text-foreground">
                        <CircleHelp class="h-3.5 w-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{{ t('system.languageDesc') }}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <Select :model-value="language" @update:model-value="setLanguage">
                <SelectTrigger class="h-9 w-full rounded-full border-border/70 bg-background/90 px-3.5 text-[13px] shadow-none md:w-[170px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="zhCN">{{ t('system.languageOptionZhCN') }}</SelectItem>
                  <SelectItem value="enUS">{{ t('system.languageOptionEnUS') }}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div class="h-px bg-border/60" />

            <div class="flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-center md:justify-between">
              <div class="flex items-center gap-2">
                <Label class="text-sm font-medium">{{ t('sidebar.theme') }}</Label>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button type="button" class="inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground/80 transition-colors hover:text-foreground">
                        <CircleHelp class="h-3.5 w-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{{ t('system.themeDesc') }}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <Select :model-value="themeStore.theme" @update:model-value="themeStore.setTheme">
                <SelectTrigger class="h-9 w-full rounded-full border-border/70 bg-background/90 px-3.5 text-[13px] shadow-none md:w-[170px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="light">{{ t('sidebar.themeLight') }}</SelectItem>
                  <SelectItem value="dark">{{ t('sidebar.themeDark') }}</SelectItem>
                  <SelectItem value="system">{{ t('sidebar.themeSystem') }}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </section>

        <section class="space-y-2">
          <div class="flex items-center gap-2.5">
            <Settings class="h-3.5 w-3.5 text-muted-foreground" />
            <h2 class="text-[12px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{{ t('system.environment') }}</h2>
          </div>

          <div class="overflow-hidden rounded-[18px] border border-border/60 bg-transparent">
            <div class="flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-center md:justify-between">
              <div class="flex items-center gap-2">
                <Label class="text-sm font-medium">{{ t('system.importOpenclaw') }}</Label>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button type="button" class="inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground/80 transition-colors hover:text-foreground">
                        <CircleHelp class="h-3.5 w-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{{ t('system.importOpenclawDesc') }}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <Button
                variant="outline"
                size="sm"
                class="h-8.5 rounded-full border-border/70 bg-background/90 px-3.5 text-[13px] shadow-none hover:bg-muted/30"
                @click="handleImportOpenclaw"
                :disabled="importingOpenclaw"
              >
                <Loader2 v-if="importingOpenclaw" class="mr-2 h-4 w-4 animate-spin" />
                <DownloadCloud v-else class="mr-2 h-4 w-4" />
                {{ importingOpenclaw ? t('system.importingOpenclaw') : t('system.importOpenclawAction') }}
              </Button>
            </div>

            <div class="h-px bg-border/60" />

            <div class="flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-center md:justify-between">
              <div class="flex items-center gap-2">
                <Label class="text-sm font-medium">{{ t('system.envVariables') }}</Label>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button type="button" class="inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground/80 transition-colors hover:text-foreground">
                        <CircleHelp class="h-3.5 w-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{{ t('system.envVariablesDesc') }}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <div class="flex items-center gap-2.5">
                <span class="hidden text-[11px] text-muted-foreground md:inline">{{ envVarsSummary }}</span>
                <Button
                  variant="outline"
                  size="sm"
                  class="h-8.5 rounded-full border-border/70 bg-background/90 px-3.5 text-[13px] shadow-none hover:bg-muted/30"
                  @click="openEnvEditor"
                >
                  <Settings class="mr-2 h-4 w-4" />
                  {{ t('system.configure') }}
                </Button>
              </div>
            </div>
          </div>
        </section>

        <section class="space-y-2">
          <div class="flex items-center gap-2.5">
            <Globe class="h-3.5 w-3.5 text-muted-foreground" />
            <h2 class="text-[12px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{{ t('system.browserIntegration') }}</h2>
          </div>

          <div class="overflow-hidden rounded-[18px] border border-border/60 bg-transparent">
              <div class="flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-center md:justify-between">
                <div class="space-y-1">
                <p class="text-sm font-medium text-foreground">{{ t('system.installBrowserPlugin') }}</p>
                <p class="text-[12px] leading-5 text-muted-foreground">
                  {{ t('system.browserPluginDesc') }}
                </p>
              </div>
              <div class="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  class="h-8.5 rounded-full border-border/70 bg-background/90 px-3.5 text-[13px] shadow-none hover:bg-muted/30"
                  @click="openChromeExtensionsPage"
                >
                  {{ t('system.openExtensionPage') }}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  class="h-8.5 rounded-full border-border/70 bg-background/90 px-3.5 text-[13px] shadow-none hover:bg-muted/30"
                  @click="openExtensionDirectory"
                >
                  {{ t('system.openExtensionDirectory') }}
                </Button>
              </div>
            </div>

            <div class="h-px bg-border/60" />

            <div class="flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-center md:justify-between">
              <div class="space-y-1">
                <p class="text-sm font-medium text-foreground">{{ t('system.connectionStatus') }}</p>
                <p class="text-[12px] leading-5 text-muted-foreground">
                  {{ browserBridgeStatusText }}
                </p>
                <p v-if="browserBridgeLastSeenText" class="text-[11px] text-muted-foreground/80">
                  {{ t('system.browserLastSeen', { time: browserBridgeLastSeenText }) }}
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                class="h-8.5 rounded-full border-border/70 bg-background/90 px-3.5 text-[13px] shadow-none hover:bg-muted/30"
                :disabled="checkingBrowserBridge"
                @click="checkBrowserBridgeStatus"
              >
                <Loader2 v-if="checkingBrowserBridge" class="mr-2 h-4 w-4 animate-spin" />
                <RefreshCw v-else class="mr-2 h-4 w-4" />
                {{ t('system.recheck') }}
              </Button>
            </div>
          </div>
        </section>
      </div>

            <!-- Environment Variables Editor Dialog -->
            <Dialog v-model:open="showEnvDialog">
                <DialogContent class="max-w-3xl h-[85vh] flex flex-col p-0">
                    <DialogHeader class="px-6 pt-6 pb-4 shrink-0">
                        <DialogTitle>{{ t('system.envDialogTitle') }}</DialogTitle>
                        <DialogDescription>
                            {{ t('system.envDialogDesc') }}
                        </DialogDescription>
                    </DialogHeader>
                    
                    <!-- Scrollable Content Area -->
                    <div class="flex-1 overflow-y-auto px-6 pb-4 min-h-0">
                        <!-- Alert for restart requirement -->
                        <Alert variant="warning" class="mb-4">
                            <AlertCircle class="h-4 w-4" />
                            <AlertTitle>{{ t('system.restartRequiredTitle') }}</AlertTitle>
                            <AlertDescription>
                                {{ t('system.restartRequiredDesc') }}
                            </AlertDescription>
                        </Alert>

                        <!-- Preset Environment Variables -->
                        <div class="mb-4">
                            <div class="flex items-center justify-between mb-2">
                                <Label class="text-sm font-medium">{{ t('system.presetEnvVars') }}</Label>
                                <span class="text-xs text-muted-foreground">{{ t('system.clickToAdd') }}</span>
                            </div>
                            <div class="flex flex-wrap gap-2">
                                <Button
                                    v-for="preset in localizedPresetEnvVars"
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
                                <p>{{ t('system.noEnvVars') }}</p>
                                <p class="text-sm">{{ t('system.addEnvVarHint') }}</p>
                            </div>
                            
                            <div
                                v-for="(envVar, index) in envVars"
                                :key="index"
                                class="flex items-start gap-2 p-3 border rounded-lg bg-muted/30"
                            >
                                <div class="flex-1 grid grid-cols-[1fr,1fr] gap-2">
                                    <div class="space-y-1">
                                        <Label class="text-xs text-muted-foreground">{{ t('system.envKey') }}</Label>
                                        <Input
                                            v-model="envVar.key"
                                            :placeholder="t('system.envKeyPlaceholder')"
                                            class="font-mono text-sm"
                                        />
                                    </div>
                                    <div class="space-y-1">
                                        <Label class="text-xs text-muted-foreground">{{ t('system.envValue') }}</Label>
                                        <Input
                                            v-model="envVar.value"
                                            :type="envVar.showValue ? 'text' : 'password'"
                                            :placeholder="t('system.envValuePlaceholder')"
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
                                        :title="envVar.showValue ? t('system.hide') : t('system.show')"
                                    >
                                        <Eye v-if="envVar.showValue" class="w-4 h-4" />
                                        <EyeOff v-else class="w-4 h-4" />
                                    </Button>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        class="h-8 w-8 text-destructive hover:text-destructive"
                                        @click="removeEnvVar(index)"
                                        :title="t('system.delete')"
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
                            {{ t('system.addEnvVar') }}
                        </Button>
                    </div>

                    <DialogFooter class="px-6 py-4 border-t shrink-0">
                        <Button variant="outline" @click="showEnvDialog = false">
                            {{ t('common.cancel') }}
                        </Button>
                        <Button @click="saveEnvContent" :disabled="savingEnv">
                            {{ savingEnv ? t('common.saving') : t('common.save') }}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <!-- Restart Confirmation Dialog -->
            <Dialog v-model:open="showRestartDialog">
                <DialogContent class="max-w-md">
                    <DialogHeader>
                        <DialogTitle>{{ t('system.savedSuccessfully') }}</DialogTitle>
                        <DialogDescription>
                            {{ t('system.envVariablesSavedRestart') }}
                        </DialogDescription>
                    </DialogHeader>
                    <DialogFooter class="mt-4">
                        <Button variant="outline" @click="showRestartDialog = false">
                            {{ t('system.restartLater') }}
                        </Button>
                        <Button @click="restartApp" variant="default">
                            <RotateCcw class="w-4 h-4 mr-2" />
                            {{ t('system.restartNow') }}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useLanguage } from '../utils/i18n'
import { useThemeStore } from '../stores/theme'
import { useUserStore } from '../stores/user'
import { useUpdaterStore } from '../stores/updater'
import { agentAPI } from '../api/agent.js'
import request from '../utils/request.js'
import { invoke } from '@tauri-apps/api/core'
import { relaunch } from '@tauri-apps/plugin-process'
import { open } from '@tauri-apps/plugin-shell'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Input } from '@/components/ui/input'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import { RefreshCw, Loader2, DownloadCloud, Settings, Plus, Trash2, Eye, EyeOff, AlertCircle, RotateCcw, CircleHelp, Globe } from 'lucide-vue-next'
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
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
const importingOpenclaw = ref(false)
const checkingBrowserBridge = ref(false)
const browserBridgeStatus = ref(null)
const browserBridgeLastSeenAt = ref(null)

// 预设环境变量列表 - 只包含系统实际使用的
const presetEnvVars = [
    // 搜索引擎 API Keys (MCP Search Server 使用)
    { key: 'SERPAPI_API_KEY', descriptionKey: 'system.presetEnvVar.search.serpapi', category: 'search' },
    { key: 'SERPER_API_KEY', descriptionKey: 'system.presetEnvVar.search.serper', category: 'search' },
    { key: 'TAVILY_API_KEY', descriptionKey: 'system.presetEnvVar.search.tavily', category: 'search' },
    { key: 'BRAVE_API_KEY', descriptionKey: 'system.presetEnvVar.search.brave', category: 'search' },
    { key: 'ZHIPU_API_KEY', descriptionKey: 'system.presetEnvVar.search.zhipu', category: 'search' },
    { key: 'BOCHA_API_KEY', descriptionKey: 'system.presetEnvVar.search.bocha', category: 'search' },
    { key: 'SHUYAN_API_KEY', descriptionKey: 'system.presetEnvVar.search.shuyan', category: 'search' },
    // 图片生成 API Keys (Unified Image Generation Server 使用)
    { key: 'MINIMAX_API_KEY', descriptionKey: 'system.presetEnvVar.image.minimaxApiKey', category: 'image' },
    { key: 'MINIMAX_MODEL', descriptionKey: 'system.presetEnvVar.image.minimaxModel', category: 'image' },
    { key: 'QWEN_API_KEY', descriptionKey: 'system.presetEnvVar.image.qwenApiKey', category: 'image' },
    { key: 'QWEN_MODEL', descriptionKey: 'system.presetEnvVar.image.qwenModel', category: 'image' },
    { key: 'SEEDREAM_API_KEY', descriptionKey: 'system.presetEnvVar.image.seedreamApiKey', category: 'image' },
    { key: 'SEEDREAM_MODEL', descriptionKey: 'system.presetEnvVar.image.seedreamModel', category: 'image' },
    // 代理设置 (Tauri 读取用于系统代理配置)
    { key: 'HTTP_PROXY', descriptionKey: 'system.presetEnvVar.proxy.http', category: 'proxy' },
    { key: 'HTTPS_PROXY', descriptionKey: 'system.presetEnvVar.proxy.https', category: 'proxy' },
    { key: 'ALL_PROXY', descriptionKey: 'system.presetEnvVar.proxy.all', category: 'proxy' },
]

const localizedPresetEnvVars = computed(() => presetEnvVars.map((preset) => ({
  ...preset,
  description: t(preset.descriptionKey),
})))

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
    await loadEnvVarsPreview()
    showEnvDialog.value = true
  } catch (error) {
    toast.error(t('system.loadEnvErrorDetail', { message: error.message || error }))
  }
}

const addEmptyEnvVar = () => {
    envVars.value.push({ key: '', value: '', showValue: false })
}

const addPresetEnvVar = (preset) => {
    // 检查是否已存在
    const exists = envVars.value.some(v => v.key === preset.key)
    if (exists) {
        toast.info(t('system.envVarExists'))
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
    await loadEnvVarsPreview()
    showEnvDialog.value = false
    showRestartDialog.value = true
  } catch (error) {
    toast.error(t('system.saveEnvErrorDetail', { message: error.message || error }))
  } finally {
    savingEnv.value = false
  }
}

const restartApp = async () => {
    try {
        await relaunch()
    } catch (error) {
        toast.error(t('system.restartErrorDetail', { message: error.message || error }))
    }
}

const checkForUpdates = () => {
  updaterStore.checkForUpdates()
}

const handleImportOpenclaw = async () => {
  importingOpenclaw.value = true
  try {
    const result = await agentAPI.importOpenclaw()
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('agents-updated', {
        detail: {
          source: 'import-openclaw',
          agentId: result?.agent_id || null
        }
      }))
    }
    const agentName = result?.agent_name || t('system.openclawDefaultAgentName')
    const skillCount = result?.linked_skill_count || 0
    if (skillCount > 0) {
      toast.success(
        t('system.importOpenclawSuccessWithSkills', {
          agent: agentName,
          count: skillCount
        })
      )
    } else {
      toast.success(
        t('system.importOpenclawSuccessNoSkills', {
          agent: agentName
        })
      )
    }
  } catch (error) {
    toast.error(`${t('system.importOpenclawError')}: ${error.message || error}`)
  } finally {
    importingOpenclaw.value = false
  }
}

// 用户头像 URL
const userAvatarUrl = computed(() => {
  return userStore.avatarUrl
})

const envVarsSummary = computed(() => {
  if (envVars.value.length === 0) {
    return t('system.noEnvVars')
  }
  return t('system.envVariablesSummary', { count: envVars.value.length })
})

const browserBridgeStatusText = computed(() => {
  if (!browserBridgeStatus.value) return t('system.browserStatusUnknown')
  const connected = !!browserBridgeStatus.value.connected
  if (!connected) return t('system.browserStatusDisconnected')
  const extensionId = browserBridgeStatus.value.extension_id || 'unknown'
  return t('system.browserStatusConnected', { extensionId })
})

const browserBridgeLastSeenText = computed(() => {
  if (!browserBridgeLastSeenAt.value) return ''
  const date = new Date(Number(browserBridgeLastSeenAt.value) * 1000)
  if (Number.isNaN(date.getTime())) return ''
  const locale = language.value === 'zhCN' ? 'zh-CN' : 'en-US'
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
})

const loadEnvVarsPreview = async () => {
  const content = await invoke('get_sage_env_content')
  envVars.value = parseEnvContent(content || '')
}

const checkBrowserBridgeStatus = async ({ probe = true } = {}) => {
  checkingBrowserBridge.value = true
  try {
    // 主动 ping 扩展，扩展挂了会在 timeout 后强制返回 offline，避免被陈旧心跳误导
    const data = probe
      ? await request.post('/api/browser-extension/probe?timeout=5')
      : await request.get('/api/browser-extension/status')
    browserBridgeStatus.value = data || null
    browserBridgeLastSeenAt.value = data?.last_seen_at || null
    if (probe && data?.probe?.timed_out) {
      toast.warning(t('system.browserBridgeOfflineWarning'))
    }
  } catch (error) {
    browserBridgeStatus.value = null
    browserBridgeLastSeenAt.value = null
    toast.error(t('system.browserBridgeCheckError', { message: error.message || error }))
  } finally {
    checkingBrowserBridge.value = false
  }
}

const openChromeExtensionsPage = async () => {
  try {
    await invoke('open_chrome_extensions_page')
  } catch (error) {
    toast.error(t('system.openChromeExtensionsPageError', { message: error.message || error }))
  }
}

const openExtensionDirectory = async () => {
  try {
    const extensionDir = await invoke('get_chrome_extension_dir')
    if (!extensionDir) {
      throw new Error(t('system.extensionDirectoryNotFound'))
    }
    await open(extensionDir)
    toast.success(t('system.openExtensionDirectorySuccess', { path: extensionDir }))
  } catch (error) {
    toast.error(t('system.openExtensionDirectoryError', { message: error.message || error }))
  }
}

// 随机生成头像
const randomizeAvatar = () => {
  const newSeed = Math.random().toString(36).substring(2, 15)
  userStore.setAvatarSeed(newSeed)
}

onMounted(async () => {
  updaterStore.init()

  try {
    await loadEnvVarsPreview()
  } catch {
    envVars.value = []
  }

  // 如果用户没有头像种子，生成一个随机的
  if (!userStore.avatarSeed) {
    randomizeAvatar()
  }
  // 启动时先用快路径（不主动 ping，免得每次开页面都阻塞 5s）
  await checkBrowserBridgeStatus({ probe: false })
})
</script>
