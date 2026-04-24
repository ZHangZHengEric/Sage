<template>
  <div class="h-full w-full overflow-hidden flex flex-col">
    <!-- List View -->
    <div v-if="currentView === 'list'" class="flex-1 overflow-y-auto px-5 py-4 animate-in fade-in duration-500">
      <div class="mx-auto flex w-full max-w-7xl flex-col gap-4">
        <div class="flex items-center justify-between gap-4 border-b border-border/55 pb-3">
          <div class="min-w-0">
            <h1 class="text-[15px] font-semibold tracking-tight text-foreground">{{ t('agent.title') }}</h1>
            <p class="text-[11px] text-muted-foreground">{{ agents.length }} {{ t('chat.agents') }}</p>
          </div>

          <div class="flex items-center gap-2">
            <div class="flex items-center rounded-xl border border-border/60 bg-background/70 p-1">
              <button
                type="button"
                class="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[12px] font-medium transition-colors"
                :class="agentDisplayMode === 'cards' ? 'bg-muted text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
                @click="agentDisplayMode = 'cards'"
              >
                <LayoutGrid class="h-3.5 w-3.5" />
                {{ t('agent.cardView') }}
              </button>
              <button
                type="button"
                class="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[12px] font-medium transition-colors"
                :class="agentDisplayMode === 'rows' ? 'bg-muted text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
                @click="agentDisplayMode = 'rows'"
              >
                <List class="h-3.5 w-3.5" />
                {{ t('agent.listView') }}
              </button>
            </div>

            <Button variant="outline" class="h-9 rounded-xl border-border/60 bg-background/70 px-3.5 shadow-none" @click="handleImport">
              <Download class="mr-2 h-4 w-4" />
              {{ t('agent.import') }}
            </Button>
            <Button class="h-9 rounded-xl px-3.5" @click="handleCreateAgent">
              <Plus class="mr-2 h-4 w-4" />
              {{ t('agent.create') }}
            </Button>
          </div>
        </div>

        <div v-if="loading" class="flex flex-col items-center justify-center py-20">
          <Loader class="h-8 w-8 animate-spin text-primary" />
        </div>

        <div v-else-if="agentDisplayMode === 'cards'" class="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          <div 
            v-for="agent in agents" 
            :key="agent.id"
            class="flip-card h-[212px]"
            :class="{ 'flipped': flippedCard === agent.id }"
          >
            <div class="flip-card-inner">
              <Card 
                class="flip-card-front relative flex h-full cursor-pointer flex-col overflow-hidden rounded-[24px] border border-border/60 bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(249,250,251,0.98))] shadow-[0_1px_0_rgba(255,255,255,0.9),0_20px_48px_rgba(15,23,42,0.05)] transition-all hover:-translate-y-0.5 hover:border-primary/18 hover:shadow-[0_1px_0_rgba(255,255,255,0.94),0_24px_56px_rgba(15,23,42,0.08)] dark:bg-[linear-gradient(180deg,rgba(17,24,39,0.97),rgba(7,11,20,0.99))] dark:shadow-[0_1px_0_rgba(255,255,255,0.04),0_20px_48px_rgba(0,0,0,0.28)]"
                @click="handleViewAgent(agent)"
              >
                <div class="absolute inset-x-0 top-0 h-24 bg-[radial-gradient(circle_at_top_left,rgba(59,130,246,0.16),transparent_62%)] dark:bg-[radial-gradient(circle_at_top_left,rgba(96,165,250,0.18),transparent_58%)]" />
                <div class="absolute inset-x-0 top-[74px] h-px bg-gradient-to-r from-transparent via-border/55 to-transparent" />
                <div class="absolute inset-x-0 bottom-0 h-14 bg-[linear-gradient(180deg,transparent,rgba(15,23,42,0.035))] dark:bg-[linear-gradient(180deg,transparent,rgba(255,255,255,0.024))]" />

                <button 
                  class="absolute right-3 top-3 z-20 rounded-full border border-border/55 bg-background/70 p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground dark:bg-white/5"
                  @click.stop="toggleFlip(agent.id)"
                  :title="t('agent.viewActions')"
                >
                  <MoreHorizontal class="w-4 h-4" />
                </button>
                <CardContent class="relative flex h-full flex-col px-5 pb-4 pt-4">
                  <div class="flex items-start justify-between gap-3 pr-8">
                    <div class="flex min-w-0 items-center gap-2.5">
                      <img
                        :src="`https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=${encodeURIComponent(agent.id)}`"
                        :alt="agent.name"
                        class="h-11 w-11 rounded-[17px] bg-primary/10 object-cover shrink-0 ring-1 ring-border/40"
                      />
                      <div class="min-w-0">
                        <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                          <component :is="getAgentModeIcon(agent.agentMode)" class="h-3.5 w-3.5" />
                          <span>{{ getAgentModeLabel(agent.agentMode) }}</span>
                        </div>
                        <CardTitle class="mt-1 truncate text-[18px] font-semibold leading-tight tracking-[-0.03em]" :title="agent.name">
                          {{ agent.name }}
                        </CardTitle>
                      </div>
                    </div>

                    <span v-if="agent.is_default" class="inline-flex shrink-0 items-center rounded-full border border-primary/18 bg-primary/[0.08] px-1.5 py-0.5 text-[9px] font-medium tracking-[0.08em] text-primary">
                      <Star class="mr-1 h-3 w-3" />
                      {{ t('agent.defaultModel') }}
                    </span>
                  </div>

                  <p class="mt-5 line-clamp-3 text-[13px] leading-[1.45rem] text-foreground/80">
                    {{ agent.description || getRandomPlaceholder(agent.name) }}
                  </p>

                  <div class="mt-auto flex items-end justify-between gap-3 border-t border-border/55 pt-3.5">
                    <div class="min-w-0">
                      <div class="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                        {{ getModelShortName(agent.llm_provider_id) }}
                      </div>
                      <button
                        @click.stop="copyAgentId(agent.id)"
                        class="mt-1 inline-flex max-w-full items-center gap-1 text-[10px] text-muted-foreground transition-colors hover:text-foreground"
                        :title="t('agent.copyFullId')"
                      >
                        <span class="max-w-[112px] truncate font-mono">{{ agent.id }}</span>
                        <Copy class="h-3 w-3" />
                      </button>
                    </div>

                    <div class="flex items-center gap-3 text-[10px] text-muted-foreground">
                      <div class="flex items-center gap-1.5 rounded-full bg-muted/24 px-2 py-1">
                        <Wrench class="h-3.5 w-3.5" />
                        <span>{{ agent.availableTools?.length || 0 }}</span>
                      </div>
                      <div class="flex items-center gap-1.5 rounded-full bg-muted/24 px-2 py-1">
                        <Zap class="h-3.5 w-3.5" />
                        <span>{{ agent.availableSkills?.length || 0 }}</span>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card class="flip-card-back flex h-full flex-col rounded-[22px] border-border/60 bg-card/98">
                <button 
                  class="absolute right-3 top-3 z-20 rounded-full border border-border/55 bg-background/70 p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  @click.stop="toggleFlip(agent.id)"
                >
                  <X class="w-4 h-4 text-muted-foreground" />
                </button>
                
                <CardHeader class="pb-1 pt-4 shrink-0">
                  <CardTitle class="text-sm font-medium text-center">{{ t('agent.actions') }}</CardTitle>
                </CardHeader>

                <CardContent class="flex flex-1 items-center justify-center px-3 pb-3 pt-1">
                  <div class="grid w-full grid-cols-2 gap-1.5">
                    <Button v-if="!agent.is_default" variant="outline" class="h-8 w-full justify-center gap-1 rounded-xl px-2 text-[11px] text-primary hover:bg-primary/10 hover:text-primary" @click.stop="handleSetDefault(agent); toggleFlip(agent.id)">
                      <Star class="w-3.5 h-3.5" />
                      <span class="truncate">{{ t('agent.setDefault') }}</span>
                    </Button>
                    <Button variant="outline" class="h-8 w-full justify-center gap-1 rounded-xl px-2 text-[11px]" @click.stop="openUsageModal(agent); toggleFlip(agent.id)">
                      <FileBraces class="w-3.5 h-3.5" />
                      <span class="truncate">{{ t('agent.usageExample') }}</span>
                    </Button>
                    <Button v-if="canEdit(agent)" variant="outline" class="h-8 w-full justify-center gap-1 rounded-xl px-2 text-[11px]" @click.stop="handleEditAgent(agent); toggleFlip(agent.id)">
                      <Edit class="w-3.5 h-3.5" />
                      <span class="truncate">{{ t('agent.edit') }}</span>
                    </Button>
                    <Button variant="outline" class="h-8 w-full justify-center gap-1 rounded-xl px-2 text-[11px]" @click.stop="handleExport(agent); toggleFlip(agent.id)">
                      <Upload class="w-3.5 h-3.5" />
                      <span class="truncate">{{ t('agent.export') }}</span>
                    </Button>
                    <Button v-if="canDelete(agent)" variant="outline" class="col-span-2 h-8 w-full justify-center gap-1 rounded-xl px-2 text-[11px] text-destructive hover:bg-destructive/10 hover:text-destructive" @click.stop="handleDelete(agent); toggleFlip(agent.id)">
                      <Trash2 class="w-3.5 h-3.5" />
                      <span class="truncate">{{ t('agent.delete') }}</span>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>

        <div v-else class="overflow-hidden rounded-[22px] border border-border/60 bg-background/40">
          <div
            v-for="(agent, index) in agents"
            :key="agent.id"
            :class="[
              'group grid grid-cols-[auto,minmax(0,1fr),148px,164px] items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/20',
              { 'border-t border-border/60': index > 0 }
            ]"
          >
            <img
              :src="`https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=${encodeURIComponent(agent.id)}`"
              :alt="agent.name"
              class="h-10 w-10 rounded-2xl bg-primary/10 object-cover ring-1 ring-border/40"
            />

            <div class="min-w-0 cursor-pointer" @click="handleViewAgent(agent)">
              <div class="flex items-center gap-2">
                <h3 class="min-w-0 flex-1 truncate text-[14px] font-semibold tracking-tight text-foreground">
                  {{ agent.name }}
                </h3>
              </div>
              <div class="mt-1 flex items-center gap-2 overflow-hidden text-[11px] text-muted-foreground">
                <span class="truncate">{{ agent.description || getRandomPlaceholder(agent.name) }}</span>
                <span class="text-border/80">·</span>
                <span class="truncate">{{ getModelShortName(agent.llm_provider_id) }}</span>
                <span class="text-border/80">·</span>
                <button @click.stop="copyAgentId(agent.id)" class="inline-flex items-center gap-1 rounded-full px-1 py-0.5 transition-colors hover:bg-muted/30">
                  <span class="max-w-[110px] truncate font-mono">{{ agent.id }}</span>
                  <Copy class="h-3 w-3" />
                </button>
              </div>
            </div>

            <div class="flex items-center justify-end gap-1.5">
              <span class="flex w-[58px] justify-end">
                <Badge v-if="agent.is_default" variant="default" class="h-5 rounded-full px-2 text-[10px]">
                  {{ t('agent.defaultModel') }}
                </Badge>
              </span>
              <span class="flex w-[82px] justify-end">
                <Badge :variant="getModeBadgeVariant(agent.agentMode)" class="h-5 rounded-full px-2 text-[10px]">
                  {{ getAgentModeLabel(agent.agentMode) }}
                </Badge>
              </span>
            </div>

            <div class="flex min-w-[164px] items-center justify-end gap-1 opacity-0 transition-opacity group-hover:opacity-100">
              <Button v-if="!agent.is_default" variant="ghost" size="icon" class="h-8 w-8 rounded-full" @click.stop="handleSetDefault(agent)">
                <Star class="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" class="h-8 w-8 rounded-full" @click.stop="openUsageModal(agent)">
                <FileBraces class="h-4 w-4" />
              </Button>
              <Button v-if="canEdit(agent)" variant="ghost" size="icon" class="h-8 w-8 rounded-full" @click.stop="handleEditAgent(agent)">
                <Edit class="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" class="h-8 w-8 rounded-full" @click.stop="handleExport(agent)">
                <Upload class="h-4 w-4" />
              </Button>
              <Button v-if="canDelete(agent)" variant="ghost" size="icon" class="h-8 w-8 rounded-full text-destructive hover:bg-destructive/10 hover:text-destructive" @click.stop="handleDelete(agent)">
                <Trash2 class="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div v-else class="flex-1 overflow-hidden">
      <AgentEdit :visible="currentView !== 'list'" :agent="editingAgent" :tools="tools" :skills="skills"
        @save="handleSaveAgent" @update:visible="handleCloseEdit" />
    </div>
    <!-- Export Dialog -->
    <Dialog :open="showExportDialog" @update:open="showExportDialog = $event">
      <DialogContent class="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{{ t('agent.exportTitle') }}</DialogTitle>
          <DialogDescription>
            {{ t('agent.exportDescription') }}
          </DialogDescription>
        </DialogHeader>
        <div class="grid gap-4 py-4">
          <div class="grid grid-cols-4 items-center gap-4">
            <Label class="text-right">
              {{ t('agent.exportFormat') }}
            </Label>
            <div class="col-span-3 flex gap-4">
              <div class="flex items-center space-x-2">
                <input type="radio" id="json" value="json" v-model="exportFormat" class="accent-primary h-4 w-4" />
                <label for="json"
                  class="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">JSON</label>
              </div>
              <div class="flex items-center space-x-2">
                <input type="radio" id="yaml" value="yaml" v-model="exportFormat" class="accent-primary h-4 w-4" />
                <label for="yaml"
                  class="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">YAML</label>
              </div>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showExportDialog = false">{{ t('agent.cancel') }}</Button>
          <Button @click="confirmExport">{{ t('agent.export') }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Usage Dialog -->
    <Dialog :open="showUsageModal" @update:open="showUsageModal = $event">
      <DialogContent class="sm:max-w-[80vw] overflow-hidden">
        <DialogHeader>
          <DialogTitle>
            {{ usageAgent?.name ? t('agent.usageExampleTitleWithName').replace('{name}', usageAgent.name) : t('agent.usageExample') }}
          </DialogTitle>
          <DialogDescription>
            {{ t('agent.usageExampleDescription') }}
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

      </DialogContent>
    </Dialog>

    <!-- Agent Creation Option Modal -->
    <AgentCreationOption :isOpen="showCreationModal" :tools="tools" @create-blank="handleBlankConfig"
      @create-smart="handleSmartConfig" @close="showCreationModal = false" />

    <AgentAuthModal v-model:visible="showAuthModal" :agentId="authAgentId" />
    <AppConfirmDialog ref="confirmDialogRef" />

    <!-- Delete Confirmation Modal -->
    <Teleport to="body">
      <div v-if="showDeleteConfirmDialog" class="fixed inset-0 z-[9999]">
        <!-- Backdrop -->
        <div 
          class="absolute inset-0 bg-black/60 transition-opacity" 
          @click="showDeleteConfirmDialog = false"
        ></div>
        <!-- Modal Content -->
        <div class="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-md">
          <div class="bg-background border rounded-lg shadow-xl p-6 mx-4">
            <h3 class="text-lg font-semibold mb-2">{{ t('agent.deleteConfirmTitle') }}</h3>
            <p class="text-muted-foreground text-sm mb-4">
              {{ t('agent.deleteConfirmMessage').replace('{name}', agentToDelete?.name || '') }}
            </p>
            <div class="space-y-4">
              <div class="flex items-center gap-4">
                <Label class="text-sm w-16">
                  {{ t('agent.name') }}
                </Label>
                <Input
                  v-model="deleteConfirmName"
                  :placeholder="t('agent.deleteNamePlaceholder')"
                  class="flex-1"
                  @keyup.enter="confirmDelete"
                />
              </div>
              <p v-if="deleteConfirmNameError" class="text-destructive text-sm text-center">
                {{ t('agent.deleteNameError') }}
              </p>
            </div>
            <div class="flex justify-end gap-3 mt-6">
              <Button variant="outline" @click="showDeleteConfirmDialog = false">{{ t('agent.cancel') }}</Button>
              <Button variant="destructive" @click="confirmDelete" :disabled="!deleteConfirmName">{{ t('agent.delete') }}</Button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, watch, Teleport } from 'vue'
