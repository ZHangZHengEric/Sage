<template>
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <div class="space-y-6">
      <FormItem :label="t('agent.name')" :error="store.errors.name" required>
        <Input v-model="store.formData.name" :placeholder="t('agent.namePlaceholder')"
          :disabled="store.formData.id === 'default'" />
      </FormItem>

      <FormItem :label="t('agent.description')" :error="store.errors.description">
        <Textarea v-model="store.formData.description" :rows="3" :placeholder="t('agent.descriptionPlaceholder')"
          class="resize-none" />
      </FormItem>

      <FormItem :error="store.errors.systemPrefix">
        <div class="flex justify-between items-center">
          <div class="flex items-center gap-1">
            <Label :class="store.errors.systemPrefix ? 'text-destructive' : ''">{{ t('agent.systemPrefix') }}</Label>
          </div>
          <Button size="sm" variant="ghost" class="flex items-center gap-1 text-black hover:bg-transparent"
            @click="showOptimizeModal = true" :disabled="isOptimizing">
            <!-- 星星图标 -->
            <Sparkles class="h-5 w-5 text-yellow-400" />
            <span>AI优化</span>
          </Button>

        </div>
        <div class="relative">
          <Textarea v-model="store.formData.systemPrefix" :rows="20" :placeholder="t('agent.systemPrefixPlaceholder')"
            class="min-h-[400px] font-mono text-sm" />
        </div>
      </FormItem>
      </div>

    <div class="space-y-6">

      <!-- Strategy Settings (Moved from Step 3) -->
      <Card class="transition-all hover:shadow-md rounded-xl border bg-background/80 backdrop-blur-sm">
        <CardHeader class="pb-3 pt-4 px-5 bg-muted/30 cursor-pointer flex flex-row items-center justify-between rounded-t-xl" @click="toggleSection('strategy')">
          <div class="flex items-center gap-2">
            <Cpu class="h-5 w-5" />
            <CardTitle class="text-base">{{ t('agent.strategy') }}</CardTitle>
          </div>
          <ChevronDown v-if="sections.strategy" class="h-4 w-4" />
          <ChevronUp v-else class="h-4 w-4" />
        </CardHeader>
        <div v-show="!sections.strategy" class="px-5 pb-5 pt-4 space-y-6">
          <FormItem :label="t('agent.memoryType')">
             <Select v-model="store.formData.memoryType">
               <SelectTrigger>
                 <SelectValue />
               </SelectTrigger>
               <SelectContent>
                 <SelectItem value="session">{{ t('agent.sessionMemory') }}</SelectItem>
                 <SelectItem value="user">{{ t('agent.userMemory') }}</SelectItem>
               </SelectContent>
             </Select>
          </FormItem>

          <FormItem :label="t('agent.agentMode')">
              <Select v-model="store.formData.agentMode">
                  <SelectTrigger><SelectValue :placeholder="t('agent.modeAuto')" /></SelectTrigger>
                  <SelectContent>
                      <SelectItem value="fibre">{{ t('agent.modeFibre') }}</SelectItem>
                      <SelectItem value="simple">{{ t('agent.modeSimple') }}</SelectItem>
                      <SelectItem value="multi">{{ t('agent.modeMulti') }}</SelectItem>
                  </SelectContent>
              </Select>
          </FormItem>

          <!-- Sub Agent Selection for Fibre Mode -->
          <FormItem v-if="store.formData.agentMode === 'fibre'" label="子智能体">
              <DropdownMenu>
                <DropdownMenuTrigger as-child>
                  <Button variant="outline" class="w-full justify-between px-3 text-left font-normal">
                    <span class="truncate block">{{ selectedSubAgentsLabel }}</span>
                    <ChevronDown class="ml-2 h-4 w-4 opacity-50 shrink-0" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent class="w-[--radix-dropdown-menu-trigger-width] min-w-[200px]">
                  <div class="max-h-[300px] overflow-y-auto">
                    <DropdownMenuCheckboxItem
                      v-for="agent in filteredAgents"
                      :key="agent.id"
                      :checked="isSubAgentSelected(agent.id)"
                      @select.prevent
                      @update:checked="(checked) => toggleSubAgent(agent.id, checked)"
                    >
                      {{ agent.name }}
                    </DropdownMenuCheckboxItem>
                  </div>
                </DropdownMenuContent>
              </DropdownMenu>
          </FormItem>

          <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
             <FormItem :label="t('agent.deepThinking')">
                <Tabs :model-value="getSelectValue(store.formData.deepThinking)" @update:model-value="(v) => setSelectValue('deepThinking', v)" class="w-full">
                  <TabsList class="grid w-full grid-cols-3">
                    <TabsTrigger value="auto">{{ t('agent.auto') }}</TabsTrigger>
                    <TabsTrigger value="enabled">{{ t('agent.enabled') }}</TabsTrigger>
                    <TabsTrigger value="disabled">{{ t('agent.disabled') }}</TabsTrigger>
                  </TabsList>
                </Tabs>
             </FormItem>
            <FormItem :label="t('agent.moreSuggest')">
               <div class="flex items-center h-10 gap-2 border rounded-md px-3">
                 <Switch :checked="store.formData.moreSuggest" @update:checked="(v) => store.formData.moreSuggest = v" />
                 <span class="text-sm text-muted-foreground">{{ store.formData.moreSuggest ? t('agent.enabled') : t('agent.disabled') }}</span>
               </div>
            </FormItem>
            <FormItem :label="t('agent.maxLoopCount')">
              <Input type="number" v-model.number="store.formData.maxLoopCount" min="1" max="50" />
            </FormItem>
          </div>
        </div>
      </Card>
      <!-- LLM Config (Moved from Step 3) -->
      <Card class="transition-all hover:shadow-md rounded-xl border bg-background/80 backdrop-blur-sm">
        <CardHeader
          class="pb-3 pt-4 px-5 bg-muted/30 cursor-pointer flex flex-row items-center justify-between rounded-t-xl"
          @click="toggleSection('llm')">
          <div class="flex items-center gap-2">
            <Bot class="h-5 w-5" />
            <CardTitle class="text-base">{{ t('agent.llmConfig') }}</CardTitle>
          </div>
          <ChevronDown v-if="sections.llm" class="h-4 w-4" />
          <ChevronUp v-else class="h-4 w-4" />
        </CardHeader>
        <div v-show="!sections.llm" class="px-5 pb-5 pt-4 space-y-4">
          <FormItem :label="t('agent.modelProvider')">
            <div v-if="providers.length === 0"
              class="text-sm text-muted-foreground border border-dashed rounded-md p-3 text-center">
              {{ t('agent.noProviders') || 'No model providers available.' }}
            </div>
            <Select v-else v-model="computedProviderId">
              <SelectTrigger>
                <SelectValue :placeholder="t('agent.selectProvider')" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__system_default__">
                  <span class="text-muted-foreground">{{ t('agent.useSystemDefault') || 'System Default' }}</span>
                </SelectItem>
                <SelectItem v-for="p in providers" :key="p.id" :value="p.id">
                  <span class="font-medium">{{ p.name }}</span>
                  <span class="ml-2 text-xs text-muted-foreground">({{ t('agent.model') || 'Model' }}: {{ p.model
                  }})</span>
                </SelectItem>
              </SelectContent>
            </Select>
          </FormItem>
          <div class="grid grid-cols-1 md:grid-cols-5 gap-4">
            <FormItem :label="t('agent.maxTokens')">
              <Input type="number" v-model.number="store.formData.llmConfig.maxTokens" placeholder="4096" />
            </FormItem>
            <FormItem :label="t('agent.temperature')">
              <Input type="number" v-model.number="store.formData.llmConfig.temperature" step="0.1" placeholder="0.2" />
            </FormItem>
            <FormItem :label="t('agent.topP')">
              <Input type="number" v-model.number="store.formData.llmConfig.topP" step="0.1" placeholder="0.9" />
            </FormItem>
            <FormItem :label="t('agent.presencePenalty')">
              <Input type="number" v-model.number="store.formData.llmConfig.presencePenalty" step="0.1"
                placeholder="0.0" />
            </FormItem>
            <FormItem :label="t('agent.maxModelLen')">
              <Input type="number" v-model.number="store.formData.llmConfig.maxModelLen" placeholder="54000" />
            </FormItem>
          </div>

        </div>
      </Card>

      <!-- System Context -->
      <Card class="transition-all hover:shadow-md rounded-xl bg-background/80 backdrop-blur-sm">
        <CardHeader
          class="pb-3 pt-4 px-5 bg-muted/30 cursor-pointer flex flex-row items-center justify-between rounded-t-xl"
          @click="toggleSection('context')">
          <div class="flex items-center gap-2">
            <Database class="h-5 w-5" />
            <CardTitle class="text-base">{{ t('agent.systemContext') }}</CardTitle>
            <span class="text-xs text-muted-foreground ml-2">({{store.systemContextPairs.filter(p => p.key).length
              }})</span>
          </div>
          <ChevronDown v-if="sections.context" class="h-4 w-4" />
          <ChevronUp v-else class="h-4 w-4" />
        </CardHeader>
        <div v-show="!sections.context" class="px-5 pb-5 pt-4 space-y-3">
          <div v-for="(pair, index) in store.systemContextPairs" :key="index" class="flex items-center gap-2">
            <Input :model-value="pair.key" :placeholder="t('agent.contextKey')"
              @input="store.updateSystemContextPair(index, 'key', $event.target.value)" />
            <Input :model-value="pair.value" :placeholder="t('agent.contextValue')"
              @input="store.updateSystemContextPair(index, 'value', $event.target.value)" />
            <Button variant="ghost" size="icon" class="text-destructive hover:text-destructive hover:bg-destructive/10"
              @click="store.removeSystemContextPair(index)"
              :disabled="store.systemContextPairs.length === 1 && !pair.key && !pair.value">
              <Trash2 class="h-4 w-4" />
            </Button>
          </div>
          <Button variant="outline" size="sm" @click="store.addSystemContextPair" class="w-full border-dashed">
            <Plus class="h-4 w-4 mr-2" /> {{ t('agent.addContext') }}
          </Button>
        </div>
      </Card>
      <!-- Workflows -->
      <Card class="transition-all hover:shadow-md rounded-xl bg-background/80 backdrop-blur-sm">
        <CardHeader class="pb-3 pt-4 px-5 bg-muted/30 flex flex-row items-center justify-between rounded-t-xl">
          <div class="flex items-center gap-2">
            <Workflow class="h-5 w-5" />
            <CardTitle class="text-base">{{ t('agent.workflows') }}</CardTitle>
            <span class="text-xs text-muted-foreground ml-2">({{store.workflowPairs.filter(w => w.key).length
            }})</span>
          </div>
        </CardHeader>
        <div class="px-5 pb-5 pt-4 space-y-4">
          <div v-for="(workflow, index) in store.workflowPairs" :key="index"
            class="rounded-lg p-3 bg-muted/20 hover:bg-muted/40 transition-colors border border-transparent hover:border-border/50">
            <div class="flex items-center gap-2 mb-2">
              <Button variant="ghost" size="sm" class="h-8 w-8 p-0" @click="toggleWorkflow(index)">
                <ChevronDown v-if="isWorkflowExpanded(index)" class="h-4 w-4" />
                <ChevronRight v-else class="h-4 w-4" />
              </Button>
              <Input :model-value="workflow.key" :placeholder="t('agent.workflowName')" class="flex-1 h-8 bg-background"
                @input="store.updateWorkflowPair(index, 'key', $event.target.value)" />
              <Button variant="ghost" size="sm" class="h-8 w-8 p-0 text-destructive hover:text-destructive"
                @click="store.removeWorkflowPair(index)">
                <Trash2 class="h-4 w-4" />
              </Button>
            </div>
            <div v-show="isWorkflowExpanded(index)" :ref="el => setStepListRef(el, index)" class="pl-10 space-y-2"
              :key="workflowRenderKeys[index] || 0">
              <div v-for="(step, stepIndex) in workflow.steps" :key="`${workflowRenderKeys[index] || 0}-${stepIndex}`"
                class="flex items-start gap-2 group">
                <div
                  class="drag-handle cursor-move mt-2.5 text-muted-foreground hover:text-foreground transition-colors p-1 rounded hover:bg-muted flex-shrink-0">
                  <GripVertical class="h-4 w-4" />
                </div>
                <Textarea :model-value="step" :placeholder="`${t('agent.step')} ${stepIndex + 1}`"
                  class="flex-1 min-h-[60px] resize-y bg-background"
                  @input="store.updateWorkflowStep(index, stepIndex, $event.target.value)" />
                <Button variant="ghost" size="sm" class="h-8 w-8 p-0 mt-1 text-destructive hover:text-destructive"
                  @click="store.removeWorkflowStep(index, stepIndex)" :disabled="workflow.steps.length === 1">
                  <Trash2 class="h-3 w-3" />
                </Button>
              </div>
              <Button variant="outline" size="sm" class="w-full border-dashed" @click="store.addWorkflowStep(index)">
                <Plus class="h-3 w-3 mr-2" /> {{ t('agent.addStep') }}
              </Button>
            </div>
          </div>
          <Button variant="outline" class="w-full border-dashed" @click="handleAddWorkflow">
            <Plus class="h-4 w-4 mr-2" /> {{ t('agent.addWorkflow') }}
          </Button>
        </div>
      </Card>


    </div>
    <!-- Optimize Modal -->
    <Dialog :open="showOptimizeModal" @update:open="v => !v && !isOptimizing && handleOptimizeCancel()">
       <DialogContent class="sm:max-w-[640px]">
          <DialogHeader>
             <DialogTitle>优化系统提示词</DialogTitle>
             <DialogDescription>使用 AI 自动优化您的系统提示词，提高 Agent 的表现。</DialogDescription>
          </DialogHeader>
          <div class="space-y-4 py-4">
             <div class="space-y-2">
                <Label>优化目标 <span class="text-xs text-muted-foreground">(可选)</span></Label>
                <Textarea v-model="optimizationGoal" :rows="3" placeholder="例如：提高专业性和准确性，增强工具使用能力..." :disabled="isOptimizing || !!optimizedResult" />
             </div>
             <div v-if="optimizedResult" class="space-y-2">
                <Label>优化结果预览 <span class="text-xs text-muted-foreground">（可编辑）</span></Label>
                <Textarea v-model="optimizedResult" :rows="8" placeholder="优化结果将显示在这里..." />
             </div>
          </div>
          <DialogFooter>
             <Button variant="outline" @click="handleOptimizeCancel" :disabled="isOptimizing">取消</Button>
             <template v-if="optimizedResult">
                <Button variant="outline" @click="handleResetOptimization">重新优化</Button>
                <Button @click="handleApplyOptimization">应用优化</Button>
             </template>
             <template v-else>
                <Button @click="handleOptimizeStart" :disabled="isOptimizing">
                  <Loader v-if="isOptimizing" class="mr-2 h-4 w-4 animate-spin" />
                  开始优化
                </Button>
             </template>
          </DialogFooter>
       </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick, watch, onBeforeUnmount, computed } from 'vue'
