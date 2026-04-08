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
                  <SelectItem value="zhCN">简体中文</SelectItem>
                  <SelectItem value="enUS">English</SelectItem>
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
            <h2 class="text-[12px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">浏览器集成</h2>
          </div>

          <div class="overflow-hidden rounded-[18px] border border-border/60 bg-transparent">
            <div class="flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-center md:justify-between">
              <div class="space-y-1">
                <p class="text-sm font-medium text-foreground">安装 Sage Chrome 插件</p>
                <p class="text-[12px] leading-5 text-muted-foreground">
                  点击后会打开 Chrome 扩展页。请在扩展页开启开发者模式，并“加载已解压的扩展程序”指向本地插件目录。
                </p>
              </div>
              <div class="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  class="h-8.5 rounded-full border-border/70 bg-background/90 px-3.5 text-[13px] shadow-none hover:bg-muted/30"
                  @click="openChromeExtensionsPage"
                >
                  打开扩展页
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  class="h-8.5 rounded-full border-border/70 bg-background/90 px-3.5 text-[13px] shadow-none hover:bg-muted/30"
                  @click="openExtensionDirectory"
                >
                  打开插件目录
                </Button>
              </div>
            </div>

            <div class="h-px bg-border/60" />

            <div class="flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-center md:justify-between">
              <div class="space-y-1">
                <p class="text-sm font-medium text-foreground">连接状态</p>
                <p class="text-[12px] leading-5 text-muted-foreground">
                  {{ browserBridgeStatusText }}
                </p>
                <p v-if="browserBridgeLastSeenText" class="text-[11px] text-muted-foreground/80">
                  最近心跳：{{ browserBridgeLastSeenText }}
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
                重新检测
              </Button>
            </div>
          </div>
        </section>
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
    await loadEnvVarsPreview()
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
    await loadEnvVarsPreview()
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
    const agentName = result?.agent_name || 'openclaw的小龙虾'
    const skillCount = result?.linked_skill_count || 0
    if (skillCount > 0) {
      toast.success(
        t('system.importOpenclawSuccessWithSkills', {
          agent: agentName,
          count: skillCount
        }) || `${agentName} 导入成功，已关联 ${skillCount} 个 skills`
      )
    } else {
      toast.success(
        t('system.importOpenclawSuccessNoSkills', {
          agent: agentName
        }) || `${agentName} 导入成功，已导入 workspace，未发现可关联的 skills`
      )
    }
  } catch (error) {
    toast.error((t('system.importOpenclawError') || '导入 OpenClaw 失败') + ': ' + (error.message || error))
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
    return t('system.noEnvVars') || '尚未配置'
  }
  return `${envVars.value.length} ${t('system.envVariables') || '项已配置'}`
})

const browserBridgeStatusText = computed(() => {
  if (!browserBridgeStatus.value) return '尚未检测浏览器插件状态'
  const connected = !!browserBridgeStatus.value.connected
  if (!connected) return '未连接：请先在 Chrome 安装并打开 Sage 插件侧边栏'
  const extensionId = browserBridgeStatus.value.extension_id || 'unknown'
  return `已连接（扩展 ID: ${extensionId}）`
})

const browserBridgeLastSeenText = computed(() => {
  if (!browserBridgeLastSeenAt.value) return ''
  const date = new Date(Number(browserBridgeLastSeenAt.value) * 1000)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString()
})

const loadEnvVarsPreview = async () => {
  const content = await invoke('get_sage_env_content')
  envVars.value = parseEnvContent(content || '')
}

const checkBrowserBridgeStatus = async () => {
  checkingBrowserBridge.value = true
  try {
    const data = await request.get('/api/browser-extension/status')
    browserBridgeStatus.value = data || null
    browserBridgeLastSeenAt.value = data?.last_seen_at || null
  } catch (error) {
    browserBridgeStatus.value = null
    browserBridgeLastSeenAt.value = null
    toast.error('检测浏览器插件状态失败: ' + (error.message || error))
  } finally {
    checkingBrowserBridge.value = false
  }
}

const openChromeExtensionsPage = async () => {
  try {
    await invoke('open_chrome_extensions_page')
  } catch (error) {
    toast.error('打开 Chrome 扩展页失败: ' + (error.message || error))
  }
}

const openExtensionDirectory = async () => {
  try {
    const extensionDir = await invoke('get_chrome_extension_dir')
    if (!extensionDir) {
      throw new Error('插件目录未找到')
    }
    await open(extensionDir)
    toast.success(`已打开插件目录：${extensionDir}`)
  } catch (error) {
    toast.error('打开插件目录失败: ' + (error.message || error))
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
  await checkBrowserBridgeStatus()
})
</script>
