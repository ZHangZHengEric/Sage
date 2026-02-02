<template>
  <div class="h-full bg-background border rounded-lg shadow-sm overflow-hidden flex flex-col">
    <div class="flex-1 overflow-y-auto p-6">
      <div class="flex flex-col lg:flex-row gap-6">
        <!-- Left Panel: Basic Config -->
        <div class="flex-1 space-y-6 min-w-0">
          <FormItem :label="t('agent.name')" :error="errors.name" required>
            <Input v-model="formData.name" :placeholder="t('agent.namePlaceholder')" :disabled="formData.id === 'default'" />
          </FormItem>

          <FormItem :label="t('agent.description')" :error="errors.description">
            <Textarea v-model="formData.description" :rows="3" :placeholder="t('agent.descriptionPlaceholder')" class="resize-none" />
          </FormItem>

          <FormItem :label="t('agent.systemPrefix')" :error="errors.systemPrefix" required>
            <div class="relative">
              <Textarea v-model="formData.systemPrefix" :rows="20" :placeholder="t('agent.systemPrefixPlaceholder')" class="min-h-[400px] font-mono text-sm" />
              <Button size="sm" variant="outline" class="absolute top-2 right-2 bg-background/80 backdrop-blur-sm shadow-sm" @click="openOptimizeModal" :disabled="isOptimizing">
                优化系统提示词
              </Button>
            </div>
          </FormItem>

          <FormItem :label="t('agent.memoryType')">
             <Select v-model="formData.memoryType">
               <SelectTrigger>
                 <SelectValue />
               </SelectTrigger>
               <SelectContent>
                 <SelectItem value="session">{{ t('agent.sessionMemory') }}</SelectItem>
                 <SelectItem value="user">{{ t('agent.userMemory') }}</SelectItem>
               </SelectContent>
             </Select>
          </FormItem>

          <div class="grid grid-cols-2 gap-4">
             <FormItem :label="t('agent.deepThinking')">
                <Tabs :model-value="getSelectValue(formData.deepThinking)" @update:model-value="(v) => setSelectValue('deepThinking', v)" class="w-full">
                  <TabsList class="grid w-full grid-cols-3">
                    <TabsTrigger value="auto">{{ t('agent.auto') }}</TabsTrigger>
                    <TabsTrigger value="enabled">{{ t('agent.enabled') }}</TabsTrigger>
                    <TabsTrigger value="disabled">{{ t('agent.disabled') }}</TabsTrigger>
                  </TabsList>
                </Tabs>
             </FormItem>

             <FormItem :label="t('agent.multiAgent')">
                <Tabs :model-value="getSelectValue(formData.multiAgent)" @update:model-value="(v) => setSelectValue('multiAgent', v)" class="w-full">
                  <TabsList class="grid w-full grid-cols-3">
                    <TabsTrigger value="auto">{{ t('agent.auto') }}</TabsTrigger>
                    <TabsTrigger value="enabled">{{ t('agent.enabled') }}</TabsTrigger>
                    <TabsTrigger value="disabled">{{ t('agent.disabled') }}</TabsTrigger>
                  </TabsList>
                </Tabs>
             </FormItem>
             
          </div>

          <div class="grid grid-cols-2 gap-4">
            <FormItem :label="t('agent.moreSuggest')">
               <div class="flex items-center h-10 gap-2 border rounded-md px-3">
                 <Switch :checked="formData.moreSuggest" @update:checked="(v) => formData.moreSuggest = v" />
                 <span class="text-sm text-muted-foreground">{{ formData.moreSuggest ? t('agent.enabled') : t('agent.disabled') }}</span>
               </div>
            </FormItem>
            <FormItem :label="t('agent.maxLoopCount')">
              <Input type="number" v-model.number="formData.maxLoopCount" min="1" max="50" />
            </FormItem>
          </div>

                    <!-- LLM Config -->
           <div class="space-y-4">
              <h3 class="text-lg font-medium flex items-center gap-2">
                <Bot class="h-5 w-5" />
                {{ t('agent.llmConfig') }}
              </h3>
              <Separator />
              <FormItem :label="t('agent.apiKey')">
                 <Input v-model="formData.llmConfig.apiKey" type="password" :placeholder="t('agent.apiKeyPlaceholder')" show-password-toggle />
              </FormItem>
              <FormItem :label="t('agent.baseUrl')">
                 <Input v-model="formData.llmConfig.baseUrl" :placeholder="t('agent.baseUrlPlaceholder')" />
              </FormItem>
              <FormItem :label="t('agent.model')">
                 <Input v-model="formData.llmConfig.model" :placeholder="t('agent.modelPlaceholder')" />
              </FormItem>
              <div class="grid grid-cols-2 gap-4">
                 <FormItem :label="t('agent.maxTokens')">
                    <Input type="number" v-model.number="formData.llmConfig.maxTokens" placeholder="4096" />
                 </FormItem>
                 <FormItem :label="t('agent.temperature')">
                    <Input type="number" v-model.number="formData.llmConfig.temperature" step="0.1" placeholder="0.2" />
                 </FormItem>
                 <FormItem :label="t('agent.topP')">
                    <Input type="number" v-model.number="formData.llmConfig.topP" step="0.1" placeholder="0.9" />
                 </FormItem>
                 <FormItem :label="t('agent.presencePenalty')">
                    <Input type="number" v-model.number="formData.llmConfig.presencePenalty" step="0.1" placeholder="0.0" />
                 </FormItem>
              </div>
              <FormItem :label="t('agent.maxModelLen')">
                 <Input type="number" v-model.number="formData.llmConfig.maxModelLen" placeholder="54000" />
              </FormItem>
           </div>

        </div>

        <!-- Divider -->
        <Separator orientation="vertical" class="hidden lg:block h-auto" />
        <Separator orientation="horizontal" class="lg:hidden" />

        <!-- Right Panel: Context & Workflow -->
        <div class="flex-1 space-y-6 min-w-0">

           <!-- MCP Config -->
           <div class="space-y-4">
              <h3 class="text-lg font-medium flex items-center gap-2">
                <Wrench class="h-5 w-5" />
                {{ t('agent.mcpConfig') }}
              </h3>
              <Separator />
              <FormItem :label="t('agent.availableTools')">
                <ScrollArea class="h-[200px] border rounded-md p-4 bg-muted/10">
                  <div class="space-y-3">
                    <div v-for="tool in props.tools" :key="tool.name" class="flex items-center space-x-2">
                      <Checkbox :id="`tool-${tool.name}`" :checked="formData.availableTools.includes(tool.name)" @update:checked="(c) => handleToolCheck(tool.name, c)" />
                      <label :for="`tool-${tool.name}`" class="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer">
                        {{ tool.name }}
                      </label>
                      <p v-if="tool.description" class="text-xs text-muted-foreground line-clamp-2">{{ tool.description}}</p>
                    </div>
                    <div v-if="props.tools.length === 0" class="text-sm text-muted-foreground text-center py-4">
                      {{ t('tools.noTools') || '暂无可用工具' }}
                    </div>
                  </div>
                </ScrollArea>
              </FormItem>
              <FormItem :label="t('agent.availableSkills')">
                 <ScrollArea class="h-[200px] border rounded-md p-4 bg-muted/10">
                  <div class="space-y-4">
                    <div v-for="skill in props.skills" :key="skill.name || skill" class="flex items-start space-x-2">
                       <Checkbox :id="`skill-${skill.name || skill}`" :checked="formData.availableSkills.includes(skill.name || skill)" @update:checked="(c) => handleSkillCheck(skill.name || skill, c)" class="mt-1" />
                       <div class="grid gap-1.5 leading-none">
                          <label :for="`skill-${skill.name || skill}`" class="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer">
                            {{ skill.name || skill }}
                          </label>
                          <p v-if="skill.description" class="text-xs text-muted-foreground line-clamp-2">{{ skill.description }}</p>
                       </div>
                    </div>
                    <div v-if="props.skills.length === 0" class="text-sm text-muted-foreground text-center py-4">
                      {{ t('skills.noSkills') || '暂无可用技能' }}
                    </div>
                  </div>
                 </ScrollArea>
              </FormItem>
           </div>

           <!-- System Context -->
           <div class="space-y-4">
              <h3 class="text-lg font-medium flex items-center gap-2">
                <Database class="h-5 w-5" />
                {{ t('agent.systemContext') }}
              </h3>
              <Separator />
              <div class="space-y-3">
                 <div v-for="(pair, index) in systemContextPairs" :key="index" class="flex items-center gap-2">
                    <Input v-model="pair.key" :placeholder="t('agent.contextKey')" @input="updateSystemContextPair(index, 'key', $event.target.value)" />
                    <Input v-model="pair.value" :placeholder="t('agent.contextValue')" @input="updateSystemContextPair(index, 'value', $event.target.value)" />
                    <Button variant="ghost" size="icon" class="text-destructive hover:text-destructive hover:bg-destructive/10" @click="removeSystemContextPair(index)" :disabled="systemContextPairs.length === 1 && !pair.key && !pair.value">
                       <Trash2 class="h-4 w-4" />
                    </Button>
                 </div>
                 <Button variant="outline" size="sm" @click="addSystemContextPair" class="w-full border-dashed">
                    <Plus class="h-4 w-4 mr-2" /> {{ t('agent.addContext') }}
                 </Button>
              </div>
           </div>

           <!-- Workflows -->
           <div class="space-y-4">
              <h3 class="text-lg font-medium flex items-center gap-2">
                <Workflow class="h-5 w-5" />
                {{ t('agent.workflows') }}
              </h3>
              <Separator />
              <div ref="workflowContainer" class="workflow-container space-y-4">
                 <div v-for="(workflow, index) in workflowPairs" :key="workflow.id" class="workflow-item" :data-index="index">
                    <Card class="relative transition-all hover:shadow-md">
                       <CardHeader class="pb-2 pt-4 px-4 bg-muted/20">
                          <div class="flex items-center gap-2">
                             <Input v-model="workflow.key" :placeholder="t('agent.workflowName')" class="flex-1 h-8 bg-background" @input="updateWorkflowPair(index, 'key', $event.target.value)" />
                             <Button variant="ghost" size="sm" class="h-8 w-8 p-0" @click.stop="toggleWorkflowCollapse(index)">
                                <ChevronDown v-if="workflowCollapsed[index]" class="h-4 w-4" />
                                <ChevronUp v-else class="h-4 w-4" />
                             </Button>
                             <Button variant="ghost" size="sm" class="h-8 w-8 p-0 text-destructive hover:text-destructive" @click="removeWorkflowPair(index)">
                                <Trash2 class="h-4 w-4" />
                             </Button>
                          </div>
                       </CardHeader>
                       <div v-show="!workflowCollapsed[index]" class="px-4 pb-4 pt-2">
                          <div class="steps-container space-y-2 pl-6 border-l-2 border-muted ml-2" :ref="el => setStepContainer(el, index)">
                             <div v-for="(step, stepIndex) in workflow.steps" :key="step.id" class="step-item flex items-start gap-2 group" :data-step-index="stepIndex">
                                <div class="drag-handle cursor-grab active:cursor-grabbing p-1 mt-2 hover:bg-muted rounded opacity-50 group-hover:opacity-100 transition-opacity">
                                   <GripVertical class="h-3 w-3 text-muted-foreground" />
                                </div>
                                <Textarea v-model="step.value" :placeholder="`${t('agent.step')} ${stepIndex + 1}`" class="flex-1 min-h-[60px] resize-y" @input="updateWorkflowStep(index, stepIndex, $event.target.value)" />
                                <Button variant="ghost" size="sm" class="h-8 w-8 p-0 mt-1 text-destructive hover:text-destructive opacity-50 group-hover:opacity-100 transition-opacity" @click="removeWorkflowStep(index, stepIndex)" :disabled="workflow.steps.length === 1">
                                   <Trash2 class="h-3 w-3" />
                                </Button>
                             </div>
                          </div>
                          <Button variant="outline" size="sm" class="w-[calc(100%-1.5rem)] mt-2 ml-6 border-dashed" @click="addWorkflowStep(index)">
                             <Plus class="h-3 w-3 mr-2" /> {{ t('agent.addStep') }}
                          </Button>
                       </div>
                    </Card>
                 </div>
              </div>
              <Button variant="outline" class="w-full border-dashed py-6" @click="addWorkflowPair">
                 <Plus class="h-4 w-4 mr-2" /> {{ t('agent.addWorkflow') }}
              </Button>
           </div>
        </div>
      </div>
    </div>

    <!-- Footer -->
    <div class="p-4 border-t bg-muted/20 flex justify-end gap-3">
       <Button variant="outline" @click="handleClose">{{ t('common.cancel') }}</Button>
       <Button @click="handleSave" :disabled="saving">
         <Loader v-if="saving" class="mr-2 h-4 w-4 animate-spin" />
         {{ t('common.save') }}
       </Button>
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
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useLanguage } from '../utils/i18n.js'
import { Trash2, Plus, ChevronDown, ChevronUp, GripVertical, Bot, Wrench, Database, Workflow, Loader } from 'lucide-vue-next'
import Sortable from 'sortablejs'
import { agentAPI } from '../api/agent.js'