import { useAgentEditStore } from '../../stores/agentEdit'
import { useLanguage } from '../../utils/i18n.js'
import { agentAPI } from '../../api/agent.js'
import { modelProviderAPI } from '@/api/modelProvider'
const { listModelProviders } = modelProviderAPI
import { Loader, Trash2, Plus, ChevronDown, ChevronUp, ChevronRight, Workflow, Database, GripVertical, Sparkles, Bot, Cpu } from 'lucide-vue-next'
import Sortable from 'sortablejs'

// UI Components
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { FormItem } from '@/components/ui/form'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuCheckboxItem
} from '@/components/ui/dropdown-menu'

const store = useAgentEditStore()
const { t } = useLanguage()

// Collapsed state
const sections = reactive({
  context: false,
  strategy: false,
  llm: false
})

const toggleSection = (key) => {
  sections[key] = !sections[key]
}

// Workflow expansion state
const expandedWorkflows = reactive(new Set())

const toggleWorkflow = (index) => {
  if (expandedWorkflows.has(index)) {
    expandedWorkflows.delete(index)
  } else {
    expandedWorkflows.add(index)
  }
}

const isWorkflowExpanded = (index) => expandedWorkflows.has(index)

const handleAddWorkflow = () => {
  store.addWorkflowPair()
  // Expand the new workflow (last index)
  // We wait for the store to update
  setTimeout(() => {
    const newIndex = store.workflowPairs.length - 1
    if (newIndex >= 0) {
      expandedWorkflows.add(newIndex)
    }
  }, 0)
}

