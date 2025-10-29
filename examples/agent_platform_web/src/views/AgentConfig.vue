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
 </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Plus, Edit, Trash2, Bot, Settings, Download, Upload } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useLanguage } from '../utils/i18n.js'
import { agentAPI } from '../api/agent.js'
import AgentCreationOption from '../components/AgentCreationOption.vue'
import AgentEdit from '../components/AgentEdit.vue'
import { toolAPI } from '../api/tool.js'

// State
const agents = ref([])
const loading = ref(false)
const error = ref(null)
const tools = ref([])
const showCreationModal = ref(false)
const currentView = ref('list') // 'list', 'create', 'edit', 'view'
const editingAgent = ref(null)

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

const handleBlankConfig = () => {
  showCreationModal.value = false
  // 切换到创建视图
  editingAgent.value = null
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

const handleSmartConfig = async (description) => {
  const startTime = Date.now()
  console.log('🚀 开始智能配置生成，描述:', description)

  try {
    console.log('📡 发送auto-generate请求...')

    // 调用后端API生成Agent配置
    const result = await agentAPI.generateAgentConfig(description)
    const agentConfig = result.agent
    const duration = Date.now() - startTime
    console.log(`📨 收到响应，耗时: ${duration}ms`)
    console.log('✅ 解析响应成功')

    // 使用后端返回的agent_config
    const newAgent = {
      ...agentConfig
    }

    console.log('🎉 智能配置生成完成，总耗时:', Date.now() - startTime, 'ms')
    showCreationModal.value = false
    // 使用本地的saveAgent方法
    await saveAgent(newAgent)
    showCreationModal.value = false
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

    throw error // 重新抛出错误，让AgentCreationModal处理
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

</style>