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
      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5 gap-6">
        <Card v-for="agent in agents" :key="agent.id" class="flex flex-col h-full hover:shadow-lg transition-all duration-300 hover:-translate-y-1">
          <CardHeader class="pb-4">
            <div class="flex items-start gap-4">
              <div class="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 text-primary">
                <Bot class="h-6 w-6" />
              </div>
              <div class="space-y-1 overflow-hidden flex-1">
                <CardTitle class="text-lg leading-tight truncate" :title="agent.name">
                  {{ agent.name }}
                </CardTitle>
                <CardDescription class="line-clamp-2 min-h-[2.5rem]">
                  {{ agent.description }}
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          
          <CardContent class="flex-1 pb-4">
             <div class="space-y-3 text-sm">
                <div class="flex justify-between">
                   <span class="text-muted-foreground">{{ t('agent.model') }}:</span>
                   <span class="font-medium truncate max-w-[120px]" :title="agent.llmConfig?.model">{{ agent.llmConfig?.model || t('agent.defaultModel') }}</span>
                </div>
                <div class="flex justify-between items-center">
                   <span class="text-muted-foreground">{{ t('agent.deepThinking') }}:</span>
                   <Badge :variant="getConfigBadgeVariant(agent.deepThinking)">{{ getConfigBadgeText(agent.deepThinking) }}</Badge>
                </div>
                <div class="flex justify-between items-center">
                   <span class="text-muted-foreground">{{ t('agent.multiAgent') }}:</span>
                   <Badge :variant="getConfigBadgeVariant(agent.multiAgent)">{{ getConfigBadgeText(agent.multiAgent) }}</Badge>
                </div>
                <div class="flex justify-between">
                   <span class="text-muted-foreground">{{ t('agent.availableTools') }}:</span>
                   <span>{{ agent.availableTools?.length || 0 }} {{ t('agent.toolsCount') }}</span>
                </div>
             </div>
          </CardContent>

          <CardFooter class="pt-4 border-t bg-muted/20 flex flex-wrap gap-2 justify-end">
            <Button variant="ghost" size="icon" @click="openUsageModal(agent)" :title="t('agent.usage')">
              <FileBraces class="h-4 w-4" />
            </Button>
            <Button v-if="canEdit(agent)" variant="ghost" size="icon" @click="handleEditAgent(agent)" :title="t('agent.edit')">
              <Edit class="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon" @click="handleExport(agent)" :title="t('agent.export')">
              <Upload class="h-4 w-4" />
            </Button>
            <Button 
              v-if="canDelete(agent)" 
              variant="ghost" 
              size="icon" 
              class="text-destructive hover:text-destructive hover:bg-destructive/10"
              @click="handleDelete(agent)" 
              :title="t('agent.delete')"
            >
              <Trash2 class="h-4 w-4" />
            </Button>
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

        <DialogFooter>
          <Button variant="outline" @click="copyUsageCode">复制</Button>
          <Button @click="showUsageModal = false">关闭</Button>
        </DialogFooter>
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

  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { toast } from 'vue-sonner'
import { Plus, Edit, Trash2, Bot, FileBraces, Download, Upload, Copy, Loader } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { agentAPI } from '../api/agent.js'
import { getCurrentUser } from '../utils/auth.js'
import AgentCreationOption from '../components/AgentCreationOption.vue'
import AgentEdit from '../components/AgentEdit.vue'
import { toolAPI } from '../api/tool.js'
import { skillAPI } from '../api/skill.js'
import { knowledgeBaseAPI } from '../api/knowledgeBase.js'
import MarkdownRenderer from '../components/chat/MarkdownRenderer.vue'

// UI Components
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'

// State
const agents = ref([])
const loading = ref(false)
const error = ref(null)
const tools = ref([])
const skills = ref([])
const knowledgeBases = ref([])
const showCreationModal = ref(false)
const currentView = ref('list') // 'list', 'create', 'edit', 'view'
const editingAgent = ref(null)
const showUsageModal = ref(false)
const usageAgent = ref(null)
const usageActiveTab = ref('curl')
const usageCodeMap = ref({ curl: '', python: '', go: '' })
const usageCodeRawMap = ref({ curl: '', python: '', go: '' })

// Composables
const { t } = useLanguage()
const route = useRoute()
const currentUser = ref(getCurrentUser())

// 监听路由参数变化，处理刷新
import { watch } from 'vue'
import { useRoute } from 'vue-router'

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
    if (response.data && response.data.list) {
      knowledgeBases.value = response.data.list
    }
  } catch (error) {
    console.error('Failed to load knowledge bases:', error)
  } finally {
    loading.value = false
  }
}

