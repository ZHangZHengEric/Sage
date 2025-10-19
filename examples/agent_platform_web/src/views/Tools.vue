<template>
  <!-- 列表视图的过滤器和内容 -->
  <div v-if="viewMode === 'list'" class="list-content">
    <div class="filter-tabs-row">
      <div class="filter-tabs">
        <button :class="['filter-tab', { active: activeTab === 'tools' }]"
          @click="activeTab = 'tools', viewMode = 'list'">
          {{ t('tools.Tools') }}
        </button>
        <button :class="['filter-tab', { active: activeTab === 'mcp' }]" @click="activeTab = 'mcp', viewMode = 'list'">
          {{ t('tools.mcpServers') }}
        </button>
      </div>
      <div class="search-box">
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
                <span class="connection-url">{{ server.streamable_http_url }}</span>
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
  <ToolDetail v-if="viewMode === 'detail' && selectedTool" :tool="selectedTool" @back="backToList" />

  <!-- MCP服务器添加视图 -->
  <McpServerAdd v-if="viewMode === 'add-mcp'" :loading="loading" @submit="handleMcpSubmit" @cancel="backToList"
    ref="mcpServerAddRef" />
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Wrench, Search, Code, Database, Globe, Cpu, Plus } from 'lucide-vue-next'
import { useLanguage } from '../utils/language'
import { getTools, getMcpServers, addMcpServer } from '../api/modules/tool'
import ToolDetail from '../components/ToolDetail.vue'
import McpServerAdd from '../components/McpServerAdd.vue'

// Composables
const { t } = useLanguage()

// Refs
const mcpServerAddRef = ref(null)

// State
const allTools = ref([])
const mcpServers = ref([])
const selectedTool = ref(null)
const searchTerm = ref('')
const filterType = ref('all')
const activeTab = ref('tools')
const viewMode = ref('list') // 'list', 'detail', 'add-mcp'
const loading = ref(false)

// Computed
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

// Methods
const showAddMcpForm = () => {
  // 重置表单
  if (mcpServerAddRef.value) {
    mcpServerAddRef.value.resetForm()
  }
  viewMode.value = 'add-mcp'
}

const handleMcpSubmit = async (payload) => {
  loading.value = true
  try {
    await addMcpServer(payload)
    loadMcpServers() // 重新加载MCP服务器列表
    backToList()
  } catch (error) {
    console.error('Failed to add MCP server:', error)
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
.list-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  max-height: calc(100vh - 120px);
}

.tools-filters {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
  padding: 16px 0;
  border-bottom: 1px solid var(--border-color);
}

.filter-tabs-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  padding: 16px 0;
  border-bottom: 1px solid var(--border-color);
  flex-wrap: wrap;
  gap: 16px;
}

.filter-tabs {
  display: flex;
  gap: 8px;
}

.filter-tab {
  padding: 8px 16px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.filter-tab:hover {
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.filter-tab.active {
  background: var(--primary-color);
  border-color: var(--primary-color);
  color: white;
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
  flex: 1;
  max-width: 400px;
}

.search-icon {
  position: absolute;
  left: 12px;
  color: var(--text-secondary);
  z-index: 1;
}

.search-input {
  width: 100%;
  padding: 10px 12px 10px 40px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 14px;
  color: var(--text-primary);
  background: var(--bg-primary);
  transition: all 0.2s ease;
}

.search-input:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px var(--primary-color-alpha);
}

.mcp-actions {
  display: flex;
  gap: 12px;
}

.btn-primary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border: none;
  border-radius: 8px;
  background: var(--primary-color);
  color: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-primary:hover {
  background: var(--primary-color-hover);
}

.tools-section {
  flex: 1;
  overflow-y: auto;
}

.tools-groups {
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.tool-group {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 12px;
  border-bottom: 2px solid var(--border-color);
}

.group-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}

.group-count {
  font-size: 14px;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  padding: 4px 12px;
  border-radius: 12px;
  border: 1px solid var(--border-color);
}

.tools-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 20px;
}

.tool-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 20px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tool-card:hover {
  border-color: var(--primary-color);
  box-shadow: 0 4px 12px var(--shadow-color);
  transform: translateY(-2px);
}

.tool-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.tool-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
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
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  word-break: break-word;
}

.tool-description {
  margin: 0;
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tool-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--border-color);
}

.meta-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
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
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px 32px;
  text-align: center;
  color: var(--text-secondary);
}

.empty-icon {
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-state h3 {
  margin: 0 0 8px 0;
  font-size: 18px;
  font-weight: 600;
}

.empty-state p {
  margin: 0;
  font-size: 14px;
  line-height: 1.5;
}

/* MCP 服务器样式 */
.mcp-section {
  flex: 1;
  overflow-y: auto;
}

.mcp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 20px;
}

.mcp-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 20px;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.mcp-card:hover {
  border-color: var(--primary-color);
  box-shadow: 0 4px 12px var(--shadow-color);
  transform: translateY(-2px);
}

.mcp-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.mcp-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.mcp-icon.protocol-sse {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.mcp-icon.protocol-http {
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
}

.mcp-icon.protocol-stdio {
  background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
}

.mcp-icon.protocol-default {
  background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
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
  gap: 12px;
}

.mcp-name {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  word-break: break-word;
}

.mcp-status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #4ade80;
}

.mcp-status-indicator.disabled .status-dot {
  background: #ef4444;
}

.status-text {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
}

.mcp-description {
  margin: 0;
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.mcp-protocol-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border-color);
}

.protocol-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  width: fit-content;
}

.protocol-badge.sse {
  background: rgba(102, 126, 234, 0.1);
  color: #667eea;
  border: 1px solid rgba(102, 126, 234, 0.2);
}

.protocol-badge.streamable_http {
  background: rgba(79, 172, 254, 0.1);
  color: #4facfe;
  border: 1px solid rgba(79, 172, 254, 0.2);
}

.protocol-badge.stdio {
  background: rgba(67, 233, 123, 0.1);
  color: #43e97b;
  border: 1px solid rgba(67, 233, 123, 0.2);
}

.protocol-icon {
  font-size: 14px;
}

.protocol-name {
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.protocol-details {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.connection-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.connection-label {
  font-weight: 600;
  color: var(--text-secondary);
  min-width: 40px;
}

.connection-url {
  color: var(--text-primary);
  font-family: monospace;
  word-break: break-all;
  flex: 1;
}
</style>