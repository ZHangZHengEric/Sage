<template>
  <div class="tools-page">
    <!-- 列表视图的页面头部 -->
    <div class="filter-tabs-row">
      <div class="filter-tabs">
        <button :class="['filter-tab', { active: activeTab === 'tools' }]" @click="activeTab = 'tools',viewMode = 'list'">
          {{ t('tools.Tools') }}
        </button>
        <button :class="['filter-tab', { active: activeTab === 'mcp' }]" @click="activeTab = 'mcp',viewMode = 'list'">
          {{ t('tools.mcpServers') }}
        </button>
      </div>
      <div v-if="viewMode === 'list'" class="search-box">
        <Search :size="16" class="search-icon" />
        <input type="text" class="input search-input"
          :placeholder="activeTab === 'mcp' ? t('tools.searchMcp') : t('tools.search')" v-model="searchTerm" />
      </div>

      <div v-if="activeTab === 'mcp'" class="mcp-actions">
        <button class="btn-primary" @click="showAddMcpForm">
          <Plus :size="16" />
          {{ t('tools.addMcpServer') }}
        </button>
      </div>
    </div>
    <!-- 列表视图的过滤器和内容 -->
    <div v-if="viewMode === 'list'" class="list-content">

      <!-- 工具列表 -->
      <div v-if="activeTab === 'tools'" class="tools-section">

        <div v-if="groupedTools.length > 0" class="tools-groups">
          <div v-for="(group, groupIndex) in groupedTools" :key="group.source" class="tool-group">
            <!-- 分组标题 -->
            <div class="group-header">
              <h3 class="group-title">{{ getToolSourceLabel(group.source) }}</h3>
              <span class="group-count">{{ group.tools.length }} {{ t('tools.count') }}</span>
            </div>
            
            <!-- 工具网格 -->
            <div class="tools-grid">
              <div v-for="tool in group.tools" :key="tool.name" class="tool-card" @click="openToolDetail(tool)">
                <div class="tool-header">
                  <div class="tool-icon"
                    :style="{ background: `linear-gradient(135deg, ${getToolTypeColor(tool.type)} 0%, ${getToolTypeColor(tool.type)}80 100%)` }">
                    <component :is="getToolIcon(tool.type)" :size="20" />
                  </div>
                  <div class="tool-info">
                    <h3 class="tool-name">{{ tool.name }}</h3>
                    <p class="tool-description">
                      {{ tool.description || t('tools.noDescription') }}
                    </p>
                  </div>
                </div>

                <div class="tool-meta">
                  <div class="meta-item">
                    <span class="meta-label">{{ t('tools.source') }}:</span>
                    <span class="meta-value">{{ getToolSourceLabel(tool.source) }}</span>
                  </div>
                  <div class="meta-item">
                    <span class="meta-label">{{ t('tools.params') }}:</span>
                    <span class="meta-value">
                      {{ formatParameters(tool.parameters).length }} {{ t('tools.count') }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
            
          </div>
        </div>

        <div v-if="filteredTools.length === 0" class="empty-state">
          <Wrench :size="48" class="empty-icon" />
          <h3>{{ t('tools.noTools') }}</h3>
          <p>{{ t('tools.noToolsDesc') }}</p>
        </div>
      </div>

      <!-- MCP服务器列表 -->
      <div v-if="activeTab === 'mcp'" class="mcp-section">

        <div class="mcp-grid">
          <div v-for="server in filteredMcpServers" :key="server.name" class="mcp-card">
            <!-- 卡片头部 -->
            <div class="mcp-header">
              <div class="mcp-icon" :class="getProtocolIconClass(server.protocol)">
                <Database :size="24" />
              </div>
              <div class="mcp-info">
                <div class="mcp-title-row">
                  <h3 class="mcp-name">{{ server.name }}</h3>
                  <div class="mcp-status-indicator" :class="{ disabled: server.disabled }">
                    <div class="status-dot"></div>
                    <span class="status-text">{{ server.disabled ? t('tools.disabled') : t('tools.enabled') }}</span>
                  </div>
                </div>
                <p class="mcp-description">
                  {{ getSimpleDescription(server) }}
                </p>
              </div>
              <!-- <div class="mcp-actions">
                <button class="action-btn" @click="toggleMcpServerStatus(server)"
                  :title="server.disabled ? t('tools.enable') : t('tools.disable')">
                  <component :is="server.disabled ? 'Play' : 'Pause'" :size="16" />
                </button>
                <button class="action-btn delete" @click="deleteMcpServerHandler(server)" :title="t('tools.delete')">
                  <Trash2 :size="16" />
                </button>
              </div> -->
            </div>

            <!-- 协议信息 -->
            <div class="mcp-protocol-section">
              <div class="protocol-badge" :class="server.protocol">
                <span class="protocol-icon">{{ getProtocolIcon(server.protocol) }}</span>
                <span class="protocol-name">{{ server.protocol?.toUpperCase() || 'UNKNOWN' }}</span>
              </div>
              <div class="protocol-details">
                <div v-if="server.streamable_http_url" class="connection-info">
                  <span class="connection-label">HTTP:</span>
                  <span class="connection-url">{{server.streamable_http_url }}</span>
                </div>
                <div v-if="server.sse_url" class="connection-info">
                  <span class="connection-label">SSE:</span>
                  <span class="connection-url">{{ server.sse_url }}</span>
                </div>
                <div v-if="server.command" class="connection-info">
                  <span class="connection-label">CMD:</span>
                  <span class="connection-url">{{ server.command }}</span>
                </div>
              </div>
            </div>

          </div>
        </div>

      </div>
    </div>

    <!-- 工具详情视图 -->
    <div v-if="viewMode === 'detail' && selectedTool" class="tool-detail-view">
      <div class="detail-header">

        <div class="detail-tool-info">
          <div class="detail-tool-icon"
            :style="{ background: `linear-gradient(135deg, ${getToolTypeColor(selectedTool.type)} 0%, ${getToolTypeColor(selectedTool.type)}80 100%)` }">
            <component :is="getToolIcon(selectedTool.type)" :size="24" />
          </div>
          <div class="detail-tool-meta">
            <h1>{{ selectedTool.name }}</h1>
            <span class="detail-tool-type" :style="{ background: getToolTypeColor(selectedTool.type) }">
              {{ getToolTypeLabel(selectedTool.type) }}
            </span>
          </div>
        </div>
        <button class="back-button" @click="backToList">
          <ArrowLeft :size="20" />
          {{ t('tools.backToList') }}
        </button>
      </div>

      <div class="tool-detail-content">
        <div class="tool-section">
          <h3>
            <Database :size="20" />
            {{ t('toolDetail.description') }}
          </h3>
          <p>{{ selectedTool.description || t('tools.noDescription') }}</p>
        </div>

        <div class="tool-section">
          <h3>
            <Code :size="20" />
            {{ t('toolDetail.basicInfo') }}
          </h3>
          <div class="info-grid">
            <div class="info-item">
              <span class="info-label">{{ t('toolDetail.toolName') }}</span>
              <span class="info-value">{{ selectedTool.name }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">{{ t('toolDetail.toolType') }}</span>
              <span class="info-value">{{ getToolTypeLabel(selectedTool.type) }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">{{ t('toolDetail.source') }}</span>
              <span class="info-value">{{ getToolSourceLabel(selectedTool.source) }}</span>
            </div>
          </div>
        </div>

        <div class="tool-section">
          <h3>
            <Wrench :size="20" />
            {{ t('toolDetail.parameterDetails') }}
          </h3>
          <div v-if="formattedParams.length > 0" class="params-table-container">
            <table class="params-table">
              <thead>
                <tr>
                  <th>{{ t('toolDetail.paramName') }}</th>
                  <th>{{ t('toolDetail.paramType') }}</th>
                  <th>{{ t('toolDetail.required') }}</th>
                  <th>{{ t('toolDetail.paramDescription') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(param, index) in formattedParams" :key="index">
                  <td class="param-name">{{ param.name }}</td>
                  <td class="param-type">{{ param.type }}</td>
                  <td class="param-required">
                    <span :class="param.required ? 'required-yes' : 'required-no'">
                      {{ param.required ? t('toolDetail.yes') : t('toolDetail.no') }}
                    </span>
                  </td>
                  <td class="param-description">{{ param.description }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="no-parameters">{{ t('toolDetail.noParameters') }}</p>
        </div>

        <div class="tool-section">
          <h3>
            <Globe :size="20" />
            {{ t('toolDetail.rawConfig') }}
          </h3>
          <pre class="config-display">{{ JSON.stringify(selectedTool.parameters, null, 2) }}</pre>
        </div>
      </div>
    </div>

    <!-- MCP服务器添加视图 -->
    <div v-if="viewMode === 'add-mcp'" class="add-mcp-view">
      <div class="tool-detail-content">
        <form @submit.prevent="handleSubmit" class="add-mcp-form">
          <div class="tool-section">
            <h3>
              <Database :size="20" />
              {{ t('tools.basicInfo') }}
            </h3>

            <div class="form-group">
              <label for="name">{{ t('tools.serverName') }}</label>
              <input id="name" v-model="mcpForm.name" type="text" :placeholder="t('tools.enterServerName')" required
                class="form-input" />
            </div>
          </div>

          <div  class="tool-section">
            <h3>
              <Code :size="20" />
              {{ t('tools.protocolConfig') }}
            </h3>

            <div class="form-group">
              <label for="protocol">{{ t('tools.protocol') }}</label>
              <select id="protocol" v-model="mcpForm.protocol" required class="form-select">
                <option value="stdio">stdio</option>
                <option value="sse">SSE</option>
                <option value="streamable_http">Streamable HTTP</option>
              </select>
            </div>

            <!-- stdio 协议配置 -->
            <div v-if="mcpForm.protocol === 'stdio'">
              <div class="form-group">
                <label for="command">{{ t('tools.command') }}</label>
                <input id="command" v-model="mcpForm.command" type="text" :placeholder="t('tools.enterCommand')"
                  required class="form-input" />
              </div>

              <div class="form-group">
                <label for="args">{{ t('tools.arguments') }}</label>
                <input id="args" v-model="mcpForm.args" type="text" :placeholder="t('tools.enterArguments')"
                  class="form-input" />
              </div>
            </div>

            <!-- SSE 协议配置 -->
            <div v-if="mcpForm.protocol === 'sse'">
              <div class="form-group">
                <label for="sse_url">{{ t('tools.sseUrl') }}</label>
                <input id="sse_url" v-model="mcpForm.sse_url" type="url" :placeholder="t('tools.enterSseUrl')" required
                  class="form-input" />
              </div>
            </div>

            <!-- Streamable HTTP 协议配置 -->
            <div v-if="mcpForm.protocol === 'streamable_http'">
              <div class="form-group">
                <label for="streamable_http_url">{{ t('tools.streamingHttpUrl') }}</label>
                <input id="streamable_http_url" v-model="mcpForm.streamable_http_url" type="url"
                  :placeholder="t('tools.enterStreamingHttpUrl')" required class="form-input" />
              </div>
            </div>
          </div>

          <div class="tool-section">
            <h3>
              <Globe :size="20" />
              {{ t('tools.additionalInfo') }}
            </h3>

            <div class="form-group">
              <label for="description">{{ t('tools.description') }}</label>
              <textarea id="description" v-model="mcpForm.description" :placeholder="t('tools.enterDescription')"
                rows="4" class="form-textarea"></textarea>
            </div>
          </div>

          <div class="form-actions">
            <button type="button" class="btn-secondary" @click="backToList">
              {{ t('tools.cancel') }}
            </button>
            <button type="submit" class="btn-primary" :disabled="loading">
              <Loader2 v-if="loading" :size="16" class="animate-spin" />
              {{ loading ? t('tools.adding') : t('tools.add') }}
            </button>
          </div>
        </form>
      </div>
    </div>

 
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Wrench, Search, Code, Database, Globe, Cpu, Plus, Play, Pause, Trash2, ArrowLeft, Loader2, Settings, Key } from 'lucide-vue-next'
import { useLanguage } from '../utils/language'
import { getTools, getMcpServers, toggleMcpServer, deleteMcpServer, addMcpServer } from '../api/modules/tool'

// Composables
const { t } = useLanguage()

// State
const allTools = ref([])
const mcpServers = ref([])
const selectedTool = ref(null)
const searchTerm = ref('')
const filterType = ref('all')
const activeTab = ref('tools')
const viewMode = ref('list') // 'list', 'detail', 'add-mcp'
const loading = ref(false)

// MCP表单数据
const mcpForm = ref({
  name: '',
  protocol: 'sse',
  command: '',
  args: '',
  sse_url: '',
  streamable_http_url: '',
  description: ''
})


const filteredTools = computed(() => {
  let filtered = allTools.value

  // 搜索过滤
  if (searchTerm.value.trim()) {
    const query = searchTerm.value.toLowerCase()
    filtered = filtered.filter(tool =>
      tool.name.toLowerCase().includes(query) ||
      tool.description.toLowerCase().includes(query)
    )
  }

  // 类型过滤
  if (filterType.value !== 'all') {
    filtered = filtered.filter(tool => tool.type === filterType.value)
  }

  return filtered
})

const filteredMcpServers = computed(() => {
  if (!searchTerm.value.trim()) {
    return mcpServers.value
  }

  const query = searchTerm.value.toLowerCase()
  return mcpServers.value.filter(server =>
    server.name.toLowerCase().includes(query) ||
    (server.streamable_http_url && server.streamable_http_url.toLowerCase().includes(query)) ||
    (server.sse_url && server.sse_url.toLowerCase().includes(query))
  )
})

const formattedParams = computed(() => {
  if (!selectedTool.value || !selectedTool.value.parameters) {
    return []
  }
  return formatParameters(selectedTool.value.parameters)
})

// 按来源分组的工具
const groupedTools = computed(() => {
  const groups = {}
  
  filteredTools.value.forEach(tool => {
    const source = tool.source || '未知来源'
    if (!groups[source]) {
      groups[source] = []
    }
    groups[source].push(tool)
  })
  
  // 按来源名称排序
  const sortedGroups = Object.keys(groups).sort().map(source => ({
    source,
    tools: groups[source]
  }))
  
  return sortedGroups
})

// API Methods
const loadBasicTools = async () => {
  try {
    loading.value = true
    const response = await getTools()
    console.log('Basic Tools Response:', response)
    if (response.tools) {
      allTools.value = response.tools
    }
  } catch (error) {
    console.error('Failed to load basic tools:', error)
  } finally {
    loading.value = false
  }
}

const loadMcpServers = async () => {
  try {
    loading.value = true
    const response = await getMcpServers()
    if (response.servers) {
      mcpServers.value = response.servers
    }
  } catch (error) {
    console.error('Failed to load MCP servers:', error)
  } finally {
    loading.value = false
  }
}

const toggleMcpServerStatus = async (server) => {
  try {
    const response = await toggleMcpServer(server.name)
    if (response.success) {
      // 更新本地状态
      const index = mcpServers.value.findIndex(s => s.name === server.name)
      if (index !== -1) {
        mcpServers.value[index].disabled = !mcpServers.value[index].disabled
      }
    }
  } catch (error) {
    console.error('Failed to toggle MCP server:', error)
  }
}

const deleteMcpServerHandler = async (server) => {
  if (!confirm(t('tools.confirmDeleteMcp', { name: server.name }))) {
    return
  }

  try {
    const response = await deleteMcpServer(server.name)
    if (response.success) {
      // 从本地列表中移除
      const index = mcpServers.value.findIndex(s => s.name === server.name)
      if (index !== -1) {
        mcpServers.value.splice(index, 1)
      }
    }
  } catch (error) {
    console.error('Failed to delete MCP server:', error)
  }
}

const handleMcpServerAdded = () => {
  loadMcpServers() // 重新加载MCP服务器列表
}

// Methods
const showAddMcpForm = () => {
  // 重置表单
  mcpForm.value = {
    name: '',
    protocol: 'sse',
    command: '',
    args: '',
    sse_url: '',
    streamable_http_url: '',
    description: ''
  }
  viewMode.value = 'add-mcp'
}

const handleSubmit = async () => {
  loading.value = true
  const mcpServerData = mcpForm.value
  try {
          const payload = {
    name: mcpServerData.name,
    protocol: mcpServerData.protocol,
    description: mcpServerData.description
  }

  // 根据协议类型添加相应字段
  if (mcpServerData.protocol === 'stdio') {
    payload.command = mcpServerData.command
    if (mcpServerData.args) {
      payload.args = Array.isArray(mcpServerData.args) 
        ? mcpServerData.args 
        : mcpServerData.args.split(' ').filter(arg => arg.trim())
    }
  } else if (mcpServerData.protocol === 'sse') {
    payload.sse_url = mcpServerData.sse_url
  } else if (mcpServerData.protocol === 'streamable_http') {
    payload.streamable_http_url = mcpServerData.streamable_http_url
  }
  
    await addMcpServer(payload)
    handleMcpServerAdded()
    backToList()
   } finally {
    loading.value = false
  }
}

const getToolTypeLabel = (type) => {
  const typeKey = `tools.type.${type}`
  return t(typeKey) !== typeKey ? t(typeKey) : type
}

const getToolSourceLabel = (source) => {
  // 直接映射中文source到翻译key
  const sourceMapping = {
    '基础工具': 'tools.source.basic',
    '内置工具': 'tools.source.builtin',
    '系统工具': 'tools.source.system'
  }

  const translationKey = sourceMapping[source]
  return translationKey ? t(translationKey) : source
}

const getToolIcon = (type) => {
  switch (type) {
    case 'basic':
      return Code
    case 'mcp':
      return Database
    case 'agent':
      return Cpu
    default:
      return Wrench
  }
}

const getToolTypeColor = (type) => {
  switch (type) {
    case 'basic':
      return '#4facfe'
    case 'mcp':
      return '#667eea'
    case 'agent':
      return '#ff6b6b'
    default:
      return '#4ade80'
  }
}

const getMcpServerDescription = (server) => {
  if (!server) return t('tools.noDescription')
  
  const protocol = server.protocol?.toUpperCase() || 'UNKNOWN'
  const status = server.disabled ? t('tools.disabled') : t('tools.enabled')
  
  if (server.streamable_http_url && server.sse_url) {
    return `${protocol} 协议服务器，支持 HTTP 和 SSE 连接 - ${status}`
  } else if (server.streamable_http_url) {
    return `${protocol} 协议服务器，支持 HTTP 连接 - ${status}`
  } else if (server.sse_url) {
    return `${protocol} 协议服务器，支持 SSE 连接 - ${status}`
  } else {
    return `${protocol} 协议服务器 - ${status}`
  }
}

// 新增方法：获取简化的服务器描述
const getSimpleDescription = (server) => {
  if (!server) return t('tools.noDescription')
  
  if (server.description) {
    return server.description
  }
  
  const protocol = server.protocol?.toUpperCase() || 'UNKNOWN'
  return `${protocol} 协议的 MCP 服务器，提供工具和资源访问能力`
}

// 新增方法：获取协议图标类名
const getProtocolIconClass = (protocol) => {
  switch (protocol?.toLowerCase()) {
    case 'sse':
      return 'protocol-sse'
    case 'streamable_http':
      return 'protocol-http'
    case 'stdio':
      return 'protocol-stdio'
    default:
      return 'protocol-default'
  }
}

// 新增方法：获取协议图标
const getProtocolIcon = (protocol) => {
  switch (protocol?.toLowerCase()) {
    case 'sse':
      return '⚡'
    case 'streamable_http':
      return '🌐'
    case 'stdio':
      return '💻'
    default:
      return '🔧'
  }
}

// 新增方法：格式化URL显示
const formatUrl = (url) => {
  if (!url) return ''
  try {
    const urlObj = new URL(url)
    return `${urlObj.hostname}:${urlObj.port || (urlObj.protocol === 'https:' ? '443' : '80')}`
  } catch {
    return url.length > 30 ? url.substring(0, 30) + '...' : url
  }
}

// 新增方法：获取服务器工具数量（模拟数据，实际应从API获取）
const getServerToolsCount = (server) => {
  // 这里应该从实际的API获取工具数量
  // 目前返回模拟数据
  return Math.floor(Math.random() * 10) + 1
}

// 新增方法：获取服务器参数数量（模拟数据，实际应从API获取）
const getServerParamsCount = (server) => {
  // 这里应该从实际的API获取参数数量
  // 目前返回模拟数据
  return Math.floor(Math.random() * 20) + 5
}

const maskApiKey = (apiKey) => {
  if (!apiKey) return ''
  if (apiKey.length <= 8) return '***'
  return apiKey.substring(0, 4) + '***' + apiKey.substring(apiKey.length - 4)
}

const formatParameters = (parameters) => {
  if (!parameters || typeof parameters !== 'object') {
    return []
  }

  return Object.entries(parameters).map(([key, value]) => {
    return {
      name: key,
      type: value.type || 'unknown',
      description: value.description || t('tools.noDescription'),
      required: value.required || false
    }
  })
}

const openToolDetail = (tool) => {
  selectedTool.value = tool
  viewMode.value = 'detail'
}

const backToList = () => {
  viewMode.value = 'list'
  selectedTool.value = null
}

// 生命周期
onMounted(() => {
  loadBasicTools()
  loadMcpServers()
})
</script>

<style scoped>
.tools-page {
  padding: 24px;
  width: 100%;
  min-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
}

.list-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 12px 0;
  overflow-y: auto;
  max-height: calc(100vh - 120px);
}

.tools-filters {
  flex-shrink: 0;
}

.tools-groups {
  flex: 1;
  overflow-y: auto;
  padding-right: 8px;
}

.tool-group {
  margin-bottom: 32px;
}

.group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 2px solid var(--border-color);
}

.group-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.group-count {
  font-size: 14px;
  color: var(--text-secondary);
  background: var(--background-secondary);
  padding: 4px 8px;
  border-radius: 12px;
}

.group-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent 0%, var(--border-color) 20%, var(--border-color) 80%, transparent 100%);
  margin: 24px 0;
  position: relative;
}

.group-divider::before {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 6px;
  height: 6px;
  background: var(--border-color);
  border-radius: 50%;
}

.tools-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.mcp-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.mcp-grid {
  flex: 1;
  overflow-y: auto;
  padding-right: 8px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 32px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--border-color);
}

