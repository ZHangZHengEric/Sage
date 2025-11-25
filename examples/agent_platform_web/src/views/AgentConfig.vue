<template>
 <div class="agent-config-page">
    <div v-if="currentView === 'list'" class="page-header">
    <div class="page-actions">
      <el-button type="default" @click="handleImport">
        <Upload :size="16" />
        {{ t('agent.import') }}
      </el-button>
      <el-button type="primary" @click="handleCreateAgent">
        <Plus :size="16" />
        {{ t('agent.create') }}
      </el-button>
    </div>

  </div>

  <!-- 列表视图 -->
  <div v-if="currentView === 'list'" class="agents-grid">
    <div v-for="agent in agents" :key="agent.id" class="agent-card">
      <div class="agent-header">
        <div class="agent-avatar">
          <Bot :size="24" />
        </div>
        <div class="agent-info">
          <h3 class="agent-name">{{ agent.name }}</h3>
          <p class="agent-description">{{ agent.description }}</p>
        </div>
      </div>

      <div class="agent-config">
        <div class="config-item">
          <span class="config-label">{{ t('agent.model') }}:</span>
          <span class="config-value">
            {{ agent.llmConfig?.model || t('agent.defaultModel') }}
          </span>
        </div>
        <div class="config-item">
          <span class="config-label">{{ t('agent.deepThinking') }}:</span>
          <span :class="['config-badge', getConfigBadgeClass(agent.deepThinking)]">
            {{ getConfigBadgeText(agent.deepThinking) }}
          </span>
        </div>
        <div class="config-item">
          <span class="config-label">{{ t('agent.multiAgent') }}:</span>
          <span :class="['config-badge', getConfigBadgeClass(agent.multiAgent)]">
            {{ getConfigBadgeText(agent.multiAgent) }}
          </span>
        </div>
        <div class="config-item">
          <span class="config-label">{{ t('agent.availableTools') }}:</span>
          <span class="config-value">
            {{ agent.availableTools?.length || 0 }} {{ t('agent.toolsCount') }}
          </span>
        </div>
      </div>

      <div class="agent-actions">
          <el-button type="default" class="action-icon" @click="openUsageModal(agent)">
            <Settings :size="16" />
            示例
          </el-button>
        <el-button type="default" @click="handleEditAgent(agent)">
          <Edit :size="16" />
          {{ t('agent.edit') }}
        </el-button>
        <el-button type="default" @click="handleExport(agent)" :title="t('agent.export')">
          <Download :size="16" />
          {{ t('agent.export') }}
        </el-button>
        <el-button v-if="agent.id !== 'default'" type="danger" @click="handleDelete(agent)">
          <Trash2 :size="16" />
          {{ t('agent.delete') }}
        </el-button>
      </div>
    </div>
  </div>

  <!-- Agent编辑/创建视图 -->
  <div v-else>
    <div class="view-header">
      <h3 class="form-title">{{ currentView === 'edit' ? t('agent.editTitle') : t('agent.createTitle') }}</h3>
      <el-button @click="handleBackToList" type="default">
        ← {{ t('tools.backToList') }}
      </el-button>
    </div>

    <AgentEdit :visible="currentView !== 'list'" :agent="editingAgent" :tools="tools" @save="handleSaveAgent"
      @update:visible="handleCloseEdit" />
  </div>

  <!-- Agent创建模态框 -->
  <AgentCreationOption :isOpen="showCreationModal" :tools="tools" @create-blank="handleBlankConfig"
    @create-smart="handleSmartConfig" @close="showCreationModal = false" />

  <!-- 调用示例弹框 -->
  <el-dialog v-model="showUsageModal" :title="usageAgent?.name ? `调用示例 - ${usageAgent.name}` : '调用示例'" width="60%">
    <el-tabs v-model="usageActiveTab">
      <el-tab-pane label="cURL" name="curl" />
      <el-tab-pane label="Python" name="python" />
      <el-tab-pane label="Go" name="go" />
      <el-tab-pane label="Java" name="java" />
    </el-tabs>
    <div class="usage-code">
      <button class="copy-icon-btn" @click="copyUsageCode" title="复制">
        <Copy :size="16" />
      </button>
      <ReactMarkdown :content="usageCodeMarkdown" />
    </div>
    <template #footer>
      <div class="dialog-footer">
        <el-button @click="copyUsageCode">复制</el-button>
        <el-button type="primary" @click="showUsageModal = false">关闭</el-button>
      </div>
    </template>
  </el-dialog>