// UI Components
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
import { Checkbox } from '@/components/ui/checkbox'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Label } from '@/components/ui/label'
import { FormItem } from '@/components/ui/form'

// Props
const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  agent: {
    type: Object,
    default: null
  },
  tools: {
    type: Array,
    default: () => []
  },
  skills: {
    type: Array,
    default: () => []
  }
})

// Emits
const emit = defineEmits(['update:visible', 'save'])

// Composables
const { t } = useLanguage()

// Refs
const saving = ref(false)
const systemContextPairs = ref([{ key: '', value: '' }])
const workflowPairs = ref([{ key: '', steps: [''] }])
const workflowCollapsed = ref([]) // 工作流收缩状态
const workflowContainer = ref(null)
const stepContainers = ref(new Map())
const isInternalEdit = ref(false) // 标记是否为内部编辑
const errors = ref({})

// Sortable instances
const stepSortables = new Map()

const generateId = () => '_' + Math.random().toString(36).substr(2, 9)

// Computed
const isEditing = computed(() => !!props.agent?.id)

// Form data
const defaultFormData = () => ({
  id: null,
  name: '',
  description: '',
  systemPrefix: '你是一个有用的AI助手。',
  deepThinking: null,
  multiAgent: null,
  moreSuggest: false,
  memoryType: "session",
  maxLoopCount: 10,
  llmConfig: {
    apiKey: '',
    baseUrl: '',
    model: '',
    maxTokens: 4096,
    temperature: 0.2,
    topP: 0.9,
    presencePenalty: 0.0,
    maxModelLen: 54000
  },
  availableTools: [],
  availableSkills: [],
  systemContext: {},
  availableWorkflows: {}
})

