<template>
  <div class="h-screen w-full bg-background p-6">
    <!-- 列表视图 -->
    <div v-if="viewMode === 'list'" class="flex h-full flex-col space-y-6">
      <!-- 头部操作区 -->
      <div class="flex items-center justify-between pb-4 border-b">
        <div class="relative w-full max-w-sm">
          <Search class="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input 
            v-model="searchTerm" 
            :placeholder="t('tools.search')" 
            class="pl-9"
          />
        </div>
        <Button @click="showAddMcpForm">
          <Plus class="mr-2 h-4 w-4" />
          {{ t('tools.addMcpServer') }}
        </Button>
      </div>

      <!-- MCP服务器列表 -->
      <ScrollArea class="flex-1">
        <div class="space-y-6 pr-4">
          <div v-if="filteredMcpServers.length > 0" class="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            <Card 
              v-for="server in filteredMcpServers" 
              :key="server.name" 
              class="transition-all hover:shadow-md hover:-translate-y-0.5"
            >
              <CardHeader class="flex flex-row items-start gap-4 space-y-0 pb-2">
                <div 
                  class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-white shadow-sm"
                  :class="getProtocolIconClass(server.protocol)"
                >
                  <Database class="h-5 w-5" />
                </div>
                <div class="space-y-1 overflow-hidden flex-1">
                  <div class="flex items-center justify-between">
                    <CardTitle class="text-base truncate" :title="server.name">
                      {{ server.name }}
                    </CardTitle>
                    <div class="flex items-center gap-1">
                      <Button 
                        variant="ghost" 
                        size="icon" 
                        class="h-6 w-6" 
                        :disabled="loading"
                        :title="t('tools.refresh')"
                        @click="handleRefreshMcp(server.name)"
                      >
                        <RefreshCw 
                          class="h-3.5 w-3.5" 
                          :class="{ 'animate-spin': refreshingServers.has(server.name) }" 
                        />
                      </Button>
                      <Button 
                        variant="ghost" 
                        size="icon" 
                        class="h-6 w-6 text-destructive hover:text-destructive" 
                        :disabled="loading"
                        :title="t('tools.delete')"
                        @click="handleDeleteMcp(server.name)"
                      >
                        <Trash2 class="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                  <CardDescription class="line-clamp-2 text-xs">
                    {{ getSimpleDescription(server) }}
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                <div class="flex flex-col gap-2 pt-4 border-t mt-2">
                  <div class="flex items-center justify-between">
                    <Badge variant="outline" class="uppercase text-[10px] font-mono">
                      {{ server.protocol?.toUpperCase() || 'UNKNOWN' }}
                    </Badge>
                    <div class="flex items-center gap-1.5">
                      <div class="h-2 w-2 rounded-full" :class="server.disabled ? 'bg-muted-foreground' : 'bg-green-500'"></div>
                      <span class="text-xs text-muted-foreground">{{ server.disabled ? t('tools.disabled') : t('tools.enabled') }}</span>
                    </div>
                  </div>
                  
                  <div class="text-xs text-muted-foreground font-mono truncate bg-muted/50 p-1.5 rounded">
                    {{ getServerUrl(server) }}
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          <div v-else class="flex flex-col items-center justify-center py-12 text-center">
            <div class="rounded-full bg-muted p-4">
              <Wrench class="h-8 w-8 text-muted-foreground" />
            </div>
            <h3 class="mt-4 text-lg font-semibold">{{ t('tools.noMcpServers') }}</h3>
            <p class="text-sm text-muted-foreground">{{ t('tools.noMcpServersDesc') }}</p>
          </div>
        </div>
      </ScrollArea>
    </div>

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
import { Wrench, Search, Code, Database, Globe, Cpu, Plus, RefreshCw, Trash2 } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { toolAPI } from '../api/tool.js'
import McpServerAdd from '../components/McpServerAdd.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'

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

const backToList = () => {
  viewMode.value = 'list'
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

const handleDeleteMcp = async (serverName) => {
  try {
    loading.value = true
    await toolAPI.deleteMcpServer(serverName)
  } catch (error) {
    console.error(`Failed to delete MCP server ${serverName}:`, error)
  } finally {
    await loadMcpServers()
    loading.value = false
  }
}

const getProtocolIconClass = (protocol) => {
  switch (protocol) {
    case 'stdio':
      return 'bg-blue-500'
    case 'sse':
      return 'bg-green-500'
    case 'streamable_http':
      return 'bg-purple-500'
    default:
      return 'bg-gray-500'
  }
}

const getSimpleDescription = (server) => {
  if (server.description) return server.description
  return t('tools.noDescription')
}

const getServerUrl = (server) => {
  if (server.streamable_http_url) return server.streamable_http_url
  if (server.sse_url) return server.sse_url
  if (server.command) return `${server.command} ${server.args || ''}`
  return 'N/A'
}

onMounted(() => {
  loadMcpServers()
})
</script>
