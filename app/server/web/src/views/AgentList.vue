<template>
  <div class="h-full w-full overflow-hidden flex flex-col">
    <!-- List View -->
    <div v-if="currentView === 'list'" class="flex-1 overflow-y-auto p-6 space-y-6 animate-in fade-in duration-500">
      <div class="flex justify-end gap-3">
        <Button variant="outline" @click="handleImport">
          <Download class="mr-2 h-4 w-4" />
          {{ t('agent.import') }}
        </Button>
        <Button @click="handleCreateAgent">
          <Plus class="mr-2 h-4 w-4" />
          {{ t('agent.create') }}
        </Button>
      </div>

      <div v-if="loading" class="flex flex-col items-center justify-center py-20">
        <Loader class="h-8 w-8 animate-spin text-primary" />
      </div>
      <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
        <Card
          v-for="agent in agents"
          :key="agent.id"
          class="flex flex-col h-full border hover:border-primary/30 transition-colors bg-card cursor-pointer"
          @click="handleViewAgent(agent)"
        >
          <CardHeader class="pb-2 pt-4">
            <div class="flex items-start gap-3">
              <img
                :src="getAgentAvatar(agent.id)"
                :alt="agent.name"
                class="h-12 w-12 rounded-xl bg-primary/10 object-cover shrink-0"
              />

              <div class="flex-1 min-w-0">
                <div class="flex items-start justify-between gap-2">
                  <CardTitle class="text-base font-bold leading-tight truncate" :title="agent.name">
                    {{ agent.name }}
                  </CardTitle>
                  <Badge
                    v-if="agent.is_default"
                    variant="default"
                    class="text-xs font-medium px-2 py-0.5 shrink-0 bg-primary text-primary-foreground"
                  >
                    <Star class="w-3 h-3 mr-1" />
                    默认
                  </Badge>
                </div>

                <div class="flex items-center gap-1 mt-1">
                  <button
                    @click.stop="copyAgentId(agent.id)"
                    class="text-[10px] font-mono text-muted-foreground/70 bg-muted/40 hover:bg-muted/60 px-1.5 py-0.5 rounded transition-colors cursor-pointer flex items-center gap-1"
                    title="点击复制完整ID"
                  >
                    <span class="truncate max-w-[120px]">{{ agent.id }}</span>
                    <Copy class="w-3 h-3" />
                  </button>
                </div>
              </div>
            </div>
          </CardHeader>
          
          <CardContent class="pt-0 pb-3 flex-1 flex flex-col">
            <p class="text-sm text-muted-foreground line-clamp-3 leading-relaxed flex-1">
              {{ agent.description || '这个智能体已经准备好协助完成你的任务。' }}
            </p>
            
            <div class="flex items-center gap-3 mt-3 flex-wrap">
              <Badge variant="outline" class="text-xs font-medium px-2 py-0.5 shrink-0">
                {{ getAgentModeText(agent.agentMode) }}
              </Badge>
              <Badge :variant="getConfigBadgeVariant(agent.deepThinking)" class="text-xs font-medium px-2 py-0.5 shrink-0">
                {{ getConfigBadgeText(agent.deepThinking) }}
              </Badge>
              <span class="text-xs text-muted-foreground truncate" :title="getModelLabel(agent.llm_provider_id)">
                {{ getModelLabel(agent.llm_provider_id) }}
              </span>
            </div>
          </CardContent>

          <CardFooter class="pt-0 pb-4 px-4 flex-col items-stretch gap-3">
            <div class="flex items-center justify-between w-full">
              <div class="flex items-center gap-3">
                <div v-if="agent.availableTools?.length" class="flex items-center gap-1 text-muted-foreground">
                  <Wrench class="w-3.5 h-3.5" />
                  <span class="text-xs">{{ agent.availableTools.length }}</span>
                </div>
                <div v-if="agent.availableSkills?.length" class="flex items-center gap-1 text-muted-foreground">
                  <Zap class="w-3.5 h-3.5" />
                  <span class="text-xs">{{ agent.availableSkills.length }}</span>
                </div>
              </div>
              <span class="text-xs text-muted-foreground/50">点击查看详情</span>
            </div>

            <div class="pt-3 border-t bg-muted/20 -mx-4 px-4 -mb-4 pb-4 flex flex-wrap gap-2 justify-end">
            <Button variant="ghost" size="icon" @click.stop="openUsageModal(agent)" :title="t('agent.usage')">
              <FileBraces class="h-4 w-4" />
            </Button>
            <Button v-if="canEdit(agent)" variant="ghost" size="icon" @click.stop="handleEditAgent(agent)" :title="t('agent.edit')">
              <Edit class="h-4 w-4" />
            </Button>
            <Button v-if="canEdit(agent)" variant="ghost" size="icon" @click.stop="handleAuthorize(agent)" :title="t('agent.authorize')">
              <UserPlus class="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon" @click.stop="handleExport(agent)" :title="t('agent.export')">
              <Upload class="h-4 w-4" />
            </Button>
            <Button 
              v-if="canDelete(agent)" 
              variant="ghost" 
              size="icon" 
              class="text-destructive hover:text-destructive hover:bg-destructive/10"
              @click.stop="handleDelete(agent)" 
              :title="t('agent.delete')"
            >
              <Trash2 class="h-4 w-4" />
            </Button>
            </div>
          </CardFooter>
        </Card>
      </div>
    </div>
    <div v-else class="flex-1 overflow-hidden">
       <AgentEdit 
      :visible="currentView !== 'list'" 
      :agent="editingAgent" 
      :tools="tools" 
      :skills="skills" 
      :knowledgeBases="knowledgeBases"
      @save="handleSaveAgent"
      @update:visible="handleCloseEdit" 
    />
    </div>
    <!-- Export Dialog -->
    <Dialog :open="showExportDialog" @update:open="showExportDialog = $event">
      <DialogContent class="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{{ t('agent.exportTitle') }}</DialogTitle>
          <DialogDescription>
            {{ t('agent.exportDescription') }}
          </DialogDescription>
        </DialogHeader>
        <div class="grid gap-4 py-4">
          <div class="grid grid-cols-4 items-center gap-4">
            <Label class="text-right">
              {{ t('agent.exportFormat') }}
            </Label>
            <div class="col-span-3 flex gap-4">
               <div class="flex items-center space-x-2">
                  <input type="radio" id="json" value="json" v-model="exportFormat" class="accent-primary h-4 w-4" />
                  <label for="json" class="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">JSON</label>
               </div>
               <div class="flex items-center space-x-2">
                  <input type="radio" id="yaml" value="yaml" v-model="exportFormat" class="accent-primary h-4 w-4" />
                  <label for="yaml" class="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">YAML</label>
               </div>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showExportDialog = false">{{ t('agent.cancel') }}</Button>
          <Button @click="confirmExport">{{ t('agent.export') }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Usage Dialog -->
    <Dialog :open="showUsageModal" @update:open="showUsageModal = $event">
      <DialogContent class="sm:max-w-[80vw] overflow-hidden">
        <DialogHeader>
          <DialogTitle>
            {{ usageAgent?.name ? `调用示例 - ${usageAgent.name}` : '调用示例' }}
          </DialogTitle>
          <DialogDescription>
            不同的会话要替换 session_id 为不同值。system_context 根据真实值替换
          </DialogDescription>
        </DialogHeader>

        <Tabs v-model="usageActiveTab" class="sm:max-w-[80vw] overflow-hidden">
          <TabsList class="grid w-full grid-cols-3">
            <TabsTrigger value="curl">cURL</TabsTrigger>
            <TabsTrigger value="python">Python</TabsTrigger>
            <TabsTrigger value="go">Go</TabsTrigger>
          </TabsList>

          <div class="mt-4 relative group sm:max-w-[80vw] overflow-hidden">
            <ScrollArea class="h-[400px] rounded-md border p-4 bg-background">
              <MarkdownRenderer :content="usageCodeMarkdown" />
            </ScrollArea>
          </div>
        </Tabs>

      </DialogContent>
    </Dialog>
    
    <!-- Agent Creation Option Modal -->
    <AgentCreationOption 
      :isOpen="showCreationModal" 
      :tools="tools" 
      @create-blank="handleBlankConfig"
      @create-smart="handleSmartConfig" 
      @close="showCreationModal = false" 
    />

    <AgentAuthModal 
      v-model:visible="showAuthModal"
      :agentId="authAgentId"
    />

  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { toast } from 'vue-sonner'
import { Plus, Edit, Trash2, Bot, FileBraces, Download, Upload, Copy, Loader, UserPlus, Star, Wrench, Zap } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import { useLanguage } from '../utils/i18n.js'
import { agentAPI } from '../api/agent.js'
import { modelProviderAPI } from '../api/modelProvider.js'
import { getCurrentUser } from '../utils/auth.js'
import AgentCreationOption from '../components/AgentCreationOption.vue'
import AgentEdit from '../components/AgentEdit.vue'
import AgentAuthModal from '../components/AgentAuthModal.vue'
import { toolAPI } from '../api/tool.js'
import { skillAPI } from '../api/skill.js'
import { knowledgeBaseAPI } from '../api/knowledgeBase.js'
import MarkdownRenderer from '../components/chat/MarkdownRenderer.vue'
import { useAgentEditStore } from '../stores/agentEdit'
import { normalizeAgentMode } from '../utils/agentMode.js'
import { buildImportedAgentDraft, parseAgentConfigImport } from '../utils/agentConfigImport.js'
import { dump } from 'js-yaml'

// UI Components
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'

// State
const agents = ref([])
const loading = ref(false)
const error = ref(null)
const tools = ref([])
const skills = ref([])
const knowledgeBases = ref([])
const modelProviders = ref([])
const showCreationModal = ref(false)
const currentView = ref('list') // 'list', 'create', 'edit', 'view'
const editingAgent = ref(null)
const showUsageModal = ref(false)
const usageAgent = ref(null)
const usageActiveTab = ref('curl')
const usageCodeMap = ref({ curl: '', python: '', go: '' })
const usageCodeRawMap = ref({ curl: '', python: '', go: '' })

// Export Dialog State
const showExportDialog = ref(false)
const exportFormat = ref('json')
const agentToExport = ref(null)

// Authorization Modal
const showAuthModal = ref(false)
const authAgentId = ref('')

// Composables
const { t } = useLanguage()
const route = useRoute()
const currentUser = ref(getCurrentUser())
const agentEditStore = useAgentEditStore()
const { listModelProviders } = modelProviderAPI

// 监听路由参数变化，处理刷新
watch(() => route.query.refresh, () => {
  if (currentView.value !== 'list') {
    handleBackToList()
  }
})



const canEdit = (agent) => {
  if (!currentUser.value) return false
  if (currentUser.value.role === 'admin') return true
  // If agent has no owner (system agent), user cannot edit
  if (!agent.user_id) return false
  return agent.user_id === currentUser.value.userid
}

const canDelete = (agent) => {
  if (!currentUser.value) return false
  if (currentUser.value.role === 'admin') return true
  // If agent has no owner (system agent), user cannot delete
  if (!agent.user_id) return false
  return agent.user_id === currentUser.value.userid
}

// 生命周期
onMounted(async () => {
  await loadAgents()
  await loadModelProviders()
  await loadAvailableTools()
  await loadAvailableSkills()
  await loadKnowledgeBases()
})


// API Methods
const loadAvailableTools = async () => {
  try {
    loading.value = true
    const response = await toolAPI.getTools()
    console.log('Available Tools Response:', response)
    if (response.tools) {
      tools.value = response.tools
    }
  } catch (error) {
    console.error('Failed to load available tools:', error)
  } finally {
    loading.value = false
  }
}

const loadAvailableSkills = async () => {
  try {
    loading.value = true
    const response = await skillAPI.getSkills()
    if (response.skills) {
      skills.value = response.skills
    }
  } catch (error) {
    console.error('Failed to load available skills:', error)
  } finally {
    loading.value = false
  }
}

const loadKnowledgeBases = async () => {
  try {
    loading.value = true
    const response = await knowledgeBaseAPI.getKnowledgeBases({ page: 1, page_size: 1000 })
    const { list } = response || {}
    knowledgeBases.value = list || []
  } catch (error) {
    console.error('Failed to load knowledge bases:', error)
  } finally {
    loading.value = false
  }
}

const loadModelProviders = async () => {
  try {
    const response = await listModelProviders()
    modelProviders.value = response || []
  } catch (error) {
    console.error('Failed to load model providers:', error)
    modelProviders.value = []
  }
}

// Methods
const loadAgents = async () => {
  try {
    loading.value = true
    error.value = null
    const response = await agentAPI.getAgents()
    // 后端返回格式: [...]
    agents.value = response || []
  } catch (err) {
    console.error('加载agents失败:', err)
    error.value = err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

const saveAgent = async (agentData) => {
  try {
    let result
    if (agentData.id) {
      // 更新现有agent
      result = await agentAPI.updateAgent(agentData.id, agentData)
    } else {
      // 创建新agent
      result = await agentAPI.createAgent(agentData)
    }
    // 重新加载列表
    await loadAgents()
    return result
  } catch (err) {
    console.error('保存agent失败:', err)
    throw err
  }
}

const removeAgent = async (agentId) => {
  try {
    await agentAPI.deleteAgent(agentId)
    // 重新加载列表
    await loadAgents()
  } catch (err) {
    console.error('删除agent失败:', err)
    throw err
  }
}
const getConfigBadgeVariant = (value) => {
  if (value === null) return 'secondary' // auto
  return value ? 'default' : 'outline' // enabled : disabled
}

const getConfigBadgeText = (value) => {
  if (value === null) return t('common.auto')
  return value ? t('agent.enabled') : t('agent.disabled')
}

const handleDelete = async (agent) => {
  if (agent.id === 'default') {
    alert(t('agent.defaultCannotDelete'))
    return
  }

  const confirmed = window.confirm(t('agent.deleteConfirm').replace('{name}', agent.name))
  if (!confirmed) return

  try {
    await removeAgent(agent.id)
    toast.success(t('agent.deleteSuccess').replace('{name}', agent.name))
  } catch (error) {
    console.error('删除agent失败:', error)
    toast.error(t('agent.deleteError'))
  }
}

const handleExport = (agent) => {
  agentToExport.value = agent
  exportFormat.value = 'json'
  showExportDialog.value = true
}

const confirmExport = () => {
  if (!agentToExport.value) return
  const agent = agentToExport.value
  
  // 创建导出的配置对象
  const exportConfig = {
    id: agent.id,
    name: agent.name,
    description: agent.description,
    systemPrefix: agent.systemPrefix,
    deepThinking: agent.deepThinking,
    multiAgent: agent.multiAgent,
    moreSupport: agent.moreSupport,
    maxLoopCount: agent.maxLoopCount,
    llm_provider_id: agent.llm_provider_id,
    availableTools: agent.availableTools,
    availableSkills: agent.availableSkills,
    availableKnowledgeBases: agent.availableKnowledgeBases,
    systemContext: agent.systemContext,
    availableWorkflows: agent.availableWorkflows,
    exportTime: new Date().toISOString(),
    version: '1.0'
  }

  let dataStr = ''
  let mimeType = ''
  let extension = ''

  if (exportFormat.value === 'json') {
    dataStr = JSON.stringify(exportConfig, null, 2)
    mimeType = 'application/json'
     extension = 'json'
   } else {
     dataStr = dump(exportConfig)
     mimeType = 'application/x-yaml'
     extension = 'yaml'
   }

  // 创建下载链接
  const dataBlob = new Blob([dataStr], { type: mimeType })
  const url = URL.createObjectURL(dataBlob)

  // 创建下载链接并触发下载
  const link = document.createElement('a')
  link.href = url
  link.download = `agent_${agent.name}_${new Date().toISOString().split('T')[0]}.${extension}`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)

  // 清理URL对象
  URL.revokeObjectURL(url)
  
  showExportDialog.value = false
  agentToExport.value = null
}

const handleImport = () => {
  // 创建文件输入元素
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json,.yaml,.yml,application/json,application/x-yaml,text/yaml,text/x-yaml'
  input.style.display = 'none'

  input.onchange = (event) => {
    const file = event.target.files[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = async (e) => {
      try {
        const importedConfig = parseAgentConfigImport(e.target.result)

        // 验证必要字段
        if (!importedConfig.name) {
          alert(t('agent.importMissingName'))
          return
        }

        const newAgent = buildImportedAgentDraft(importedConfig, t('agent.importSuffix'))

        // 切换到编辑视图并预填数据
        editingAgent.value = newAgent
        currentView.value = 'edit'
        toast.success(t('agent.importDataLoaded'))

      } catch (error) {
        alert(t('agent.importError'))
        console.error('Import error:', error)
      }
    }

    reader.readAsText(file)
  }

  // 添加到DOM并触发点击
  document.body.appendChild(input)
  input.click()
  document.body.removeChild(input)
}

const handleCreateAgent = () => {
  showCreationModal.value = true
}

const handleBlankConfig = async (selectedTools = []) => {
  showCreationModal.value = false
  
  let systemPrefix = ''
  try {
    // 强制使用中文模板
    const response = await agentAPI.getDefaultSystemPrompt('zh')
    if (response && response.data && response.data.content) {
      systemPrefix = response.data.content
    } else if (response && response.content) {
      systemPrefix = response.content
    }
  } catch (error) {
    console.error('Failed to load default system prompt:', error)
  }

  // 切换到创建视图，并预填可用工具和系统提示词
  editingAgent.value = {
    availableTools: Array.isArray(selectedTools) ? selectedTools : [],
    availableSkills: [],
    systemPrefix: systemPrefix
  }
  currentView.value = 'create'
}

const handleEditAgent = async (agent) => {
  try {
    loading.value = true
    // 调用详情接口获取完整信息
    const response = await agentAPI.getAgentDetail(agent.id)
    if (response) {
      editingAgent.value = response
    } else {
      // 如果接口返回格式不同，直接使用原有数据
      editingAgent.value = agent
    }
    currentView.value = 'edit'
  } catch (error) {
    console.error('获取Agent详情失败:', error)
    toast.error('获取Agent详情失败')
    // 失败时使用列表数据
    editingAgent.value = agent
    currentView.value = 'edit'
  } finally {
    loading.value = false
  }
}

const handleAuthorize = (agent) => {
  authAgentId.value = agent.id
  showAuthModal.value = true
}

const handleViewAgent = (agent) => {
  editingAgent.value = agent
  currentView.value = 'view'
}

const handleBackToList = () => {
  currentView.value = 'list'
  editingAgent.value = null
  agentEditStore.currentStep = 1
}

const handleCloseEdit = () => {
  currentView.value = 'list'
  editingAgent.value = null
  agentEditStore.currentStep = 1
}

const handleSaveAgent = async (agentData, shouldExit = true, doneCallback = null) => {
  try {
    const result = await saveAgent(agentData)
    
    if (shouldExit) {
      currentView.value = 'list'
      editingAgent.value = null
      agentEditStore.currentStep = 1
    } else {
      // 如果是创建操作且不退出，需要更新editingAgent为新创建的agent
      if (!agentData.id) {
        let newAgent = null
        if (result && result.id) {
          newAgent = result
        }
        
        // 如果API没有直接返回agent对象，尝试从列表中查找
        if (!newAgent && agents.value.length > 0) {
          // 尝试通过名称匹配 (注意：名称可能不唯一，这是一个fallback)
          newAgent = agents.value.find(a => a.name === agentData.name)
        }
        
        if (newAgent) {
          editingAgent.value = newAgent
        }
      }
    }

    if (agentData.id) {
      toast.success(t('agent.updateSuccess').replace('{name}', agentData.name))
    } else {
      toast.success(t('agent.createSuccess').replace('{name}', agentData.name))
    }
  } catch (error) {
    console.error('保存agent失败:', error)
    toast.error(t('agent.saveError'))
  } finally {
    if (doneCallback) doneCallback()
  }
}

const modelProviderMap = computed(() => {
  const map = {}
  modelProviders.value.forEach((provider) => {
    if (provider && provider.id != null) {
      map[provider.id] = provider
    }
  })
  return map
})

const getModelLabel = (providerId) => {
  if (!providerId) return t('agent.defaultModel')
  const provider = modelProviderMap.value[providerId]
  if (!provider) return providerId
  return provider.name 
}

const getAgentModeText = (mode) => {
  const normalizedMode = normalizeAgentMode(mode, 'auto')
  if (normalizedMode === 'auto') return t('agent.modeAuto')
  if (normalizedMode === 'fibre') return t('agent.modeFibre')
  if (normalizedMode === 'simple') return t('agent.modeSimple')
  return normalizedMode
}

const getAgentAvatar = (agentId) => {
  const seed = encodeURIComponent(agentId || 'default')
  return `https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=${seed}`
}

const copyAgentId = async (agentId) => {
  if (!agentId) return
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(agentId)
      toast.success('Agent ID 已复制')
      return
    }
  } catch (_) {}

  try {
    const textarea = document.createElement('textarea')
    textarea.value = agentId
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    toast.success('Agent ID 已复制')
  } catch (e) {
    toast.error('复制失败')
  }
}

const handleSmartConfig = async (description, selectedTools = [], callbacks = {}) => {
  const startTime = Date.now()
  console.log('🚀 开始智能配置生成，描述:', description)

  try {
    console.log('📡 发送auto-generate请求...')

    // 调用后端API生成Agent配置
    const result = await agentAPI.generateAgentConfig(description, selectedTools)
    const agentConfig = result
    const duration = Date.now() - startTime
    console.log(`📨 收到响应，耗时: ${duration}ms`)
    console.log('✅ 解析响应成功')

    // 使用后端返回的agent_config
    const newAgent = {
      ...agentConfig,
      availableTools: (Array.isArray(selectedTools) && selectedTools.length > 0)
        ? selectedTools
        : (agentConfig.availableTools || []),
      availableSkills: agentConfig.availableSkills || []
    }

    console.log('🎉 智能配置生成完成，总耗时:', Date.now() - startTime, 'ms')
    // 使用本地的saveAgent方法
    await saveAgent(newAgent)
    // 由父组件监听器中的回调驱动子组件关闭
    callbacks.onSuccess && callbacks.onSuccess()
    toast.success(t('agent.smartConfigSuccess').replace('{name}', newAgent.name))
  } catch (error) {
    const duration = Date.now() - startTime
    console.error('❌ 智能配置生成失败，耗时:', duration, 'ms')
    console.error('❌ 错误详情:', {
      name: error.name,
      message: error.message,
      stack: error.stack
    })

    // 处理超时错误
    if (error.name === 'AbortError') {
      throw new Error(`请求超时（耗时${Math.round(duration / 1000)}秒），Agent配置生成需要较长时间，请稍后重试`)
    }

    // 处理网络错误
    if (error.name === 'TypeError' && error.message.includes('fetch')) {
      throw new Error(`网络连接错误（耗时${Math.round(duration / 1000)}秒），请检查网络连接后重试`)
    }

    callbacks.onError && callbacks.onError(error)
    throw error // 保持原有错误传递行为
  }
}

// 生成调用示例
const openUsageModal = async (agent) => {
  try {
    usageAgent.value = agent
    generateUsageCodes(agent)
    usageActiveTab.value = 'curl'
    showUsageModal.value = true
  } catch (e) {
    console.error('生成调用示例失败:', e)
    toast.error('生成调用示例失败')
  }
}

const backendEndpoint = (
  import.meta.env.VITE_SAGE_API_BASE_URL || ''
).replace(/\/+$/, '')

const generateUsageCodes = (agent) => {
  const body = {
    messages: [
      { role: 'user', content: '你好，请帮我处理一个任务' }
    ],
    session_id: 'demo-session',
    agent_id: agent.id,
    user_id: currentUser.value?.userid || "demo-user",
    system_context: agent.systemContext || {}
  }

  const jsonStr = JSON.stringify(body, null, 2)
  const curl = [
    `curl -X POST "${backendEndpoint}/api/chat" \\
  -H "Content-Type: application/json" \\
  -d '${jsonStr}'`
  ].join('\n')

  const python = [
    'import requests',
    '',
    `url = "${backendEndpoint}/api/chat"`,
    'payload = ' + jsonStr,
    'headers = {"Content-Type": "application/json"}',
    '',
    'resp = requests.post(url, json=payload, headers=headers)',
    'print(resp.status_code)'
  ].join('\n')

  const go = [
    'package main',
    '',
    'import (',
    '  "bytes"',
    '  "net/http"',
    '  "fmt"',
    ')',
    '',
    'func main() {',
    `  url := "${backendEndpoint}/api/chat"`,
    '  body := []byte(`' + jsonStr.replace(/`/g, '\\`') + '`)',
    '  req, _ := http.NewRequest("POST", url, bytes.NewBuffer(body))',
    '  req.Header.Set("Content-Type", "application/json")',
    '  resp, err := http.DefaultClient.Do(req)',
    '  if err != nil {',
    '    panic(err)',
    '  }',
    '  fmt.Println(resp.Status)',
    '}'
  ].join('\n')


  // 保存原始代码用于复制
  usageCodeRawMap.value.curl = curl
  usageCodeRawMap.value.python = python
  usageCodeRawMap.value.go = go

  // 保存 Markdown 格式用于展示
  usageCodeMap.value.curl = '```bash\n' + curl + '\n```'
  usageCodeMap.value.python = '```python\n' + python + '\n```'
  usageCodeMap.value.go = '```go\n' + go + '\n```'
}

const usageCodeMarkdown = computed(() => usageCodeMap.value[usageActiveTab.value] || '')

</script>
