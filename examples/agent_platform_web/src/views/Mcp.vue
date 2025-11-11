<template>
<div class="mcp-page">
      <!-- 列表视图的过滤器和内容 -->
  <div v-if="viewMode === 'list'"  class="list-content">
    <div  class="mcp-actions">
        <button class="btn-primary" @click="showAddMcpForm">
          <Plus :size="16" />
          {{ t('tools.addMcpServer') }}
        </button>
    </div>
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
                <div class="mcp-actions">
                  <button 
                    class="action-btn refresh-btn" 
                    @click="handleRefreshMcp(server.name)"
                    :disabled="loading"
                    :title="t('tools.refresh')"
                  >
                    <RefreshCw :size="16" :class="{ 'spinning': refreshingServers.has(server.name) }" />
                  </button>
                  <div class="mcp-status-indicator" :class="{ disabled: server.disabled }">
                    <div class="status-dot"></div>
                    <span class="status-text">{{ server.disabled ? t('tools.disabled') : t('tools.enabled') }}</span>
                  </div>
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
                <span class="connection-label">URL:</span>
                <span class="connection-url">{{ server.streamable_http_url }}</span>
              </div>
              <div v-if="server.sse_url" class="connection-info">
                <span class="connection-label">URL:</span>
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
    <div v-if="filteredMcpServers.length === 0" class="empty-state">
        <Wrench :size="48" class="empty-icon" />
        <h3>{{ t('tools.noMcpServers') }}</h3>
        <p>{{ t('tools.noMcpServersDesc') }}</p>
      </div>
  </div>
  <!-- MCP服务器添加视图 -->
  <McpServerAdd v-if="viewMode === 'add-mcp'" :loading="loading" @submit="handleMcpSubmit" @cancel="backToList"
    ref="mcpServerAddRef" />
</div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Wrench,Code, Database,  Cpu, Plus, RefreshCw } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { toolAPI } from '../api/tool.js'
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
const viewMode = ref('list') // 'list', 'detail', 'add-mcp'
const loading = ref(false)
const refreshingServers = ref(new Set())

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


// API Methods
const loadBasicTools = async () => {
  try {
    loading.value = true
    const response = await toolAPI.getTools()
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
    const response = await toolAPI.getMcpServers()
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
    await toolAPI.addMcpServer(payload)
    loadMcpServers() // 重新加载MCP服务器列表
    backToList()
  } catch (error) {
    console.error('Failed to add MCP server:', error)
  } finally {
    loading.value = false
  }
}

const handleRefreshMcp = async (serverName) => {
  if (refreshingServers.value.has(serverName)) {
    return // 防止重复刷新
  }
  
  refreshingServers.value.add(serverName)
  
  try {
    await toolAPI.refreshMcpServer(serverName)
  } catch (error) {
    console.error(`Failed to refresh MCP server ${serverName}:`, error)
    // 即使出错也重新加载列表，以防服务器状态已经改变
  } finally {
    await loadMcpServers()
    refreshingServers.value.delete(serverName)
  }
}

// 新增方法：获取简化的服务器描述
const getSimpleDescription = (server) => {
  if (!server) return t('tools.noDescription')
  return server.description
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

.mcp-page {
  padding: 1.5rem;
  min-height: 100vh;
  background: transparent;
}
.list-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  max-height: calc(100vh - 120px);
  background: white;
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
  background: #667eea;
  color: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-primary:hover {
  background: #5a6fd8;
}



.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px 32px;
  text-align: center;
  color: rgba(0, 0, 0, 0.7);
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



.mcp-grid {
  padding: 24px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 20px;
}

.mcp-card {
  background: white;
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 12px;
  padding: 20px;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.mcp-card:hover {
  border-color: #667eea;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
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

.mcp-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 6px;
  background: rgba(102, 126, 234, 0.1);
  color: #667eea;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.action-btn:hover:not(:disabled) {
  background: rgba(102, 126, 234, 0.2);
  transform: scale(1.05);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.refresh-btn .spinning {
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

.mcp-name {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #333333;
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
  color: rgba(0, 0, 0, 0.7);
}

.mcp-description {
  margin: 0;
  font-size: 14px;
  color: rgba(0, 0, 0, 0.7);
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
  border-top: 1px solid rgba(0, 0, 0, 0.1);
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
  color: rgba(0, 0, 0, 0.7);
  min-width: 40px;
}

.connection-url {
  color: #333333;
  font-family: monospace;
  word-break: break-all;
  flex: 1;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px 32px;
  text-align: center;
  color: rgba(0, 0, 0, 0.7);
}

.empty-state h3 {
  margin: 0 0 8px 0;
  font-size: 18px;
  font-weight: 600;
  color: #333333;
}

.empty-state p {
  margin: 0;
  font-size: 14px;
  line-height: 1.5;
  color: rgba(0, 0, 0, 0.7);
}
</style>