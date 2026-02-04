<template>
  <div class="h-screen w-full bg-background p-6">
    <!-- 列表视图 -->
    <div v-if="viewMode === 'list'" class="flex h-full flex-col space-y-6">
      <!-- 头部搜索区 -->
      <div class="flex items-center justify-between pb-4 border-b">
        <div class="flex items-center justify-between">
          <Input v-model="searchTerm" :placeholder="t('tools.search')" class="pl-9" />
        </div>
        <Button @click="showAddMcpForm">
          <Plus class="mr-2 h-4 w-4" />
          {{ t('tools.addMcpServer') }}
        </Button>
      </div>

      <!-- 工具列表 -->
      <ScrollArea class="flex-1">
        <div class="space-y-8 pr-4">
          <!-- Loading -->
          <div v-if="loading" class="flex flex-col items-center justify-center py-20">
            <Loader class="h-8 w-8 animate-spin text-primary" />
          </div>

          <!-- 空状态 -->
          <div v-else-if="filteredTools.length === 0" class="flex flex-col items-center justify-center py-12 text-center">
            <div class="rounded-full bg-muted p-4">
              <Wrench class="h-8 w-8 text-muted-foreground" />
            </div>
            <h3 class="mt-4 text-lg font-semibold">{{ t('tools.noTools') }}</h3>
            <p class="text-sm text-muted-foreground">{{ t('tools.noToolsDesc') }}</p>
          </div>

          <!-- 分组展示 -->
          <div v-else v-for="(group, groupIndex) in groupedTools" :key="group.source" class="space-y-4">
            <div class="flex items-center justify-between">
              <div class="flex">
                <h3 class="text-lg font-semibold tracking-tight">{{ getToolSourceLabel(group.source) }}</h3>
                <div v-if="canManage(group.tools[0])" class="flex items-center ml-2 space-x-1">
                  <Button variant="ghost" size="icon"
                    class="h-6 w-6 text-muted-foreground hover:text-primary shrink-0"
                    @click.stop="handleRefreshMcpTool(group.source)" :title="t('tools.refresh') || 'Refresh Server'">
                    <RefreshCw class="h-3.5 w-3.5" />
                  </Button>
                  <Button variant="ghost" size="icon"
                    class="h-6 w-6 text-destructive hover:text-destructive shrink-0"
                    @click.stop="handleDeleteMcpTool(group.source)" :title="t('tools.delete') || 'Delete Server'">
                    <Trash2 class="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>


              <Badge variant="secondary" class="rounded-sm px-2 font-normal">
                {{ group.tools.length }} {{ t('tools.count') }}
              </Badge>
            </div>

            <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              <Card 
                v-for="tool in group.tools" 
                :key="tool.name" 
                class="cursor-pointer transition-all hover:shadow-md hover:-translate-y-0.5 group"
                @click="openToolDetail(tool)"
              >
                <CardHeader class="flex flex-row items-start gap-4 space-y-0 pb-2">
                  <div 
                    class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-white shadow-sm transition-opacity group-hover:opacity-90"
                    :class="getToolTypeColorClass(tool.type)"
                  >
                    <component :is="getToolIcon(tool.type)" class="h-5 w-5" />
                  </div>
                  <div class="space-y-1 overflow-hidden flex-1">
                    <div class="flex items-center justify-between gap-2">
                      <CardTitle class="text-base truncate" :title="tool.name">
                        {{ tool.name }}
                      </CardTitle>
   
                    </div>
                    <CardDescription class="line-clamp-2 text-xs">
                      {{ tool.description || t('tools.noDescription') }}
                    </CardDescription>
                  </div>
                </CardHeader>
                <CardContent>
                  <div class="flex items-center justify-between pt-4 border-t mt-2 text-xs text-muted-foreground">
                    <div class="flex items-center gap-1">
                      <span>{{ t('tools.source') }}:</span>
                      <span class="font-medium text-foreground">{{ getToolSourceLabel(tool.source) }}</span>
                    </div>
                    <div class="flex items-center gap-1">
                      <span>{{ t('tools.params') }}:</span>
                      <span class="font-medium text-foreground">{{ formatParameters(tool.parameters).length }}</span>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </ScrollArea>
    </div>

    <!-- 详情视图 -->
    <ToolDetail 
      v-if="viewMode === 'detail' && selectedTool" 
      :tool="selectedTool" 
      @back="backToList" 
    />

    <!-- MCP服务器添加视图 -->
    <McpServerAdd 
      v-if="viewMode === 'add-mcp'" 
      :loading="loading" 
      @submit="handleMcpSubmit" 
      @cancel="backToList"
      ref="mcpServerAddRef" 
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Wrench, Search, Code, Database, Globe, Cpu, Plus, Trash2, Loader, RefreshCw } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { toolAPI } from '../api/tool.js'
import { getCurrentUser } from '../utils/auth.js'
import ToolDetail from '../components/ToolDetail.vue'
import McpServerAdd from '../components/McpServerAdd.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'

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
const mcpServerAddRef = ref(null)
const currentUser = ref({ userid: '', role: 'user' })

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

const showAddMcpForm = () => {
  if (mcpServerAddRef.value) {
    mcpServerAddRef.value.resetForm()
  }
  viewMode.value = 'add-mcp'
}

const handleMcpSubmit = async (payload) => {
  loading.value = true
  try {
    await toolAPI.addMcpServer(payload)
    await loadMcpServers()
    await loadBasicTools()
    backToList()
  } catch (error) {
    console.error('Failed to add MCP server:', error)
  } finally {
    loading.value = false
  }
}

const canManage = (tool) => {
  if (tool.type !== 'mcp') return false
  if (currentUser.value.role === 'admin') return true
  const server = mcpServers.value.find(s => 'MCP Server: ' + s.name  === tool.source)
  if (!server || !server.user_id) return false
  return server.user_id === currentUser.value.userid
}

const handleDeleteMcpTool = async (sourceName) => {
  if (!confirm(t('tools.confirmDelete') || 'Are you sure you want to remove this MCP server?')) {
    return
  }

  const serverName = sourceName.startsWith('MCP Server: ') ? sourceName.substring('MCP Server: '.length) : sourceName

  try {
    loading.value = true
    await toolAPI.removeMcpServer(serverName)
    toast.success(t('tools.deleteSuccess') || 'Server removed successfully')
    await loadBasicTools()
  } catch (error) {
    console.error('Failed to remove MCP server:', error)
    toast.error(error.message || t('tools.deleteFailed') || 'Failed to remove server')
  } finally {
    loading.value = false
  }
}

const handleRefreshMcpTool = async (sourceName) => {
  const serverName = sourceName.startsWith('MCP Server: ') ? sourceName.substring('MCP Server: '.length) : sourceName

  try {
    loading.value = true
    await toolAPI.refreshMcpServer(serverName)
    toast.success(t('tools.refreshSuccess') || 'Server refreshed successfully')
    await loadBasicTools()
  } catch (error) {
    console.error('Failed to refresh MCP server:', error)
    toast.error(error.message || t('tools.refreshFailed') || 'Failed to refresh server')
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

const getToolTypeColorClass = (type) => {
  switch (type) {
    case 'basic':
      return 'bg-blue-500'
    case 'mcp':
      return 'bg-indigo-500'
    case 'agent':
      return 'bg-red-500'
    default:
      return 'bg-green-500'
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
onMounted(async () => {
  const user = await getCurrentUser()
  if (user) {
    currentUser.value = user
  }
  loadBasicTools()
  loadMcpServers()
})
</script>