.page-title h2 {
  margin: 0 0 8px 0;
  font-size: 28px;
  font-weight: 600;
  color: var(--text-primary);
}

.page-title p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 16px;
}

.tools-stats {
  display: flex;
  gap: 32px;
}

.stat-item {
  text-align: center;
}

.stat-number {
  display: block;
  font-size: 32px;
  font-weight: 700;
  color: var(--primary-color);
  line-height: 1;
}

.stat-label {
  display: block;
  font-size: 14px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.tools-filters {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  margin-bottom: 32px;
  flex-wrap: wrap;
}

.mcp-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.btn-primary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: rgb(255, 255, 255);
  color: rgb(0, 0, 0);
  border: none;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-primary:hover {
  background: var(--primary-color);
  color: rgb(255, 255, 255);
  transform: translateY(-1px);
}

.search-box {
  position: relative;
  flex: 1;
  min-width: 300px;
}

.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-secondary);
}

.search-input {
  width: 100%;
  padding: 12px 12px 12px 40px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 14px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  transition: all 0.2s ease;
}

.search-input:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px var(--primary-color-alpha);
}

.filter-tabs-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
}

.filter-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-tab {
  padding: 8px 16px;
  border: 1px solid var(--border-color);
  border-radius: 20px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.filter-tab:hover {
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.filter-tab.active {
  background: var(--primary-color);
  border-color: var(--primary-color);
  color: rgb(255, 255, 255);
}

.tools-section {
  flex: 1;
  overflow-y: auto;
  padding-right: 8px;
}

.mcp-section {
  flex: 1;
  overflow-y: auto;
  padding-right: 8px;
}

.tools-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 24px;
  margin-bottom: 32px;
}

.tool-card {
  background: var(--bg-secondary);
  border: 2px solid var(--border-color);
  border-radius: 12px;
  padding: 20px;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.tool-card:hover {
  border-color: var(--primary-color);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.1);
}

.tool-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.tool-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.tool-info {
  flex: 1;
  min-width: 0;
}

.tool-name {
  margin: 0 0 8px 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  word-break: break-word;
}

.tool-description {
  margin: 0;
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tool-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.meta-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
}

.meta-label {
  color: var(--text-secondary);
  font-weight: 500;
}

.meta-value {
  color: var(--text-primary);
  font-weight: 600;
}

.empty-state {
  text-align: center;
  padding: 64px 24px;
  color: var(--text-secondary);
}

.empty-icon {
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-state h3 {
  margin: 0 0 8px 0;
  font-size: 20px;
  color: var(--text-primary);
}

.empty-state p {
  margin: 0;
  font-size: 16px;
}

/* 分组样式 */
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-color);
}

