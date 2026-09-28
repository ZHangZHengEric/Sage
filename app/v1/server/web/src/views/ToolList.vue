<template>
  <div class="h-full w-full bg-background flex flex-col overflow-hidden">
    <!-- Header Area -->
    <div class="flex-none bg-background border-b">
  

      <!-- Source Groups Grid -->
      <Collapsible
        v-model:open="isGridExpanded"
        class="flex flex-col border-b bg-background py-2"
      >
        <div class="px-6 py-2 flex items-center justify-begin">
           <span class="text-sm font-medium text-muted-foreground">{{ t('tools.sourceGroups') || 'Source Groups' }}</span>
           <CollapsibleTrigger as-child>
            <Button variant="ghost" size="sm" class="h-8 w-8 p-0">
              <ChevronDown v-if="!isGridExpanded" class="h-4 w-4" />
              <ChevronUp v-else class="h-4 w-4" />
              <span class="sr-only">Toggle Grid</span>
            </Button>
          </CollapsibleTrigger>
        </div>
        
        <CollapsibleContent class="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
           <div class="px-6 pb-6">
            <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-4">
              <!-- Dynamic Groups -->
              <div
                v-for="group in groupedTools"
                :key="group.source"
                class="relative flex flex-col gap-2 p-3 rounded-xl border transition-all duration-200 cursor-pointer hover:shadow-md group"
                :class="[
                  selectedGroupSource === group.source 
                    ? 'bg-primary/5 border-primary ring-1 ring-primary/20' 
                    : 'bg-card border-border hover:border-primary/50',
                  group.disabled ? 'opacity-60 grayscale' : ''
                ]"
                @click="selectedGroupSource = group.source"
              >
                <div class="flex items-center gap-2">
                  <div 
                    class="p-1.5 rounded-md transition-colors shrink-0"
                    :class="selectedGroupSource === group.source ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground group-hover:text-primary group-hover:bg-primary/10'"
                  >
                    <component :is="getGroupIcon(group.source)" class="h-4 w-4" />
                  </div>
                  <h3 class="font-medium text-sm truncate flex-1" :title="getToolSourceLabel(group.source)">
                    {{ getToolSourceLabel(group.source) }}
                  </h3>
                  <Badge v-if="group.source.startsWith('内置MCP:')" variant="outline" class="h-5 px-1.5 text-[10px] shrink-0">
                    {{ t('tools.builtin') || 'Built-in' }}
                  </Badge>
                  <Badge v-if="group.disabled" variant="destructive" class="h-5 px-1.5 text-[10px] shrink-0">
                    {{ t('tools.disabled') || 'Disabled' }}
                  </Badge>
                  <Badge v-else variant="secondary" class="h-5 px-1.5 text-[10px] bg-background/80 backdrop-blur shrink-0">
                    {{ group.tools.length }}
                  </Badge>
                </div>
                <p class="text-xs text-muted-foreground line-clamp-1">
                  {{ getGroupCategoryLabel(group.source) }}
                </p>
              </div>

              <!-- Add New MCP Card -->
              <div
                class="relative flex flex-col items-center justify-center gap-2 p-3 rounded-xl border border-dashed border-muted-foreground/25 hover:border-primary hover:bg-primary/5 cursor-pointer transition-all duration-200"
                @click="showAddMcpForm"
              >
                <div class="flex items-center gap-2 text-muted-foreground group-hover:text-primary">
                  <Plus class="h-4 w-4" />
                  <span class="text-sm font-medium">
                    {{ t('tools.addMcpServer') || 'Add MCP Server' }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      <!-- MCP Management Bar (Only visible when specific MCP server is selected) -->
      <div v-if="isMcpGroup(selectedGroupSource)" class="px-6 py-2 bg-muted/30 border-t flex items-center justify-between animate-in slide-in-from-top-2">
        <div class="flex items-center gap-2 text-sm text-muted-foreground">
          <Server class="h-4 w-4" />
          <span class="font-medium">{{ getToolSourceLabel(selectedGroupSource) }}</span>
          <span class="mx-2 text-muted-foreground/50">|</span>
          <span>{{ displayedTools.length }} {{ t('tools.count') }}</span>
        </div>
        <div class="flex items-center gap-2">
          <Button 
            v-if="isMcpGroup(selectedGroupSource)"
            variant="outline" 
            size="sm" 
            class="h-8" 
            @click="showMcpDetails(selectedGroupSource)"
          >
            <Info class="mr-2 h-3.5 w-3.5" />
            {{ t('tools.details') || 'Details' }}
          </Button>

          <Button
            v-if="canEditGroup(selectedGroupSource)"
            variant="outline"
            size="sm"
            class="h-8"
            @click="handleEditMcpTool(selectedGroupSource)"
          >
            <Edit class="mr-2 h-3.5 w-3.5" />
            {{ t('tools.editMcpServer') || 'Edit MCP Server' }}
          </Button>

          <Button
            v-if="isAnyToolGroup(selectedGroupSource)"
            variant="outline"
            size="sm"
            class="h-8"
            @click="openAnyToolEditor()"
          >
            <Plus class="mr-2 h-3.5 w-3.5" />
            {{ t('tools.addTool') || 'Add Tool' }}
          </Button>

          <Button
            variant="outline"
            size="sm"
            class="h-8"
            :class="getCurrentGroupDisabled() ? 'text-emerald-600 hover:text-emerald-600 hover:bg-emerald-50' : 'text-amber-600 hover:text-amber-600 hover:bg-amber-50'"
            @click="handleToggleMcpTool(selectedGroupSource)"
          >
            <component :is="getCurrentGroupDisabled() ? Power : PowerOff" class="mr-2 h-3.5 w-3.5" />
            {{ getCurrentGroupDisabled() ? t('tools.enable') || 'Enable' : t('tools.disable') || 'Disable' }}
          </Button>

          <Button variant="outline" size="sm" class="h-8" @click="handleRefreshMcpTool(selectedGroupSource)">
            <RefreshCw class="mr-2 h-3.5 w-3.5" />
            {{ t('tools.refresh') }}
          </Button>
          <Button
            v-if="canDeleteGroup(selectedGroupSource)"
            variant="outline"
            size="sm"
            class="h-8 text-destructive hover:text-destructive hover:bg-destructive/10"
            @click="handleDeleteMcpTool(selectedGroupSource)"
          >
            <Trash2 class="mr-2 h-3.5 w-3.5" />
            {{ t('tools.delete') }}
          </Button>
        </div>
      </div>
    </div>

    <!-- Main Content Area -->
    <div v-if="viewMode === 'list'" class="flex-1 overflow-hidden bg-muted/5 p-4 md:p-6">
      <ScrollArea class="h-full pr-4">
        <div v-if="loading" class="flex flex-col items-center justify-center py-20">
          <Loader class="h-8 w-8 animate-spin text-primary" />
        </div>
        <div v-else-if="displayedTools.length === 0" class="flex h-full min-h-[420px] items-center justify-center pb-20">
          <div class="max-w-lg rounded-2xl border border-dashed bg-background/60 p-8 text-center shadow-sm">
            <div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 text-primary">
              <Plus class="h-6 w-6" />
            </div>
            <h3 class="text-lg font-semibold">
              {{ isAnyToolGroup(selectedGroupSource) ? (t('tools.noAnyToolDefinitions') || 'No tool definitions yet. Add one to start simulating.') : (t('tools.noToolDefinitions') || 'No tools in this group yet.') }}
            </h3>
            <p class="mt-2 text-sm text-muted-foreground">
              {{ isAnyToolGroup(selectedGroupSource) ? (t('tools.anyToolEditorHint') || 'Define simulated tools, preview them, and keep the built-in MCP server enabled or disabled.') : (t('tools.noDescription') || '') }}
            </p>
            <div class="mt-6 flex items-center justify-center gap-3">
              <Button
                v-if="isAnyToolGroup(selectedGroupSource)"
                variant="default"
                size="sm"
                @click="openAnyToolEditor()"
              >
                <Plus class="mr-2 h-4 w-4" />
                {{ t('tools.addTool') || 'Add Tool' }}
              </Button>
              <Button variant="outline" size="sm" @click="showMcpDetails(selectedGroupSource)">
                <Info class="mr-2 h-4 w-4" />
                {{ t('tools.details') || 'Details' }}
              </Button>
            </div>
          </div>
        </div>
        <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4 pb-20">
           <Card 
              v-for="tool in displayedTools" 
              :key="tool.name" 
              class="relative cursor-pointer transition-all duration-200 hover:shadow-md border-muted/60 hover:border-primary/50 group bg-card"
              @click="openToolDetail(tool)"
            >
              <div
                v-if="isAnyToolGroup(selectedGroupSource)"
                class="absolute top-2 right-2 z-10 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity"
                @click.stop
              >
                <Button
                  variant="ghost"
                  size="icon"
                  class="h-7 w-7"
                  :title="t('tools.editTool') || 'Edit Tool'"
                  @click.stop="openAnyToolEditor(tool)"
                >
                  <Edit class="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  class="h-7 w-7 text-destructive hover:text-destructive"
                  :title="t('tools.deleteTool') || 'Delete Tool'"
                  @click.stop="confirmDeleteAnyToolTool(tool)"
                >
                  <Trash2 class="h-3.5 w-3.5" />
                </Button>
              </div>
              <CardHeader class="flex flex-row items-start gap-3 space-y-0 pb-3 p-4">
                <div 
                  class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-white shadow-sm transition-all group-hover:scale-105"
                  :class="getToolTypeColorClass(tool.type)"
                >
                  <component :is="getToolIcon(tool.type)" class="h-5 w-5" />
                </div>
                <div class="space-y-1 overflow-hidden flex-1 min-w-0">
                  <div class="flex items-center justify-between gap-2">
                    <CardTitle class="text-sm font-semibold truncate" :title="tool.name">
                      {{ tool.name }}
                    </CardTitle>
                  </div>
                  <p class="text-xs text-muted-foreground line-clamp-3 h-8">
                    {{ tool.description || t('tools.noDescription') }}
                  </p>
                </div>
              </CardHeader>
              <CardContent class="p-4 pt-0">
                <div class="flex items-center justify-between pt-3 border-t border-dashed mt-1 text-[10px] text-muted-foreground">
                  <div class="flex items-center gap-1.5 truncate max-w-[70%]">
                    <Database v-if="tool.type === 'mcp'" class="h-3 w-3 shrink-0" />
                    <Code v-else class="h-3 w-3 shrink-0" />
                    <span class="truncate" :title="getToolSourceLabel(tool.source)">{{ getToolSourceLabel(tool.source) }}</span>
                  </div>
                  <Badge variant="secondary" class="text-[10px] h-5 px-1.5 font-normal">
                    {{ formatParameters(tool.parameters).length }} {{ t('tools.paramsCount') || '参数' }}
                  </Badge>
                </div>
              </CardContent>
            </Card>
        </div>
      </ScrollArea>
    </div>

    <!-- Add/Edit MCP Dialog -->
    <Dialog v-model:open="isAddMcpDialogOpen">
      <DialogContent class="sm:max-w-[600px] max-h-[85vh] overflow-hidden flex flex-col p-0 gap-0">
        <DialogHeader class="px-6 py-4 border-b">
          <DialogTitle>{{ isEditMode ? (t('tools.editMcpServer') || 'Edit MCP Server') : (t('tools.addMcpServer') || 'Add MCP Server') }}</DialogTitle>
          <DialogDescription class="hidden">
             {{ isEditMode ? 'Edit existing MCP server' : 'Add a new MCP server' }}
          </DialogDescription>
        </DialogHeader>
        <div class="flex-1 overflow-y-auto">
           <McpServerAdd 
            :loading="loading" 
            :is-edit="isEditMode"
            @submit="handleMcpSubmit" 
            @cancel="isAddMcpDialogOpen = false"
            ref="mcpServerAddRef" 
          />
        </div>
      </DialogContent>
    </Dialog>

    <!-- AnyTool Tool Editor Dialog -->
    <Dialog v-model:open="isAnyToolEditorOpen">
      <DialogContent class="sm:max-w-[980px] max-h-[90vh] overflow-hidden flex flex-col p-0 gap-0">
        <DialogHeader class="px-6 py-4 border-b">
          <DialogTitle>
            {{ anyToolEditorMode === 'edit' ? (t('tools.editTool') || 'Edit Tool') : (t('tools.addTool') || 'Add Tool') }}
          </DialogTitle>
          <DialogDescription class="hidden">
            {{ anyToolEditorMode === 'edit' ? 'Edit a built-in AnyTool definition' : 'Create a new built-in AnyTool definition' }}
          </DialogDescription>
        </DialogHeader>
        <div class="flex-1 overflow-y-auto">
          <AnyToolToolEditor
            :tool="editingAnyToolTool"
            :mode="anyToolEditorMode"
            :loading="isSavingAnyToolTool"
            @submit="handleAnyToolToolSubmit"
            @cancel="isAnyToolEditorOpen = false"
          />
        </div>
      </DialogContent>
    </Dialog>

    <!-- MCP Details Dialog -->
    <Dialog v-model:open="isDetailsDialogOpen">
      <DialogContent class="sm:max-w-[600px] max-h-[85vh] overflow-hidden flex flex-col p-0 gap-0">
        <DialogHeader class="px-6 py-4 border-b">
          <DialogTitle>{{ t('tools.mcpDetails') || 'MCP Server Details' }}</DialogTitle>
          <DialogDescription class="hidden">
             Details of the MCP server
          </DialogDescription>
        </DialogHeader>
        <div class="flex-1 overflow-y-auto p-6 space-y-6">
           <!-- Name & Description -->
           <div class="space-y-1">
             <h3 class="text-lg font-semibold flex items-center gap-2">
               <Server class="h-5 w-5" />
               {{ mcpDetails.name }}
             </h3>
             <p class="text-muted-foreground">{{ mcpDetails.description || t('tools.noDescription') }}</p>
           </div>

           <div class="grid gap-4 py-4">
             <div class="grid grid-cols-4 items-center gap-4">
               <span class="font-medium text-right text-muted-foreground">{{ t('tools.protocol') }}</span>
               <span class="col-span-3 font-mono text-sm bg-muted px-2 py-1 rounded">{{ mcpDetails.protocol }}</span>
             </div>
             
             <!-- Protocol Specifics -->
             <template v-if="mcpDetails.protocol === 'stdio'">
               <div class="grid grid-cols-4 items-start gap-4">
                 <span class="font-medium text-right text-muted-foreground mt-1">{{ t('tools.command') }}</span>
                 <code class="col-span-3 text-sm bg-muted px-2 py-1 rounded break-all">{{ mcpDetails.command }}</code>
               </div>
               <div v-if="mcpDetails.args && mcpDetails.args.length" class="grid grid-cols-4 items-start gap-4">
                 <span class="font-medium text-right text-muted-foreground mt-1">{{ t('tools.arguments') }}</span>
                 <div class="col-span-3 flex flex-wrap gap-1">
                   <Badge variant="secondary" v-for="(arg, idx) in mcpDetails.args" :key="idx" class="font-mono text-xs">
                     {{ arg }}
                   </Badge>
                 </div>
               </div>
             </template>

             <template v-if="mcpDetails.protocol === 'sse'">
               <div class="grid grid-cols-4 items-start gap-4">
                 <span class="font-medium text-right text-muted-foreground mt-1">SSE URL</span>
                 <a :href="mcpDetails.sse_url" target="_blank" class="col-span-3 text-sm text-primary hover:underline break-all">{{ mcpDetails.sse_url }}</a>
               </div>
             </template>
             
             <template v-if="mcpDetails.protocol === 'streamable_http'">
               <div class="grid grid-cols-4 items-start gap-4">
                 <span class="font-medium text-right text-muted-foreground mt-1">Stream URL</span>
                 <a :href="mcpDetails.streamable_http_url" target="_blank" class="col-span-3 text-sm text-primary hover:underline break-all">{{ mcpDetails.streamable_http_url }}</a>
               </div>
             </template>

             <div class="grid grid-cols-4 items-center gap-4">
               <span class="font-medium text-right text-muted-foreground">{{ t('tools.status') }}</span>
               <Badge :variant="mcpDetails.status === 'disabled' ? 'destructive' : 'default'" class="w-fit col-span-3">
                 {{ mcpDetails.status === 'disabled' ? (t('tools.disabled') || 'Disabled') : (t('tools.enabled') || 'Enabled') }}
               </Badge>
             </div>
           </div>
        </div>
        <div class="p-6 pt-0 flex justify-end">
          <Button @click="isDetailsDialogOpen = false">
            {{ t('tools.close') || 'Close' }}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
    <AppConfirmDialog ref="confirmDialogRef" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Wrench, Search, Code, Database, Globe, Cpu, Plus, Trash2, Loader, RefreshCw, LayoutGrid, Server, Edit, Info, Power, PowerOff } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { toolAPI } from '../api/tool.js'