const formData = ref(defaultFormData())

// Helper functions for Select
const getSelectValue = (val) => {
  if (val === null) return 'auto'
  return val ? 'enabled' : 'disabled'
}

const setSelectValue = (field, val) => {
  if (val === 'auto') formData.value[field] = null
  else if (val === 'enabled') formData.value[field] = true
  else formData.value[field] = false
}

// Helper functions for Tools/Skills
const handleToolCheck = (name, checked) => {
  if (checked) {
    if (!formData.value.availableTools.includes(name)) {
      formData.value.availableTools.push(name)
    }
  } else {
    formData.value.availableTools = formData.value.availableTools.filter(t => t !== name)
  }
}

const handleSkillCheck = (name, checked) => {
  if (checked) {
    if (!formData.value.availableSkills.includes(name)) {
      formData.value.availableSkills.push(name)
    }
  } else {
    formData.value.availableSkills = formData.value.availableSkills.filter(s => s !== name)
  }
}

// Validation
const validate = () => {
  errors.value = {}
  let isValid = true

  if (!formData.value.name || !formData.value.name.trim()) {
    errors.value.name = t('agent.nameRequired')
    isValid = false
  } else if (formData.value.name.length < 2 || formData.value.name.length > 50) {
    errors.value.name = t('agent.nameLength')
    isValid = false
  }

  if (formData.value.description && formData.value.description.length > 200) {
    errors.value.description = t('agent.descriptionLength')
    isValid = false
  }

  if (!formData.value.systemPrefix || !formData.value.systemPrefix.trim()) {
    errors.value.systemPrefix = t('agent.systemPrefixRequired')
    isValid = false
  }

  return isValid
}