import { toast } from 'vue-sonner'
import { 
  Plus, Edit, Trash2, FileBraces, Download, Upload, Copy, Loader, 
  Sparkles, Wrench, Zap, GitBranch, Cpu, MoreHorizontal, X, Star, LayoutGrid, List
} from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import { useLanguage } from '../utils/i18n.js'
import { agentAPI } from '../api/agent.js'
import { modelProviderAPI } from '../api/modelProvider.js'
import { getCurrentUser } from '../utils/auth.js'
import AgentCreationOption from '../components/AgentCreationOption.vue'
import AgentEdit from '../components/AgentEdit.vue'
import AgentAuthModal from '../components/AgentAuthModal.vue'
import { toolAPI } from '../api/tool.js'
import { skillAPI } from '../api/skill.js'
import MarkdownRenderer from '../components/chat/MarkdownRenderer.vue'
import { useAgentEditStore } from '../stores/agentEdit'
import { buildImportedAgentDraft, parseAgentConfigImport } from '../utils/agentConfigImport.js'
import { dump } from 'js-yaml'
import AppConfirmDialog from '@/components/AppConfirmDialog.vue'

// UI Components
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'

// State
const agents = ref([])
const loading = ref(false)
const error = ref(null)
const tools = ref([])
const skills = ref([])
const modelProviders = ref([])
const showCreationModal = ref(false)
const currentView = ref('list') // 'list', 'create', 'edit', 'view'
const editingAgent = ref(null)
const showUsageModal = ref(false)
const usageAgent = ref(null)
const usageActiveTab = ref('curl')
const usageCodeMap = ref({ curl: '', python: '', go: '' })
const usageCodeRawMap = ref({ curl: '', python: '', go: '' })
const confirmDialogRef = ref(null)
const flippedCard = ref(null) // Track which card is flipped
const agentDisplayMode = ref('cards')