.section-header h3 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

.tool-type-filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.type-filter {
  padding: 6px 12px;
  border: 1px solid var(--border-color);
  border-radius: 16px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.type-filter:hover {
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.type-filter.active {
  background: var(--primary-color);
  border-color: var(--primary-color);
  color: white;
}

/* MCP服务器样式 */
.mcp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 24px;
  margin-bottom: 32px;
}

.mcp-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 24px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.mcp-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.mcp-card:hover {
  border-color: var(--primary-color);
  box-shadow: 0 8px 25px rgba(59, 130, 246, 0.15);
  transform: translateY(-4px);
}

.mcp-card:hover::before {
  opacity: 1;
}

.mcp-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.mcp-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
}

.mcp-info {
  flex: 1;
  min-width: 0;
}

.mcp-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.mcp-name {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  word-break: break-word;
  line-height: 1.3;
}

.mcp-description {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0 0 12px 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.mcp-status-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  background: #dcfce7;
  color: #166534;
}

.mcp-status-indicator.disabled {
  background: #fef2f2;
  color: #991b1b;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

.mcp-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.action-btn {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn:hover {
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.action-btn.delete:hover {
  border-color: #ef4444;
  color: #ef4444;
  background: #fef2f2;
}

.mcp-protocol-section {
  margin-bottom: 16px;
}

.protocol-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.protocol-icon {
  font-size: 14px;
}

.protocol-details {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.connection-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.connection-label {
  color: var(--text-secondary);
  font-weight: 500;
  min-width: 40px;
}

.connection-url {
  color: var(--text-primary);
  font-family: monospace;
  background: var(--bg-primary);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  word-break: break-all;
  flex: 1;
}

.mcp-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 12px;
}

.stat-icon {
  color: var(--text-secondary);
  flex-shrink: 0;
}

.stat-label {
  color: var(--text-secondary);
  font-weight: 500;
  flex: 1;
}

.stat-value {
  color: var(--text-primary);
  font-weight: 600;
}

.stat-value.api-key {
  font-family: monospace;
  font-size: 11px;
}

/* 响应式设计 */
@media (max-width: 1200px) {
  .mcp-grid {
    grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
  }
}

@media (max-width: 768px) {
  .tools-page {
    padding: 16px;
  }
  
  .mcp-card {
    padding: 20px;
  }
  
  .mcp-grid {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  
  .mcp-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }
  
  .mcp-icon {
    width: 40px;
    height: 40px;
    margin-right: 0;
    margin-bottom: 8px;
  }
  
  .mcp-actions {
    width: 100%;
    justify-content: flex-end;
  }
  
  .mcp-stats {
    grid-template-columns: 1fr;
    gap: 8px;
  }
  
  .protocol-details {
    gap: 8px;
  }
  
  .connection-info {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }
  
  .connection-label {
    min-width: auto;
    font-weight: 600;
  }
}

@media (max-width: 480px) {
  .tools-page {
    padding: 12px;
  }
  
  .mcp-card {
    padding: 16px;
  }
  
  .mcp-name {
    font-size: 16px;
  }
  
  .mcp-description {
    font-size: 13px;
  }
  
  .action-btn {
    padding: 6px 10px;
    font-size: 11px;
  }
}

/* 改进的交互效果 */
.mcp-card {
  position: relative;
  overflow: hidden;
}

.mcp-card:hover::after {
  left: 100%;
}

.action-btn {
  position: relative;
  overflow: hidden;
}

.action-btn::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 0;
  height: 0;
  background: rgba(59, 130, 246, 0.1);
  border-radius: 50%;
  transform: translate(-50%, -50%);
  transition: width 0.3s ease, height 0.3s ease;
}

.action-btn:hover::before {
  width: 100px;
  height: 100px;
}

.action-btn:active {
  transform: scale(0.95);
}

.mcp-status-indicator {
  transition: all 0.3s ease;
}

.mcp-status-indicator:hover {
  transform: scale(1.05);
}

.protocol-badge {
  transition: all 0.3s ease;
}

.protocol-badge:hover {
  background: var(--primary-color);
  color: white;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
}

.stat-item {
  transition: all 0.3s ease;
}

.stat-item:hover {
  background: var(--primary-color);
  color: white;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.2);
}

.stat-item:hover .stat-icon,
.stat-item:hover .stat-label {
  color: white;
}

/* 加载动画 */
@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

.mcp-card.loading {
  animation: pulse 1.5s ease-in-out infinite;
}

/* 焦点样式 */
.action-btn:focus {
  outline: 2px solid var(--primary-color);
  outline-offset: 2px;
}

.mcp-card:focus-within {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

/* 深色模式支持 */
@media (prefers-color-scheme: dark) {
  .mcp-card::after {
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
  }
  
  .protocol-badge:hover {
    background: #4f46e5;
  }
  
  .stat-item:hover {
    background: #4f46e5;
  }
}

/* 工具详情视图样式 */
.tool-detail-view {
  background: var(--bg-primary);
  border-radius: 12px;
  overflow: hidden;
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px 0;
}

/* 工具详情页面样式 */
.detail-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 24px 24px 24px 24px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-primary);
  flex-shrink: 0;
}