</div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { Plus, Edit, Trash2, Bot, Settings, Download, Upload, Copy } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useLanguage } from '../utils/i18n.js'
import { agentAPI } from '../api/agent.js'
import AgentCreationOption from '../components/AgentCreationOption.vue'
import AgentEdit from '../components/AgentEdit.vue'
import { toolAPI } from '../api/tool.js'
import ReactMarkdown from '../components/chat/ReactMarkdown.vue'

// State
const agents = ref([])
const loading = ref(false)
const error = ref(null)
const tools = ref([])
const showCreationModal = ref(false)
const currentView = ref('list') // 'list', 'create', 'edit', 'view'
const editingAgent = ref(null)
const showUsageModal = ref(false)
const usageAgent = ref(null)
const usageActiveTab = ref('curl')
const usageCodeMap = ref({ curl: '', python: '', go: '', java: '' })

// Composables
const { t } = useLanguage()

// 生命周期
onMounted(async () => {
  await loadAgents()
  await loadAvailableTools()
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

// Methods
const loadAgents = async () => {
  try {
    loading.value = true
    error.value = null
    const response = await agentAPI.getAgents()
    agents.value = response
  } catch (err) {
    console.error('加载agents失败:', err)
    error.value = err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

const saveAgent = async (agentData) => {
  try {
    if (agentData.id) {
      // 更新现有agent
      await agentAPI.updateAgent(agentData.id, agentData)
    } else {
      // 创建新agent
      await agentAPI.createAgent(agentData)
    }
    // 重新加载列表
    await loadAgents()
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
const getConfigBadgeClass = (value) => {
  if (value === null) return 'auto'
  return value ? 'enabled' : 'disabled'
}

const getConfigBadgeText = (value) => {
  if (value === null) return t('common.auto')
  return value ? t('agent.enabled') : t('agent.disabled')
}

const handleDelete = async (agent) => {
  if (agent.id === 'default') {
    ElMessage.warning(t('agent.defaultCannotDelete'))
    return
  }

  try {
    await ElMessageBox.confirm(
      t('agent.deleteConfirm').replace('{name}', agent.name),
      t('common.confirm'),
      {
        confirmButtonText: t('common.confirm'),
        cancelButtonText: t('common.cancel'),
        type: 'warning'
      }
    )

    // 使用本地的removeAgent方法
    await removeAgent(agent.id)
    ElMessage.success(t('agent.deleteSuccess').replace('{name}', agent.name))
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除agent失败:', error)
      ElMessage.error(t('agent.deleteError'))
    }
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
          ElMessage.error(t('agent.importMissingName'))
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
          systemContext: importedConfig.systemContext || {},
          availableWorkflows: importedConfig.availableWorkflows || {}
        }

        // 切换到编辑视图并预填数据
        editingAgent.value = newAgent
        currentView.value = 'edit'

      } catch (error) {
        ElMessage.error(t('agent.importError'))
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
    availableTools: Array.isArray(selectedTools) ? selectedTools : []
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

const handleSaveAgent = async (agentData) => {
  try {
    await saveAgent(agentData)
    currentView.value = 'list'
    editingAgent.value = null

    if (agentData.id) {
      ElMessage.success(t('agent.updateSuccess').replace('{name}', agentData.name))
    } else {
      ElMessage.success(t('agent.createSuccess').replace('{name}', agentData.name))
    }
  } catch (error) {
    console.error('保存agent失败:', error)
    ElMessage.error(t('agent.saveError'))
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
        : (agentConfig.availableTools || [])
    }

    console.log('🎉 智能配置生成完成，总耗时:', Date.now() - startTime, 'ms')
    // 使用本地的saveAgent方法
    await saveAgent(newAgent)
    // 由父组件监听器中的回调驱动子组件关闭
    callbacks.onSuccess && callbacks.onSuccess()
    ElMessage.success(t('agent.smartConfigSuccess').replace('{name}', newAgent.name))
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
    ElMessage.error('生成调用示例失败')
  }
}

const backendEndpoint = (
  import.meta.env.VITE_SAGE_API_BASE_URL ||
  import.meta.env.VITE_BACKEND_ENDPOINT ||
  ''
).replace(/\/+$/, '')

const generateUsageCodes = (agent) => {
  const body = {
    messages: [
      { role: 'user', content: '你好，请帮我处理一个任务' }
    ],
    session_id: 'demo-session',
    deep_thinking: agent.deepThinking ?? null,
    multi_agent: agent.multiAgent ?? null,
    max_loop_count: agent.maxLoopCount ?? 20,
    system_prefix: agent.systemPrefix || '',
    system_context: agent.systemContext || {},
    available_workflows: agent.availableWorkflows || {},
    llm_model_config: agent.llmConfig || null,
    available_tools: agent.availableTools || [],
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
    '}',
  ].join('\n')

  const java = [
    'import java.net.*;',
    'import java.io.*;',
    '',
    'public class Demo {',
    '  public static void main(String[] args) throws Exception {',
    `    String url = "${backendEndpoint}/api/stream";`,
    '    String json = ' + JSON.stringify(jsonStr) + ';',
    '    HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();',
    '    conn.setRequestMethod("POST");',
    '    conn.setRequestProperty("Content-Type", "application/json");',
    '    conn.setDoOutput(true);',
    '    try (OutputStream os = conn.getOutputStream()) {',
    '      os.write(json.getBytes("UTF-8"));',
    '    }',
    '    System.out.println(conn.getResponseCode());',
    '  }',
    '}',
  ].join('\n')

  usageCodeMap.value.curl = '```bash\n' + curl + '\n```'
  usageCodeMap.value.python = '```python\n' + python + '\n```'
  usageCodeMap.value.go = '```go\n' + go + '\n```'
  usageCodeMap.value.java = '```java\n' + java + '\n```'
}

const usageCodeMarkdown = computed(() => usageCodeMap.value[usageActiveTab.value] || '')

const copyUsageCode = async () => {
  const md = usageCodeMap.value[usageActiveTab.value] || ''
  const raw = md.replace(/^```[\s\S]*?\n/, '').replace(/\n```$/, '')
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(raw)
      ElMessage.success('代码已复制到剪贴板')
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
      ElMessage.success('代码已复制到剪贴板')
    } else {
      ElMessage.error('复制失败')
    }
  } catch (e) {
    document.body.removeChild(ta)
    ElMessage.error('复制失败')
  }
}
</script>

<style scoped>
.agent-config-page {
  padding: 1.5rem;
  min-height: 100vh;
  background: transparent;
}

.page-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 2rem;
}


.page-actions {
  display: flex;
  gap: 0.75rem;
}

.agents-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 1.5rem;
  border-radius: 12px;
  padding: 1.5rem;
  background: transparent;
}

.agent-card {
  background: transparent;
  border: 2px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 1.5rem;
  transition: all 0.2s ease;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.222);
}

