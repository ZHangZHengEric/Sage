<template>
  <div class="tool-page">
      <!-- 列表视图的过滤器和内容 -->
  <div v-if="viewMode === 'list'" class="list-content">
    <div class="filter-tabs-row">
      <div class="search-box">
        <Search :size="16" class="search-icon" />
        <input type="text" class="input search-input"
          :placeholder="t('tools.search')" v-model="searchTerm" />
      </div>
    </div>
    <!-- 工具列表 -->
    <div class="tools-section">
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
  </div>
  <!-- 工具详情视图 -->
  <ToolDetail v-if="viewMode === 'detail' && selectedTool" :tool="selectedTool" @back="backToList" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Wrench, Search, Code, Database, Globe, Cpu, Plus } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { toolAPI } from '../api/tool.js'
import ToolDetail from '../components/ToolDetail.vue'

// Composables
const { t } = useLanguage()


// State
const allTools = ref([])
const mcpServers = ref([])
const selectedTool = ref(null)
const searchTerm = ref('')
const filterType = ref('all')
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
.tool-page {
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
  background: transparent;
}


.filter-tabs-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 10px 10px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  flex-wrap: wrap;
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
  color: rgba(255, 255, 255, 0.7);
  z-index: 1;
}

.search-input {
  width: 100%;
  padding: 10px 12px 10px 40px;
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 8px;
  font-size: 14px;
  color: #333333;
  background: rgba(255, 255, 255, 0.9);
  transition: all 0.2s ease;
}

.search-input:focus {
  outline: none;
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
  background: white;
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
  border-bottom: 2px solid rgba(0, 0, 0, 0.1);
}

.group-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #333333;
}

.group-count {
  font-size: 14px;
  color: rgba(0, 0, 0, 0.7);
  background: #f5f5f5;
  padding: 4px 12px;
  border-radius: 12px;
  border: 1px solid rgba(0, 0, 0, 0.1);
}

.tools-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 20px;
}

.tool-card {
  background: white;
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 12px;
  padding: 20px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tool-card:hover {
  border-color: #667eea;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
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
  color: #333333;
  word-break: break-word;
}

.tool-description {
  margin: 0;
  font-size: 14px;
  color: rgba(0, 0, 0, 0.7);
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
  border-top: 1px solid rgba(0, 0, 0, 0.1);
}

.meta-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}

.meta-label {
  color: rgba(0, 0, 0, 0.7);
  font-weight: 500;
}

.meta-value {
  color: #333333;
  font-weight: 600;
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
  color: #333333;
}

.empty-state p {
  margin: 0;
  font-size: 14px;
  line-height: 1.5;
  color: rgba(0, 0, 0, 0.7);
}


</style>