import { getCurrentUser } from '../utils/auth.js'
import { getMcpServerLabel } from '../utils/mcpLabels.js'
import McpServerAdd from '../components/McpServerAdd.vue'
import AnyToolToolEditor from '../components/AnyToolToolEditor.vue'
import AppConfirmDialog from '../components/AppConfirmDialog.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { toast } from 'vue-sonner'

import { ChevronUp, ChevronDown } from 'lucide-vue-next'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'

// Composables
const { t } = useLanguage()
const router = useRouter()

// State
const allTools = ref([])
const mcpServers = ref([])
const selectedTool = ref(null)
const searchTerm = ref('')
const filterType = ref('all')
const viewMode = ref('list') // 'list', 'detail'
const isAddMcpDialogOpen = ref(false)
const isDetailsDialogOpen = ref(false)
const isAnyToolEditorOpen = ref(false)
const loading = ref(false)
const mcpServerAddRef = ref(null)
const currentUser = ref({ userid: '', role: 'user' })
const selectedGroupSource = ref('')
const isGridExpanded = ref(true)
const isEditMode = ref(false)
const editingServerName = ref('')
const confirmDialogRef = ref(null)
const anyToolEditorMode = ref('create')
const editingAnyToolTool = ref(null)
const isSavingAnyToolTool = ref(false)
const mcpDetails = ref({})

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
  const groups = []
  const processedSources = new Set()
  
  const showMcpGroups = filterType.value === 'all' || filterType.value === 'mcp'

  // 1. MCP Servers (作为 MCP 分组的数据源)
  if (showMcpGroups) {
    mcpServers.value.forEach(server => {
      // Determine prefix based on server type or existing tools
      let prefix = 'MCP Server: '
      const isAnyToolServer = server.kind === 'anytool' || server.type === 'builtin' || server.name === 'AnyTool'
      const hasBuiltinTools = filteredTools.value.some(t => t.source === `内置MCP: ${server.name}`)
      if (isAnyToolServer || hasBuiltinTools) {
        prefix = '内置MCP: '
      }

      const groupSource = `${prefix}${server.name}`
      processedSources.add(groupSource)
      
      // 查找该服务器下的工具（基于过滤后的列表，这样搜索也能生效）
      const tools = filteredTools.value.filter(t => t.source === groupSource)
      
      groups.push({
        source: groupSource,
        tools: tools,
        isMcp: true,
        disabled: server.status === 'disabled' || server.disabled === true,
        serverName: server.name
      })
    })
  }

  // 2. 其他来源（如系统工具等）
  filteredTools.value.forEach(tool => {
    const source = tool.source || '未知来源'
    // 如果不是已经处理过的 MCP 来源
    if (!processedSources.has(source)) {
      let group = groups.find(g => g.source === source)
      if (!group) {
        group = {
          source: source,
          tools: [],
          isMcp: false,
          disabled: false
        }
        groups.push(group)
      }
      group.tools.push(tool)
    }
  })

  // 按来源名称排序
  return groups.sort((a, b) => a.source.localeCompare(b.source))
})