// Optimization State
const showOptimizeModal = ref(false)
const isOptimizing = ref(false)
const optimizationGoal = ref('')
const optimizedResult = ref('')

const handleOptimizeStart = async () => {
  if (isOptimizing.value) return
  
  isOptimizing.value = true
  try {
    const result = await agentAPI.systemPromptOptimize({
      original_prompt: store.formData.systemPrefix,
      optimization_goal: optimizationGoal.value
      
    })
    
    if (result && result.optimized_prompt) {
      optimizedResult.value = result.optimized_prompt
    }
  } catch (e) {
    console.error('Optimization failed:', e)
    // You might want to show a toast here
  } finally {
    isOptimizing.value = false
  }
}

const handleOptimizeCancel = () => {
  showOptimizeModal.value = false
  optimizationGoal.value = ''
  optimizedResult.value = ''
}

const handleResetOptimization = () => {
  optimizedResult.value = ''
}

const handleApplyOptimization = () => {
  if (optimizedResult.value) {
    store.formData.systemPrefix = optimizedResult.value
    handleOptimizeCancel()
  }
}

// Drag and Drop for Workflow Steps
const stepListRefs = ref([])
const sortableInstances = new Map()
const workflowRenderKeys = reactive({})

const setStepListRef = (el, index) => {
  if (el) {
    stepListRefs.value[index] = el
    initSortable(index, el)
  }
}

