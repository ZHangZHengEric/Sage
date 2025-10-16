<template>
  <el-dialog
    v-model="dialogVisible"
    :title="isEditing ? t('agent.editTitle') : t('agent.createTitle')"
    width="800px"
    :close-on-click-modal="false"
    @close="handleClose"
  >
    <el-form
      ref="formRef"
      :model="formData"
      :rules="rules"
      label-width="120px"
      label-position="left"
    >
      <el-form-item :label="t('agent.name')" prop="name">
        <el-input
          v-model="formData.name"
          :placeholder="t('agent.namePlaceholder')"
          :disabled="formData.id === 'default'"
        />
      </el-form-item>
      
      <el-form-item :label="t('agent.description')" prop="description">
        <el-input
          v-model="formData.description"
          type="textarea"
          :rows="3"
          :placeholder="t('agent.descriptionPlaceholder')"
        />
      </el-form-item>
      
      <el-form-item :label="t('agent.systemPrefix')" prop="systemPrefix">
        <el-input
          v-model="formData.systemPrefix"
          type="textarea"
          :rows="4"
          :placeholder="t('agent.systemPrefixPlaceholder')"
        />
      </el-form-item>
      
      <el-row :gutter="20">
        <el-col :span="8">
          <el-form-item :label="t('agent.deepThinking')">
            <el-select v-model="formData.deepThinking" :placeholder="t('agent.selectOption')">
              <el-option :label="t('agent.auto')" :value="null" />
              <el-option :label="t('agent.enabled')" :value="true" />
              <el-option :label="t('agent.disabled')" :value="false" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item :label="t('agent.multiAgent')">
            <el-select v-model="formData.multiAgent" :placeholder="t('agent.selectOption')">
              <el-option :label="t('agent.auto')" :value="null" />
              <el-option :label="t('agent.enabled')" :value="true" />
              <el-option :label="t('agent.disabled')" :value="false" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item :label="t('agent.moreSuggest')">
            <el-switch
              v-model="formData.moreSuggest"
              :active-text="t('agent.enabled')"
              :inactive-text="t('agent.disabled')"
            />
          </el-form-item>
        </el-col>
      </el-row>
      
      <el-form-item :label="t('agent.maxLoopCount')">
        <el-input-number
          v-model="formData.maxLoopCount"
          :min="1"
          :max="50"
          :step="1"
        />
      </el-form-item>
      
      <!-- LLM 配置 -->
      <el-divider content-position="left">{{ t('agent.llmConfig') }}</el-divider>
      
      <el-row :gutter="20">
        <el-col :span="8">
          <el-form-item :label="t('agent.model')">
            <el-input
              v-model="formData.llmConfig.model"
              :placeholder="t('agent.modelPlaceholder')"
            />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item :label="t('agent.maxTokens')">
            <el-input-number
              v-model="formData.llmConfig.maxTokens"
              :min="1"
              :max="100000"
              :step="1"
              :placeholder="t('agent.maxTokensPlaceholder')"
            />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item :label="t('agent.temperature')">
            <el-input-number
              v-model="formData.llmConfig.temperature"
              :min="0"
              :max="2"
              :step="0.1"
              :precision="1"
              :placeholder="t('agent.temperaturePlaceholder')"
            />
          </el-form-item>
        </el-col>
      </el-row>
      
      <!-- 系统上下文 -->
      <el-divider content-position="left">{{ t('agent.systemContext') }}</el-divider>
      
      <div class="context-editor">
        <div 
          v-for="(pair, index) in systemContextPairs" 
          :key="index" 
          class="context-pair"
        >
          <el-row :gutter="10" align="middle">
            <el-col :span="10">
              <el-input
                v-model="pair.key"
                :placeholder="t('agent.contextKey')"
                @input="updateSystemContextPair(index, 'key', $event)"
              />
            </el-col>
            <el-col :span="10">
              <el-input
                v-model="pair.value"
                :placeholder="t('agent.contextValue')"
                @input="updateSystemContextPair(index, 'value', $event)"
              />
            </el-col>
            <el-col :span="4">
              <el-button
                type="danger"
                size="small"
                @click="removeSystemContextPair(index)"
                :disabled="systemContextPairs.length === 1 && !pair.key && !pair.value"
              >
                {{ t('common.delete') }}
              </el-button>
            </el-col>
          </el-row>
        </div>
        <el-button
          type="primary"
          size="small"
          @click="addSystemContextPair"
          style="margin-top: 10px;"
        >
          {{ t('agent.addContext') }}
        </el-button>
      </div>
      
      <!-- 工作流 -->
      <el-divider content-position="left">{{ t('agent.workflows') }}</el-divider>
      
      <div class="workflow-editor">
        <div 
          ref="workflowContainer"
          class="workflow-container"
        >
          <div 
            v-for="(workflow, index) in workflowPairs" 
            :key="`workflow-${index}`" 
            class="workflow-item"
            :data-index="index"
          >
          <el-card shadow="never" style="margin-bottom: 10px;">
            <template #header>
              <el-row :gutter="10" align="middle">
                <el-col :span="2">
                  <div class="drag-handle workflow-drag-handle">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <circle cx="9" cy="12" r="1"/>
                      <circle cx="9" cy="5" r="1"/>
                      <circle cx="9" cy="19" r="1"/>
                      <circle cx="15" cy="12" r="1"/>
                      <circle cx="15" cy="5" r="1"/>
                      <circle cx="15" cy="19" r="1"/>
                    </svg>
                  </div>
                </el-col>
                <el-col :span="16">
                  <el-input
                    v-model="workflow.key"
                    :placeholder="t('agent.workflowName')"
                    @input="updateWorkflowPair(index, 'key', $event)"
                  />
                </el-col>
                <el-col :span="6">
                  <el-button
                    type="danger"
                    size="small"
                    @click="removeWorkflowPair(index)"
                  >
                    {{ t('common.delete') }}
                  </el-button>
                </el-col>
              </el-row>
            </template>
            
            <div class="workflow-steps">
              <div 
                class="steps-container" 
                :ref="el => setStepContainer(el, index)"
              >
                <div
                  v-for="(step, stepIndex) in workflow.steps" 
                  :key="`step-${index}-${stepIndex}`"
                  class="step-item"
                  :data-step-index="stepIndex"
                >
                  <el-row :gutter="10" align="middle">
                    <el-col :span="2">
                      <div class="drag-handle">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M9 3h2v2H9V3zm0 4h2v2H9V7zm0 4h2v2H9v-2zm0 4h2v2H9v-2zm0 4h2v2H9v-2zm4-16h2v2h-2V3zm0 4h2v2h-2V7zm0 4h2v2h-2v-2zm0 4h2v2h-2v-2zm0 4h2v2h-2v-2z"/>
                        </svg>
                      </div>
                    </el-col>
                    <el-col :span="18">
                      <el-input
                        v-model="workflow.steps[stepIndex]"
                        :placeholder="`${t('agent.step')} ${stepIndex + 1}`"
                        @input="updateWorkflowStep(index, stepIndex, $event)"
                      />
                    </el-col>
                    <el-col :span="4">
                      <el-button
                        type="danger"
                        size="small"
                        @click="removeWorkflowStep(index, stepIndex)"
                        :disabled="workflow.steps.length === 1"
                      >
                        {{ t('common.delete') }}
                      </el-button>
                    </el-col>
                  </el-row>
                  </div>
              </div>
              <el-button
                type="primary"
                size="small"
                @click="addWorkflowStep(index)"
                style="margin-top: 5px;"
              >
                {{ t('agent.addStep') }}
              </el-button>
            </div>
          </el-card>
          </div>
        </div>
        <el-button
          type="primary"
          @click="addWorkflowPair"
          style="margin-top: 10px;"
        >
          {{ t('agent.addWorkflow') }}
        </el-button>
      </div>
      
      <el-form-item :label="t('agent.availableTools')">
        <el-select
          v-model="formData.availableTools"
          multiple
          :placeholder="t('agent.selectTools')"
          style="width: 100%"
        >
          <el-option
            v-for="tool in props.tools"
            :key="tool.name"
            :label="tool.name"
            :value="tool.name"
          />
        </el-select>
      </el-form-item>
    </el-form>
    
    <template #footer>
      <div class="dialog-footer">
        <el-button @click="handleClose">{{ t('common.cancel') }}</el-button>
        <el-button
          type="primary"
          :loading="saving"
          @click="handleSave"
        >
          {{ t('common.save') }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useLanguage } from '../utils/language.js'