// Watch for changes in groupedTools to set initial selection
watch(groupedTools, (newGroups) => {
  if (newGroups.length > 0 && !selectedGroupSource.value) {
    selectedGroupSource.value = newGroups[0].source
  }
}, { immediate: true })

const displayedTools = computed(() => {
  if (!selectedGroupSource.value && groupedTools.value.length > 0) {
    return []
  }
  return filteredTools.value.filter(tool => tool.source === selectedGroupSource.value)
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
  isEditMode.value = false
  editingServerName.value = ''
  if (mcpServerAddRef.value) {
    mcpServerAddRef.value.resetForm()
  }
  isAddMcpDialogOpen.value = true
}

const showMcpDetails = (sourceName) => {
  const serverName = normalizeServerNameFromSource(sourceName)
  const server = mcpServers.value.find(s => s.name === serverName)
  if (server) {
    mcpDetails.value = server
    isDetailsDialogOpen.value = true
  }
}

const handleEditMcpTool = (sourceName) => {
  const serverName = normalizeServerNameFromSource(sourceName)
  const server = mcpServers.value.find(s => s.name === serverName)
  
  if (server) {
    isEditMode.value = true
    editingServerName.value = serverName
    isAddMcpDialogOpen.value = true
    // Wait for dialog to open and ref to be available
    setTimeout(() => {
      if (mcpServerAddRef.value) {
        mcpServerAddRef.value.setFormData(server)
      }
    }, 100)
  }
}

const openAnyToolEditor = (tool = null) => {
  anyToolEditorMode.value = tool ? 'edit' : 'create'
  editingAnyToolTool.value = tool ? { ...tool } : null
  isAnyToolEditorOpen.value = true
}

const handleAnyToolToolSubmit = async ({ tool_definition, original_name }) => {
  try {
    isSavingAnyToolTool.value = true
    const response = await toolAPI.upsertAnyToolTool({
      tool_definition,
      original_name,
      server_name: 'AnyTool',
    })
    toast.success(t('tools.saveSuccess') || 'Tool saved successfully')
    isAnyToolEditorOpen.value = false
    await loadMcpServers()
    await loadBasicTools()
    window.dispatchEvent(new Event('tools-updated'))
    if (response?.tool_name) {
      router.push({ name: 'ToolDetailView', params: { toolName: response.tool_name } })
    }
  } catch (error) {
    console.error('Failed to save AnyTool:', error)
    toast.error(error.message || t('tools.saveFailed') || 'Failed to save tool')
  } finally {
    isSavingAnyToolTool.value = false
  }
}

const confirmDeleteAnyToolTool = async (tool) => {
  if (!tool?.name) return
  const confirmText = (t('tools.confirmDeleteTool') || 'Are you sure to delete tool "{name}"?').replace('{name}', tool.name)
  const confirmed = await confirmDialogRef.value?.confirm(confirmText)
  if (!confirmed) return
  try {
    await toolAPI.deleteAnyToolTool(tool.name, 'AnyTool')
    toast.success(t('tools.deleteSuccess') || 'Tool deleted')
    await Promise.all([loadMcpServers(), loadBasicTools()])
    window.dispatchEvent(new Event('tools-updated'))
  } catch (error) {
    console.error('Failed to delete AnyTool tool:', error)
    toast.error(error?.message || t('tools.deleteFailed') || 'Failed to delete tool')
  }
}

const handleMcpSubmit = async (payload) => {
  loading.value = true
  try {
    if (isEditMode.value) {
      await toolAPI.updateMcpServer(editingServerName.value, payload)
      toast.success(t('tools.updateSuccess') || 'Server updated successfully')
      
      selectedGroupSource.value = payload.kind === 'anytool'
        ? `内置MCP: ${payload.name}`
        : `MCP Server: ${payload.name}`
    } else {
      // Add mode
      await toolAPI.addMcpServer(payload)
      toast.success(t('tools.addSuccess') || 'Server added successfully')
      selectedGroupSource.value = payload.kind === 'anytool'
        ? `内置MCP: ${payload.name}`
        : `MCP Server: ${payload.name}`
    }
    
    await loadMcpServers()
    await loadBasicTools()
    isAddMcpDialogOpen.value = false
  } catch (error) {
    console.error('Failed to save MCP server:', error)
    toast.error(error.message || (isEditMode.value ? t('tools.updateFailed') : t('tools.addFailed')))
  } finally {
    loading.value = false
  }
}

const canEditGroup = (sourceName) => {
  if (!isMcpGroup(sourceName)) return false
  if (isAnyToolGroup(sourceName)) return false
  if (currentUser.value.role === 'admin') return true
  
  const serverName = normalizeServerNameFromSource(sourceName)
  const server = mcpServers.value.find(s => s.name === serverName)
  
  if (!server || !server.user_id) return false
  return server.user_id === currentUser.value.userid
}

const canDeleteGroup = (sourceName) => {
  const server = getServerByGroupSource(sourceName)
  if (!server) return false
  if ((server.kind || server.type) === 'anytool' || server.name === 'AnyTool') return false
  return true
}

const canManage = (tool) => {
  if (tool.type !== 'mcp') return false
  if (currentUser.value.role === 'admin') return true
  const sourceName = normalizeServerNameFromSource(tool.source || '')
  const server = mcpServers.value.find(s => s.name === sourceName)
  if (!server || !server.user_id) return false
  return server.user_id === currentUser.value.userid
}

const handleDeleteMcpTool = async (sourceName) => {
  const serverName = normalizeServerNameFromSource(sourceName)

  if (!confirm(t('tools.deleteConfirm', { name: serverName }) || 'Are you sure you want to remove this MCP server?')) {
    return
  }

  try {
    loading.value = true
    await toolAPI.deleteMcpServer(serverName)
    toast.success(t('tools.deleteSuccess') || 'Server removed successfully')
    await loadBasicTools()
    await loadMcpServers()

    // Reset selection if deleted group was selected
    if (selectedGroupSource.value === sourceName) {
        selectedGroupSource.value = groupedTools.value[0]?.source || ''
    }
  } catch (error) {
    console.error('Failed to remove MCP server:', error)
    toast.error(error.message || t('tools.deleteFailed') || 'Failed to remove server')
  } finally {
    loading.value = false
  }
}

const getCurrentGroupDisabled = () => {
  const group = groupedTools.value.find(item => item.source === selectedGroupSource.value)
  return group?.disabled === true
}

const getServerByGroupSource = (sourceName) => {
  const serverName = normalizeServerNameFromSource(sourceName)
  return mcpServers.value.find(s => s.name === serverName)
}

const handleToggleMcpTool = async (sourceName) => {
  const serverName = normalizeServerNameFromSource(sourceName)

  try {
    loading.value = true
    await toolAPI.toggleMcpServer(serverName)
    toast.success(t('tools.updateSuccess') || 'Server status updated successfully')
    await loadMcpServers()
    await loadBasicTools()
  } catch (error) {
    console.error('Failed to toggle MCP server:', error)
    toast.error(error.message || t('tools.updateFailed') || 'Failed to update server status')
  } finally {
    loading.value = false
  }
}

const handleRefreshMcpTool = async (sourceName) => {
  const serverName = normalizeServerNameFromSource(sourceName)

  try {
    loading.value = true
    await toolAPI.refreshMcpServer(serverName)
    toast.success(t('tools.refreshSuccess') || 'Server refreshed successfully')
    await loadMcpServers()
    await loadBasicTools()
    
  } catch (error) {
    console.error('Failed to refresh MCP server:', error)
    toast.error(error.message || t('tools.refreshFailed') || 'Failed to refresh server')
  } finally {
    loading.value = false
  }
}

const getToolSourceLabel = (source) => {
  let displaySource = source
  if (source.startsWith('MCP Server: ')) {
    displaySource = getMcpServerLabel(source.replace('MCP Server: ', ''), t)
  } else if (source.startsWith('内置MCP: ')) {
    displaySource = getMcpServerLabel(source.replace('内置MCP: ', ''), t)
  }

  const sourceMapping = {
    '基础工具': 'tools.source.basic',
    '内置工具': 'tools.source.builtin',
    '系统工具': 'tools.source.system',
    '浏览器扩展': 'tools.source.browserExtension'
  }

  const translationKey = sourceMapping[displaySource]
  return translationKey ? t(translationKey) : displaySource
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

const getGroupIcon = (source) => {
    if (source.includes('MCP')) return Server
    if (source === '浏览器扩展') return Globe
    if (['基础工具', '内置工具', '系统工具'].includes(source)) return Code
    return Wrench
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

const formatParameters = (parameters, requiredNames = []) => {
  if (!parameters || typeof parameters !== 'object') {
    return []
  }

  const requiredSet = new Set(Array.isArray(requiredNames) ? requiredNames : [])
  return Object.entries(parameters).map(([key, value]) => {
    return {
      name: key,
      type: value.type || 'unknown',
      description: value.description || t('tools.noDescription'),
      required: requiredSet.has(key) || value.required === true
    }
  })
}

const openToolDetail = (tool) => {
  router.push({ name: 'ToolDetailView', params: { toolName: tool.name } })
}

const backToList = () => {
  viewMode.value = 'list'
  selectedTool.value = null
}

const isMcpGroup = (source) => {
    return source.startsWith('MCP Server:') || source.startsWith('内置MCP:')
}

const normalizeServerNameFromSource = (sourceName) => {
  if (sourceName.startsWith('MCP Server: ')) return sourceName.substring('MCP Server: '.length)
  if (sourceName.startsWith('内置MCP: ')) return sourceName.substring('内置MCP: '.length)
  return sourceName
}

const getGroupCategoryLabel = (source) => {
  if (isAnyToolGroup(source)) return t('tools.anyTool') || t('tools.builtinMCP')
  if (source.startsWith('MCP Server:')) return t('tools.externalMCP')
  return t('tools.basicTools')
}

const isBuiltInGroup = (source) => {
  return source.startsWith('内置MCP:')
}

const isAnyToolGroup = (source) => {
  const server = getServerByGroupSource(source)
  const normalizedName = normalizeServerNameFromSource(source)
  return server?.kind === 'anytool' || server?.name === 'AnyTool' || normalizedName === 'AnyTool'
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