// Watch for agent changes
watch(() => props.agent, (newAgent) => {
  if (isInternalEdit.value) return

  if (newAgent) {
    formData.value = JSON.parse(JSON.stringify({
      ...defaultFormData(),
      ...newAgent,
      availableTools: newAgent.availableTools || [],
      availableSkills: newAgent.availableSkills || [],
      llmConfig: { ...defaultFormData().llmConfig, ...(newAgent.llmConfig || {}) }
    }))

    // 初始化系统上下文键值对
    const contextEntries = Object.entries(newAgent.systemContext || {})
    systemContextPairs.value = contextEntries.length > 0
      ? contextEntries.map(([key, value]) => ({
        key: typeof key === 'string' ? key : String(key || ''),
        value: typeof value === 'string' ? value : String(value || '')
      }))
      : [{ key: '', value: '' }]

    // 初始化工作流键值对
    const workflowEntries = Object.entries(newAgent.availableWorkflows || {})
    workflowPairs.value = workflowEntries.length > 0
      ? workflowEntries.map(([key, value]) => {
          const steps = Array.isArray(value) ? value : (typeof value === 'string' ? value.split(',').map(s => s.trim()).filter(s => s) : [''])
          return {
            id: generateId(),
            key,
            steps: steps.map(s => ({ id: generateId(), value: s }))
          }
        })
      : [{ id: generateId(), key: '', steps: [{ id: generateId(), value: '' }] }]

    // 初始化工作流收缩状态（默认全部展开）
    workflowCollapsed.value = new Array(workflowPairs.value.length).fill(true)
  } else {
    formData.value = defaultFormData()
    systemContextPairs.value = [{ key: '', value: '' }]
    workflowPairs.value = [{ id: generateId(), key: '', steps: [{ id: generateId(), value: '' }] }]
    workflowCollapsed.value = [false]
  }

  nextTick(() => {
    initializeDragAndDrop()
  })
}, { immediate: true })