import { useToolStore } from '../stores/tool.js'
import Sortable from 'sortablejs'

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
  }
})

// Emits
const emit = defineEmits(['update:visible', 'save'])

// Composables
const { t } = useLanguage()
const toolStore = useToolStore()

// Refs
const formRef = ref(null)
const saving = ref(false)
const systemContextPairs = ref([{ key: '', value: '' }])
const workflowPairs = ref([{ key: '', steps: [''] }])
const workflowContainer = ref(null)
const stepContainers = ref(new Map())

// Sortable instances
let workflowSortable = null
const stepSortables = new Map()

// Computed
const isEditing = computed(() => !!props.agent?.id)

const dialogVisible = computed({
  get: () => props.visible,
  set: (value) => emit('update:visible', value)
})



// Form data
const defaultFormData = () => ({
  id: null,
  name: '',
  description: '',
  systemPrefix: '你是一个有用的AI助手。',
  deepThinking: null,
  multiAgent: null,
  moreSuggest: false,
  maxLoopCount: 10,
  llmConfig: {
    model: '',
    maxTokens: '',
    temperature: ''
  },
  availableTools: [],
  systemContext: {},
  availableWorkflows: {}
})

const formData = ref(defaultFormData())

// Form rules
const rules = {
  name: [
    { required: true, message: t('agent.nameRequired'), trigger: 'blur' },
    { min: 2, max: 50, message: t('agent.nameLength'), trigger: 'blur' }
  ],
  description: [
    { max: 200, message: t('agent.descriptionLength'), trigger: 'blur' }
  ],
  systemPrefix: [
    { required: true, message: t('agent.systemPrefixRequired'), trigger: 'blur' }
  ]
}