const initSortable = (index, el) => {
  if (sortableInstances.has(el)) return

  const sortable = Sortable.create(el, {
    handle: '.drag-handle',
    animation: 150,
    ghostClass: 'bg-muted/50',
    onEnd: (evt) => {
      const { oldIndex, newIndex } = evt
      if (oldIndex === newIndex) return

      // Update data
      const steps = store.workflowPairs[index].steps
      const item = steps[oldIndex]
      steps.splice(oldIndex, 1)
      steps.splice(newIndex, 0, item)
      
      // Force re-render to ensure Vue state matches DOM
      // This is necessary because we are using index as key and Sortable modifies DOM directly
      if (workflowRenderKeys[index] === undefined) workflowRenderKeys[index] = 0
      workflowRenderKeys[index]++
    }
  })
  
  sortableInstances.set(el, sortable)
}

onBeforeUnmount(() => {
  sortableInstances.forEach(instance => instance.destroy())
  sortableInstances.clear()
})

// Step 3 Logic (Merged)
const providers = ref([])
const allAgents = ref([])

const computedProviderId = computed({
  get: () => store.formData.llmConfig.providerId || '__system_default__',
  set: (val) => {
    store.formData.llmConfig.providerId = val === '__system_default__' ? null : val
  }
})

// Helpers for Selects
const getSelectValue = (val) => {
  if (val === null) return 'auto'
  return val ? 'enabled' : 'disabled'
}