// Watch for visibility changes
watch(() => props.visible, (newVisible) => {
  if (newVisible) {
    errors.value = {}
  }
})

// 设置步骤容器引用
const setStepContainer = (el, workflowIndex) => {
  if (el) {
    stepContainers.value.set(workflowIndex, el)
  }
}

// 初始化拖拽功能
const initializeDragAndDrop = () => {
  nextTick(() => {
    // 初始化步骤拖拽
    stepContainers.value.forEach((container, workflowIndex) => {
      if (container) {
        if (stepSortables.has(workflowIndex)) {
          stepSortables.get(workflowIndex).destroy()
        }

        const sortable = new Sortable(container, {
          handle: '.drag-handle',
          animation: 150,
          ghostClass: 'sortable-ghost',
          chosenClass: 'sortable-chosen',
          dragClass: 'sortable-drag',
          onEnd: (evt) => {
            const { oldIndex, newIndex } = evt
            if (oldIndex !== newIndex) {
              const steps = workflowPairs.value[workflowIndex].steps
              const movedStep = steps.splice(oldIndex, 1)[0]
              steps.splice(newIndex, 0, movedStep)
            }
          }
        })

        stepSortables.set(workflowIndex, sortable)
      }
    })
  })
}

// 销毁拖拽实例
const destroyDragAndDrop = () => {
  stepSortables.forEach(sortable => {
    sortable.destroy()
  })
  stepSortables.clear()
}

onMounted(() => {
  initializeDragAndDrop()
})

onUnmounted(() => {
  destroyDragAndDrop()
})

// 优化系统提示词相关状态与方法
const showOptimizeModal = ref(false)
const optimizationGoal = ref('')
const isOptimizing = ref(false)
const optimizedResult = ref('')

const openOptimizeModal = () => {
  showOptimizeModal.value = true
}

const handleOptimizeStart = async () => {
  const original = (formData.value.systemPrefix || '').trim()
  if (!original) {
    alert('请先输入系统提示词')
    return  
  }

  isOptimizing.value = true
  try { 
    const response  = await agentAPI.systemPromptOptimize({
        original_prompt: original,
        optimization_goal: (optimizationGoal.value || '').trim() || undefined
      })
    optimizedResult.value = response.optimized_prompt || ''
  } catch (err) {
    console.error('优化请求失败:', err)
    alert('优化请求失败，请检查网络连接')
  } finally {
    isOptimizing.value = false
  }
}

const handleOptimizeCancel = () => {
  showOptimizeModal.value = false
  optimizationGoal.value = ''
  isOptimizing.value = false
  optimizedResult.value = ''
}

const handleApplyOptimization = () => {
  if (optimizedResult.value) {
    formData.value.systemPrefix = optimizedResult.value
  }
  showOptimizeModal.value = false
  optimizationGoal.value = ''
  optimizedResult.value = ''
}

const handleResetOptimization = () => {
  optimizedResult.value = ''
  optimizationGoal.value = ''
}

// 系统上下文处理方法
const addSystemContextPair = () => {
  systemContextPairs.value.push({ key: '', value: '' })
}