.back-button {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 14px;
}

.back-button:hover {
  background: var(--bg-primary);
  transform: translateY(-1px);
}

.detail-tool-info {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
}

.detail-tool-icon {
  width: 64px;
  height: 64px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
  font-size: 24px;
}

.detail-tool-meta h1 {
  margin: 0 0 8px 0;
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
}

.detail-tool-type {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  color: white;
}

.tool-detail-content {
  display: flex;
  flex-direction: column;
  gap: 32px;
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.tool-section {
  background: var(--bg-secondary);
  border-radius: 12px;
  padding: 12px;
}

.tool-section h3 {
  margin: 0 0 16px 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-section p {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.6;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.info-value {
  font-size: 14px;
  color: var(--text-primary);
  font-weight: 500;
}

.params-table-container {
  overflow-x: auto;
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.params-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--bg-primary);
}

.params-table th {
  background: var(--bg-secondary);
  padding: 12px 16px;
  text-align: left;
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-color);
}

.params-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  font-size: 14px;
  vertical-align: top;
}

.params-table tbody tr:last-child td {
  border-bottom: none;
}

.params-table tbody tr:hover {
  background: var(--bg-hover);
}

.params-table .param-name {
  font-family: monospace;
  font-weight: 600;
  color: var(--text-primary);
}