// Watch for agent changes
watch(() => props.agent, (newAgent) => {
  if (newAgent) {
    formData.value = {
      ...defaultFormData(),
      ...newAgent
    }
    
    // 初始化系统上下文键值对
    const contextEntries = Object.entries(newAgent.systemContext || {})
    systemContextPairs.value = contextEntries.length > 0 
      ? contextEntries.map(([key, value]) => ({ key, value })) 
      : [{ key: '', value: '' }]
    
    // 初始化工作流键值对
    const workflowEntries = Object.entries(newAgent.availableWorkflows || {})
    workflowPairs.value = workflowEntries.length > 0 
      ? workflowEntries.map(([key, value]) => ({ 
          key, 
          steps: Array.isArray(value) ? value : (typeof value === 'string' ? value.split(',').map(s => s.trim()).filter(s => s) : [''])
        })) 
      : [{ key: '', steps: [''] }]
  } else {
    formData.value = defaultFormData()
    systemContextPairs.value = [{ key: '', value: '' }]
    workflowPairs.value = [{ key: '', steps: [''] }]
  }
  
  // 重新初始化拖拽功能
  nextTick(() => {
    initializeDragAndDrop()
  })
}, { immediate: true, deep: true })

// Watch for visibility changes
watch(() => props.visible, (newVisible) => {
  if (newVisible && formRef.value) {
    nextTick(() => {
      formRef.value.clearValidate()
    })
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
    // 初始化工作流拖拽
    if (workflowContainer.value) {
      if (workflowSortable) {
        workflowSortable.destroy()
      }
      
      workflowSortable = new Sortable(workflowContainer.value, {
        handle: '.workflow-drag-handle',
        animation: 150,
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        dragClass: 'sortable-drag',
        onEnd: (evt) => {
          const { oldIndex, newIndex } = evt
          if (oldIndex !== newIndex) {
            const movedItem = workflowPairs.value.splice(oldIndex, 1)[0]
            workflowPairs.value.splice(newIndex, 0, movedItem)
          }
        }
      })
    }
    
    // 初始化步骤拖拽
    stepContainers.value.forEach((container, workflowIndex) => {
      if (container) {
        // 销毁旧的实例
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
  if (workflowSortable) {
    workflowSortable.destroy()
    workflowSortable = null
  }
  
  stepSortables.forEach(sortable => {
    sortable.destroy()
  })
  stepSortables.clear()
}

// 在组件挂载时加载工具列表和初始化拖拽
onMounted(async () => {
  if (toolStore.tools.length === 0) {
    await toolStore.loadTools()
  }
  initializeDragAndDrop()
})

// 在组件卸载时销毁拖拽实例
onUnmounted(() => {
  destroyDragAndDrop()
})

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
  systemContextPairs.value[index][field] = value
}

// 工作流处理方法
const addWorkflowPair = () => {
  workflowPairs.value.push({ key: '', steps: [''] })
  nextTick(() => {
    initializeDragAndDrop()
  })
}

const removeWorkflowPair = (index) => {
  // 销毁对应的步骤拖拽实例
  if (stepSortables.has(index)) {
    stepSortables.get(index).destroy()
    stepSortables.delete(index)
  }
  
  const newPairs = workflowPairs.value.filter((_, i) => i !== index)
  if (newPairs.length === 0) {
    workflowPairs.value = [{ key: '', steps: [''] }]
  } else {
    workflowPairs.value = newPairs
  }
  
  nextTick(() => {
    initializeDragAndDrop()
  })
}

const updateWorkflowPair = (index, field, value) => {
  workflowPairs.value[index][field] = value
}

const addWorkflowStep = (workflowIndex) => {
  workflowPairs.value[workflowIndex].steps.push('')
  nextTick(() => {
    initializeDragAndDrop()
  })
}

const removeWorkflowStep = (workflowIndex, stepIndex) => {
  if (workflowPairs.value[workflowIndex].steps.length > 1) {
    workflowPairs.value[workflowIndex].steps.splice(stepIndex, 1)
    nextTick(() => {
      initializeDragAndDrop()
    })
  }
}

const updateWorkflowStep = (workflowIndex, stepIndex, value) => {
  workflowPairs.value[workflowIndex].steps[stepIndex] = value
}

// Methods
const handleClose = () => {
  emit('update:visible', false)
}

const handleSave = async () => {
  if (!formRef.value) return
  
  try {
    await formRef.value.validate()
    saving.value = true
    
    // 从键值对构建系统上下文对象
    const systemContext = {}
    systemContextPairs.value.forEach(pair => {
      if (pair.key.trim() && pair.value.trim()) {
        systemContext[pair.key.trim()] = pair.value.trim()
      }
    })
    
    // 从键值对构建工作流对象
    const availableWorkflows = {}
    workflowPairs.value.forEach(pair => {
      if (pair.key && pair.key.trim() && pair.steps && pair.steps.some(step => step && step.trim())) {
        const steps = pair.steps
          .filter(step => step && typeof step === 'string')
          .map(step => step.trim())
          .filter(step => step)
        if (steps.length > 0) {
          availableWorkflows[pair.key.trim()] = steps
        }
      }
    })
    
    // 准备保存的数据
    const saveData = {
      ...formData.value,
      systemContext,
      availableWorkflows
    }
    
    // 如果是新建，移除id
    if (!isEditing.value) {
      delete saveData.id
    }
    
    emit('save', saveData)
    
  } catch (error) {
    console.error('表单验证失败:', error)
  } finally {
    saving.value = false
  }
}

// Expose methods
defineExpose({
  formRef
})
</script>

<style scoped>
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

:deep(.el-form-item__label) {
  font-weight: 500;
  color: var(--text-primary);
}

:deep(.el-input__wrapper) {
  border-radius: 6px;
}

:deep(.el-textarea__inner) {
  border-radius: 6px;
}

:deep(.el-select) {
  width: 100%;
}

.context-editor {
  margin-bottom: 20px;
}

.context-pair {
  margin-bottom: 10px;
}

.workflow-editor {
  margin-bottom: 20px;
}

.workflow-item {
  margin-bottom: 15px;
}

.workflow-steps {
  padding: 10px 0;
}

.workflow-step {
  margin-bottom: 8px;
}

:deep(.el-card__header) {
  padding: 10px 20px;
}

:deep(.el-card__body) {
  padding: 15px 20px;
}

/* 拖拽相关样式 */
.workflow-drag-handle,
.drag-handle {
  cursor: grab;
  color: #909399;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
  border-radius: 4px;
  transition: all 0.2s;
}

.workflow-drag-handle:hover,
.drag-handle:hover {
  color: #409eff;
  background-color: #f0f9ff;
}

.workflow-drag-handle:active,
.drag-handle:active {
  cursor: grabbing;
}

.sortable-ghost {
  opacity: 0.5;
  background-color: #f0f9ff;
  border: 2px dashed #409eff;
}

.sortable-chosen {
  transform: scale(1.02);
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.3);
}

.sortable-drag {
  transform: rotate(5deg);
  opacity: 0.8;
}

.step-item {
  margin-bottom: 8px;
  padding: 8px;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  background-color: #fafafa;
  transition: all 0.2s;
}

.step-item:hover {
  border-color: #409eff;
  background-color: #f0f9ff;
}
</style>