const removeSystemContextPair = (index) => {
  if (systemContextPairs.value.length > 1) {
    systemContextPairs.value.splice(index, 1)
  } else {
    systemContextPairs.value = [{ key: '', value: '' }]
  }
}

const updateSystemContextPair = (index, field, value) => {
  systemContextPairs.value[index][field] = typeof value === 'string' ? value : String(value || '')
}

// 工作流处理方法
const addWorkflowPair = () => {
  workflowPairs.value.push({ id: generateId(), key: '', steps: [{ id: generateId(), value: '' }] })
  workflowCollapsed.value.push(false)
  nextTick(() => {
    initializeDragAndDrop()
  })
}

const removeWorkflowPair = (index) => {
  if (stepSortables.has(index)) {
    stepSortables.get(index).destroy()
    stepSortables.delete(index)
  }

  const newPairs = workflowPairs.value.filter((_, i) => i !== index)
  if (newPairs.length === 0) {
    workflowPairs.value = [{ id: generateId(), key: '', steps: [{ id: generateId(), value: '' }] }]
    workflowCollapsed.value = [false]
  } else {
    workflowPairs.value = newPairs
    workflowCollapsed.value.splice(index, 1)
  }

  nextTick(() => {
    initializeDragAndDrop()
  })
}

const updateWorkflowPair = (index, field, value) => {
  isInternalEdit.value = true
  workflowPairs.value[index][field] = value
  nextTick(() => {
    isInternalEdit.value = false
  })
}

const addWorkflowStep = (workflowIndex) => {
  isInternalEdit.value = true
  workflowPairs.value[workflowIndex].steps.push({ id: generateId(), value: '' })
  nextTick(() => {
    initializeDragAndDrop()
    isInternalEdit.value = false
  })
}

const removeWorkflowStep = (workflowIndex, stepIndex) => {
  if (workflowPairs.value[workflowIndex].steps.length > 1) {
    isInternalEdit.value = true
    workflowPairs.value[workflowIndex].steps.splice(stepIndex, 1)
    nextTick(() => {
      initializeDragAndDrop()
      isInternalEdit.value = false
    })
  }
}

const updateWorkflowStep = (workflowIndex, stepIndex, value) => {
  isInternalEdit.value = true
  workflowPairs.value[workflowIndex].steps[stepIndex].value = value
  nextTick(() => {
    isInternalEdit.value = false
  })
}

const toggleWorkflowCollapse = (index) => {
  workflowCollapsed.value[index] = !workflowCollapsed.value[index]
}

const handleClose = () => {
  emit('update:visible', false)
}

const handleSave = async () => {
  if (!validate()) {
    // 滚动到第一个错误位置? 简单处理即可
    return
  }

  try {
    saving.value = true

    // 从键值对构建系统上下文对象
    const systemContext = {}
    systemContextPairs.value.forEach(pair => {
      const key = typeof pair.key === 'string' ? pair.key.trim() : ''
      const value = typeof pair.value === 'string' ? pair.value.trim() : ''
      if (key && value) {
        systemContext[key] = value
      }
    })

    // 从键值对构建工作流对象
    const availableWorkflows = {}
    workflowPairs.value.forEach(pair => {
      if (pair.key && pair.key.trim() && pair.steps && pair.steps.some(step => step.value && step.value.trim())) {
        const steps = pair.steps
          .filter(step => step.value && typeof step.value === 'string')
          .map(step => step.value.trim())
          .filter(step => step)
        if (steps.length > 0) {
          availableWorkflows[pair.key.trim()] = steps
        }
      }
    })

    formData.value.systemContext = systemContext
    formData.value.availableWorkflows = availableWorkflows

    const saveData = {
      ...formData.value
    }

    // If set to auto (null), do not send the field to backend
    if (saveData.deepThinking === null) {
      delete saveData.deepThinking
    }
    
    if (saveData.multiAgent === null) {
      delete saveData.multiAgent
    }

    if (!isEditing.value) {
      delete saveData.id
    }

    emit('save', saveData)

  } catch (error) {
    console.error('保存失败:', error)
  } finally {
    saving.value = false
  }
}

defineExpose({
  // formRef not needed anymore
})
</script>

<style scoped>
.sortable-ghost {
  opacity: 0.5;
  background-color: hsl(var(--muted));
  border: 2px dashed hsl(var(--primary));
}

.sortable-chosen {
  transform: scale(1.02);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.sortable-drag {
  transform: rotate(2deg);
  opacity: 0.9;
}
</style>