// Delete Confirmation Dialog State
const showDeleteConfirmDialog = ref(false)
const agentToDelete = ref(null)
const deleteConfirmName = ref('')
const deleteConfirmNameError = ref(false)

// Export Dialog State
const showExportDialog = ref(false)
const exportFormat = ref('json')
const agentToExport = ref(null)

// Authorization Modal
const showAuthModal = ref(false)
const authAgentId = ref('')

// Composables
const { t, isZhCN } = useLanguage()
const route = useRoute()
const currentUser = ref(getCurrentUser())
const agentEditStore = useAgentEditStore()
const { listModelProviders } = modelProviderAPI

// 监听路由参数变化，处理刷新
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

// 监听工具列表更新事件
const handleToolsUpdated = () => {
  console.log('[AgentList] Received tools-updated event, reloading tools...')
  loadAvailableTools()
}

// 生命周期
onMounted(async () => {
  await loadAgents()
  await loadModelProviders()
  await loadAvailableTools()
  await loadAvailableSkills()
  window.addEventListener('tools-updated', handleToolsUpdated)
})

onUnmounted(() => {
  window.removeEventListener('tools-updated', handleToolsUpdated)
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

const loadModelProviders = async () => {
  try {
    const response = await listModelProviders()
    modelProviders.value = response || []
  } catch (error) {
    console.error('Failed to load model providers:', error)
    modelProviders.value = []
  }
}

// Methods
const loadAgents = async () => {
  try {
    loading.value = true
    error.value = null
    const response = await agentAPI.getAgents()
    // request.js 已经处理了响应，返回的是 response.data
    if (Array.isArray(response)) {
      agents.value = response
    } else if (response && Array.isArray(response.data)) {
      agents.value = response.data
    } else {
      agents.value = []
    }
  } catch (err) {
    console.error('Failed to load agents:', err)
    error.value = err.message || t('common.error')
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
    console.error('Failed to save agent:', err)
    throw err
  }
}

const removeAgent = async (agentId) => {
  try {
    await agentAPI.deleteAgent(agentId)
    // 重新加载列表
    await loadAgents()
  } catch (err) {
    console.error('Failed to delete agent:', err)
    throw err
  }
}

const handleSetDefault = async (agent) => {
  try {
    await agentAPI.setDefaultAgent(agent.id)
    toast.success(t('agent.setDefaultSuccess').replace('{name}', agent.name))
    // 重新加载列表以更新状态
    await loadAgents()
  } catch (err) {
    console.error('Failed to set default agent:', err)
    toast.error(t('agent.setDefaultError') + (err.message ? `: ${err.message}` : ''))
  }
}

const handleDelete = async (agent) => {
  if (agent.is_default) {
    alert(t('agent.defaultCannotDelete'))
    return
  }

  agentToDelete.value = agent
  deleteConfirmName.value = ''
  deleteConfirmNameError.value = false
  showDeleteConfirmDialog.value = true
}

const confirmDelete = async () => {
  if (!agentToDelete.value || !deleteConfirmName.value) return

  if (deleteConfirmName.value !== agentToDelete.value.name) {
    deleteConfirmNameError.value = true
    return
  }

  try {
    await removeAgent(agentToDelete.value.id)
    toast.success(t('agent.deleteSuccess').replace('{name}', agentToDelete.value.name))
    showDeleteConfirmDialog.value = false
    agentToDelete.value = null
    deleteConfirmName.value = ''
    deleteConfirmNameError.value = false
  } catch (error) {
    console.error('Failed to delete agent:', error)
    toast.error(t('agent.deleteError'))
  }
}

const handleExport = (agent) => {
  agentToExport.value = agent
  exportFormat.value = 'json'
  showExportDialog.value = true
}

const confirmExport = async () => {
  if (!agentToExport.value) return
  const agent = agentToExport.value
  const safeAgentName = (agent.name || 'agent')
    .replace(/[<>:"/\\|?*\u0000-\u001F]/g, '_')
    .trim() || 'agent'

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
    llm_provider_id: agent.llm_provider_id,
    availableTools: agent.availableTools,
    availableSkills: agent.availableSkills,
    systemContext: agent.systemContext,
    availableWorkflows: agent.availableWorkflows,
    exportTime: new Date().toISOString(),
    version: '1.0'
  }

  let dataStr = ''
  let mimeType = ''
  let extension = ''

  if (exportFormat.value === 'json') {
    dataStr = JSON.stringify(exportConfig, null, 2)
    mimeType = 'application/json'
    extension = 'json'
  } else {
    dataStr = dump(exportConfig)
    mimeType = 'application/x-yaml'
    extension = 'yaml'
  }
  const exportFileName = `agent_${safeAgentName}_${new Date().toISOString().split('T')[0]}.${extension}`

  // 尝试使用 Tauri API
  if (window.__TAURI__) {
    try {
      const { save } = await import('@tauri-apps/plugin-dialog')
      const { writeTextFile, stat } = await import('@tauri-apps/plugin-fs')
      const { documentDir, join } = await import('@tauri-apps/api/path')

      const defaultDir = await documentDir()
      const defaultPath = await join(defaultDir, exportFileName)

      const filePath = await save({
        defaultPath: defaultPath,
        filters: [{
          name: extension.toUpperCase() + ' Config',
          extensions: [extension]
        }]
      })

      if (filePath) {
        let targetPath = filePath
        const pathInfo = await stat(filePath).catch(() => null)
        if (pathInfo?.isDirectory) {
          targetPath = await join(filePath, exportFileName)
        }
        await writeTextFile(targetPath, dataStr)
        toast.success(t('agent.exportSuccess'))
        showExportDialog.value = false
        agentToExport.value = null
      }
      return
    } catch (e) {
      console.error('Export failed:', e)
      let errorMsg = ''
      if (typeof e === 'string') {
        errorMsg = e
      } else if (e instanceof Error) {
        errorMsg = e.message
      } else {
        errorMsg = JSON.stringify(e)
      }
      toast.error(t('agent.saveError') + (errorMsg ? `: ${errorMsg}` : ''))
      return
    }
  }

  // 创建下载链接
  const dataBlob = new Blob([dataStr], { type: mimeType })
  const url = URL.createObjectURL(dataBlob)

  // 创建下载链接并触发下载
  const link = document.createElement('a')
  link.href = url
  link.download = exportFileName
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)

  // 清理URL对象
  URL.revokeObjectURL(url)

  showExportDialog.value = false
  agentToExport.value = null
}

const processImportContent = (content) => {
  try {
    const importedConfig = parseAgentConfigImport(content)

    // 验证必要字段
    if (!importedConfig.name) {
      alert(t('agent.importMissingName'))
      return
    }

    const newAgent = buildImportedAgentDraft(importedConfig, t('agent.importSuffix'))

    // 切换到编辑视图并预填数据
    editingAgent.value = newAgent
    currentView.value = 'edit'
    toast.success(t('agent.importDataLoaded'))

  } catch (error) {
    alert(t('agent.importError'))
    console.error('Import error:', error)
  }
}

const handleImport = async () => {
  // 尝试使用 Tauri API
  if (window.__TAURI__) {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const { readTextFile } = await import('@tauri-apps/plugin-fs')
      const { documentDir } = await import('@tauri-apps/api/path')

      const defaultDir = await documentDir()

      const selected = await open({
        defaultPath: defaultDir,
        multiple: false,
        filters: [{
          name: 'Agent Config',
          extensions: ['json', 'yaml', 'yml']
        }]
      })

      if (selected) {
        // selected is path string or array of strings
        const path = Array.isArray(selected) ? selected[0] : selected
        const contents = await readTextFile(path)
        processImportContent(contents)
      }
      return
    } catch (e) {
      console.warn('Tauri import failed, falling back to web input', e)
    }
  }

  // Web fallback
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json,.yaml,.yml,application/json,application/x-yaml,text/yaml,text/x-yaml'
  input.style.display = 'none'

  input.onchange = (event) => {
    const file = event.target.files[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (e) => {
      processImportContent(e.target.result)
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

const handleBlankConfig = async (selectedTools = []) => {
  showCreationModal.value = false

  let systemPrefix = ''
  try {
    const response = await agentAPI.getDefaultSystemPrompt(isZhCN.value ? 'zh' : 'en')
    if (response && response.data && response.data.content) {
      systemPrefix = response.data.content
    } else if (response && response.content) {
      systemPrefix = response.content
    }
  } catch (error) {
    console.error('Failed to load default system prompt:', error)
  }

  // 切换到创建视图，并预填可用工具和系统提示词
  editingAgent.value = {
    availableTools: Array.isArray(selectedTools) ? selectedTools : [],
    availableSkills: [],
    systemPrefix: systemPrefix
  }
  currentView.value = 'create'
}

const handleEditAgent = (agent) => {
  editingAgent.value = agent
  currentView.value = 'edit'
}

const handleAuthorize = (agent) => {
  authAgentId.value = agent.id
  showAuthModal.value = true
}

const handleViewAgent = (agent) => {
  editingAgent.value = agent
  currentView.value = 'view'
}

const handleBackToList = () => {
  currentView.value = 'list'
  editingAgent.value = null
  agentEditStore.currentStep = 1
}

const handleCloseEdit = () => {
  currentView.value = 'list'
  editingAgent.value = null
  agentEditStore.currentStep = 1
}

const handleSaveAgent = async (agentData, shouldExit = true, doneCallback = null) => {
  try {
    const result = await saveAgent(agentData)

    if (shouldExit) {
      currentView.value = 'list'
      editingAgent.value = null
      agentEditStore.currentStep = 1
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
    toast.error(t('agent.saveError') + ' ' + error.message)
  } finally {
    if (doneCallback) doneCallback()
  }
}

const modelProviderMap = computed(() => {
  const map = {}
  modelProviders.value.forEach((provider) => {
    if (provider && provider.id != null) {
      map[provider.id] = provider
    }
  })
  return map
})

const getModelLabel = (providerId) => {
  if (!providerId) return t('agent.defaultModel')
  const provider = modelProviderMap.value[providerId]
  if (!provider) return providerId
  return `${provider.name} (${provider.model})`
}

// 获取模型简称
const getModelShortName = (providerId) => {
  if (!providerId) return t('agent.defaultModel')
  const provider = modelProviderMap.value[providerId]
  if (!provider) return providerId
  // 只返回模型名称，不包含提供商
  return provider.model || provider.name
}

// 获取Agent模式图标
const getAgentModeIcon = (mode) => {
  const normalizedMode = mode === 'fibre' ? 'fibre' : 'simple'
  const iconMap = {
    'fibre': GitBranch,
    'simple': Cpu
  }
  return iconMap[normalizedMode] || Cpu
}

// 获取Agent模式提示文字
const getAgentModeTooltip = (mode) => {
  const normalizedMode = mode === 'fibre' ? 'fibre' : 'simple'
  const tooltipMap = {
    'fibre': t('agent.modeFibre'),
    'simple': t('agent.modeSimple')
  }
  return tooltipMap[normalizedMode] || t('agent.modeSimple')
}

// 获取Agent模式标签文字
const getAgentModeLabel = (mode) => {
  const normalizedMode = mode === 'fibre' ? 'fibre' : 'simple'
  const labelMap = {
    'fibre': 'Fibre',
    'simple': 'Simple'
  }
  return labelMap[normalizedMode] || 'Simple'
}

// 获取Agent模式Badge样式
const getModeBadgeVariant = (mode) => {
  const normalizedMode = mode === 'fibre' ? 'fibre' : 'simple'
  const variantMap = {
    'fibre': 'default',
    'simple': 'secondary'
  }
  return variantMap[normalizedMode] || 'secondary'
}

// Toggle flip card
const toggleFlip = (agentId) => {
  if (flippedCard.value === agentId) {
    flippedCard.value = null
  } else {
    flippedCard.value = agentId
  }
}

// 复制 Agent ID
const copyAgentId = async (agentId) => {
  try {
    // 使用 Web Clipboard API（Tauri 也支持）
    await navigator.clipboard.writeText(agentId)
    toast.success(t('agent.copyIdSuccess'))
  } catch (error) {
    console.error('Failed to copy agent id:', error)
    // 降级方案：使用传统方法
    const textarea = document.createElement('textarea')
    textarea.value = agentId
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    try {
      document.execCommand('copy')
      toast.success(t('agent.copyIdSuccess'))
    } catch (e) {
      toast.error(t('agent.copyIdFailed'))
    }
    document.body.removeChild(textarea)
  }
}

const getRandomPlaceholder = (agentName) => {
  return t('agent.placeholderDescription').replace('{name}', agentName)
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
      throw new Error(t('agent.smartConfigTimeout').replace('{seconds}', String(Math.round(duration / 1000))))
    }

    // 处理网络错误
    if (error.name === 'TypeError' && error.message.includes('fetch')) {
      throw new Error(t('agent.smartConfigNetworkError').replace('{seconds}', String(Math.round(duration / 1000))))
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
    console.error('Failed to generate usage example:', e)
    toast.error(t('agent.usageExampleGenerateError'))
  }
}

const backendEndpoint = (
  import.meta.env.VITE_SAGE_API_BASE_URL || ''
).replace(/\/+$/, '')

const generateUsageCodes = (agent) => {
  const body = {
    messages: [
      { role: 'user', content: t('agent.usageExamplePrompt') }
    ],
    session_id: 'demo-session',
    agent_id: agent.id,
    user_id: currentUser.value?.userid || "demo-user",
    system_context: agent.systemContext || {}
  }

  const jsonStr = JSON.stringify(body, null, 2)
  const curl = [
    `curl -X POST "${backendEndpoint}/api/chat" \\
  -H "Content-Type: application/json" \\
  -d '${jsonStr}'`
  ].join('\n')

  const python = [
    'import requests',
    '',
    `url = "${backendEndpoint}/api/chat"`,
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
    `  url := "${backendEndpoint}/api/chat"`,
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

</script>

<style scoped>
/* 多行文本截断 */
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.line-clamp-3 {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* Flip Card Styles */
.flip-card {
  perspective: 1000px;
}

.flip-card-inner {
  position: relative;
  width: 100%;
  height: 100%;
  transition: transform 0.6s;
  transform-style: preserve-3d;
}

.flip-card.flipped .flip-card-inner {
  transform: rotateY(180deg);
}

.flip-card-front,
.flip-card-back {
  position: absolute;
  width: 100%;
  height: 100%;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
}

.flip-card-back {
  transform: rotateY(180deg);
}
</style>