// Methods
const loadAgents = async () => {
  try {
    loading.value = true
    error.value = null
    const response = await agentAPI.getAgents()
    if (response.agents) {
      agents.value = response.agents
    } else if (Array.isArray(response)) {
      agents.value = response
    } else {
      agents.value = []
    }
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
    llmConfig: agent.llmConfig,
    availableTools: agent.availableTools,
    availableSkills: agent.availableSkills,
    availableKnowledgeBases: agent.availableKnowledgeBases,
    systemContext: agent.systemContext,
    availableWorkflows: agent.availableWorkflows,
    exportTime: new Date().toISOString(),
    version: '1.0'
  }

  // 创建下载链接
  const dataStr = JSON.stringify(exportConfig, null, 2)
  const dataBlob = new Blob([dataStr], { type: 'application/json' })
  const url = URL.createObjectURL(dataBlob)

  // 创建下载链接并触发下载
  const link = document.createElement('a')
  link.href = url
  link.download = `agent_${agent.name}_${new Date().toISOString().split('T')[0]}.json`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)

  // 清理URL对象
  URL.revokeObjectURL(url)
}

const handleImport = () => {
  // 创建文件输入元素
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json'
  input.style.display = 'none'

  input.onchange = (event) => {
    const file = event.target.files[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = async (e) => {
      try {
        const importedConfig = JSON.parse(e.target.result)

        // 验证必要字段
        if (!importedConfig.name) {
          alert(t('agent.importMissingName'))
          return
        }

        // 创建新的Agent配置
        const newAgent = {
          name: importedConfig.name + t('agent.importSuffix'),
          llmConfig: importedConfig.llmConfig || {},
          description: importedConfig.description || '',
          systemPrefix: importedConfig.systemPrefix || '',
          deepThinking: importedConfig.deepThinking || false,
          multiAgent: importedConfig.multiAgent || false,
          maxLoopCount: importedConfig.maxLoopCount || 10,
          availableTools: importedConfig.availableTools || [],
          availableSkills: importedConfig.availableSkills || [],
          availableKnowledgeBases: importedConfig.availableKnowledgeBases || [],
          systemContext: importedConfig.systemContext || {},
          availableWorkflows: importedConfig.availableWorkflows || {}
        }

        // 切换到编辑视图并预填数据
        editingAgent.value = newAgent
        currentView.value = 'edit'

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

const handleBlankConfig = (selectedTools = []) => {
  showCreationModal.value = false
  // 切换到创建视图，并预填可用工具
  editingAgent.value = {
    availableTools: Array.isArray(selectedTools) ? selectedTools : [],
    availableSkills: []
  }
  currentView.value = 'create'
}

const handleEditAgent = (agent) => {
  editingAgent.value = agent
  currentView.value = 'edit'
}

const handleViewAgent = (agent) => {
  editingAgent.value = agent
  currentView.value = 'view'
}

const handleBackToList = () => {
  currentView.value = 'list'
  editingAgent.value = null
}

const handleCloseEdit = () => {
  currentView.value = 'list'
  editingAgent.value = null
}

const handleSaveAgent = async (agentData, shouldExit = true, doneCallback = null) => {
  try {
    const result = await saveAgent(agentData)
    
    if (shouldExit) {
      currentView.value = 'list'
      editingAgent.value = null
    } else {
      // 如果是创建操作且不退出，需要更新editingAgent为新创建的agent
      if (!agentData.id) {
        let newAgent = null
        if (result && result.agent) {
          newAgent = result.agent
        } else if (result && result.id) {
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

const handleSmartConfig = async (description, selectedTools = [], callbacks = {}) => {
  const startTime = Date.now()
  console.log('🚀 开始智能配置生成，描述:', description)

  try {
    console.log('📡 发送auto-generate请求...')

    // 调用后端API生成Agent配置
    const result = await agentAPI.generateAgentConfig(description, selectedTools)
    const agentConfig = result.agent
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
    memory_type: agent.memoryType || 'session',
    deep_thinking: agent.deepThinking ?? null,
    multi_agent: agent.multiAgent ?? null,
    max_loop_count: agent.maxLoopCount ?? 20,
    system_prefix: agent.systemPrefix || '',
    system_context: agent.systemContext || {},
    available_workflows: agent.availableWorkflows || {},
    llm_model_config: agent.llmConfig || null,
    available_tools: agent.availableTools || [],
    available_skills: agent.availableSkills || []
  }

  const jsonStr = JSON.stringify(body, null, 2)
  const curl = [
    `curl -X POST "${backendEndpoint}/api/stream" \\
  -H "Content-Type: application/json" \\
  -d '${jsonStr}'`
  ].join('\n')

  const python = [
    'import requests',
    '',
    `url = "${backendEndpoint}/api/stream"`,
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
    `  url := "${backendEndpoint}/api/stream"`,
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

const copyUsageCode = async () => {
  // 直接从 raw map 获取纯净代码，避免正则处理错误
  const raw = usageCodeRawMap.value[usageActiveTab.value] || ''
  
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(raw)
      toast.success('代码已复制到剪贴板')
      return
    }
  } catch (_) {}

  const ta = document.createElement('textarea')
  ta.value = raw
  ta.setAttribute('readonly', '')
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  ta.style.top = '0'
  document.body.appendChild(ta)
  ta.focus()
  ta.select()
  try {
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    if (ok) {
      toast.success('代码已复制到剪贴板')
    } else {
      toast.error('复制失败')
    }
  } catch (e) {
    document.body.removeChild(ta)
    toast.error('复制失败')
  }
}
</script>