const setSelectValue = (field, val) => {
  if (val === 'auto') store.formData[field] = null
  else if (val === 'enabled') store.formData[field] = true
  else store.formData[field] = false
}

// Sub-agent Logic
const filteredAgents = computed(() => {
  return allAgents.value.filter(a => a.id !== store.formData.id)
})

const selectedSubAgentsLabel = computed(() => {
  const ids = store.formData.availableSubAgentIds || []
  if (ids.length === 0) return '选择子智能体'
  
  const names = ids.map(id => {
    const agent = allAgents.value.find(a => a.id === id)
    return agent ? agent.name : ''
  }).filter(Boolean)
  
  return names.join(', ')
})

const isSubAgentSelected = (id) => {
  return store.formData.availableSubAgentIds?.includes(id) || false
}

const toggleSubAgent = (id, checked) => {
  const currentIds = [...(store.formData.availableSubAgentIds || [])]
  
  if (checked) {
    if (!currentIds.includes(id)) {
      currentIds.push(id)
    }
  } else {
    const index = currentIds.indexOf(id)
    if (index > -1) {
      currentIds.splice(index, 1)
    }
  }
  
  store.formData.availableSubAgentIds = currentIds
}

onMounted(async () => {
   // Ensure defaults
   if (!store.formData.memoryType) {
     store.formData.memoryType = 'session'
   }
   if (!store.formData.agentMode) {
     store.formData.agentMode = 'simple'
   }

   try {
     const [providersRes, agentsRes] = await Promise.all([
        listModelProviders(),
        agentAPI.getAgents()
     ])
     providers.value = providersRes || []
     
     if (agentsRes && agentsRes.agents) {
        allAgents.value = agentsRes.agents
     } else if (Array.isArray(agentsRes)) {
        allAgents.value = agentsRes
     } else {
        allAgents.value = []
     }
   } catch (e) {
     console.error('Failed to load data', e)
     providers.value = []
     allAgents.value = []
   }
})
</script>