.agent-card:hover {
  border-color: #667eea;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  transform: translateY(-2px);
}

.agent-header {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.agent-avatar {
  width: 48px;
  height: 48px;
  background: #667eea;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.agent-info {
  flex: 1;
  min-width: 0;
}

.agent-name {
  margin: 0 0 0.5rem 0;
  font-size: 1.125rem;
  font-weight: 600;
  color: #1f2937;
  word-break: break-word;
}

.agent-description {
  margin: 0;
  color: #6b7280;
  font-size: 0.875rem;
  line-height: 1.4;
  word-break: break-word;
}

.agent-config {
  margin-bottom: 1.5rem;
}

.config-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.config-item:last-child {
  margin-bottom: 0;
}

.config-label {
  font-size: 0.875rem;
  color: #6b7280;
  font-weight: 500;
}

.config-value {
  font-size: 0.875rem;
  color: #1f2937;
}


.agent-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.agent-actions .el-button {
  flex: 1;
  min-width: 0;
}

.agent-actions .action-icon {
  flex: 0 0 auto;
}



.config-badge {
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 500;
  text-transform: uppercase;
}

.config-badge.auto {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.config-badge.enabled {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
}

.config-badge.disabled {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}
.view-header {
  display: flex;
  justify-content: space-between;
  align-items: center;

}

.usage-code {
  margin-top: 12px;
  position: relative;
}

.usage-code :deep(pre) {
  white-space: pre-wrap;
  word-break: break-word;
}

.usage-code :deep(code) {
  white-space: pre-wrap;
  word-break: break-word;
}

.copy-icon-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  border: none;
  background: rgba(0,0,0,0.05);
  border-radius: 6px;
  padding: 6px;
  cursor: pointer;
}

.copy-icon-btn:hover {
  background: rgba(0,0,0,0.1);
}

</style>