.params-table .param-type {
  color: var(--text-secondary);
  line-height: 1.5;
  max-width: 300px;
  word-wrap: break-word;
}

.params-table .param-required .required-yes {
  color: #e74c3c;
  font-weight: 600;
}

.params-table .param-required .required-no {
  color: var(--text-secondary);
}

.params-table .param-description {
  color: var(--text-secondary);
  line-height: 1.5;
  max-width: 300px;
  word-wrap: break-word;
}

.config-display {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 16px;
  font-family: monospace;
  font-size: 12px;
  color: var(--text-primary);
  white-space: pre-wrap;
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
}

/* 表单样式 */
.add-mcp-form {
  width: 100%;
  max-width: 800px;
  margin: 0 auto;
  
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 24px;
  margin-bottom: 24px;
  justify-items: center;
  
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  max-width: 500px;
}

.form-group label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  text-align: center;
}

.form-input,
.form-select,
.form-textarea {
  padding: 12px 16px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 14px;
  color: var(--text-primary);
  transition: all 0.2s ease;
  text-align: center;
}

.form-input:focus,
.form-select:focus,
.form-textarea:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px var(--primary-color-alpha);
}

.form-textarea {
  resize: vertical;
  min-height: 100px;
  text-align: left;
}

.form-actions {
  display: flex;
  gap: 16px;
  justify-content: center;
  margin: 32px auto 0;
  padding-top: 24px;
  border-top: 1px solid var(--border-color);
}

.add-mcp-view {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  padding-bottom: 40px;
    overflow-y: auto;
  max-height: calc(100vh - 50px);
}

.add-mcp-view .tool-detail-content {
  width: 100%;
  max-width: 600px;
  margin: 0 auto;
}

.btn-secondary {
  padding: 12px 24px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-secondary:hover {
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.animate-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}
</style>