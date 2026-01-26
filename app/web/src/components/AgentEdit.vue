<template>
  <div class="agent-edit-container">
    <el-form ref="formRef" :model="formData" :rules="rules" label-width="120px" label-position="left">
      <div class="form-content">
        <!-- 左侧：基本配置 -->
        <div class="left-panel">
          <el-form-item :label="t('agent.name')" prop="name">
            <el-input v-model="formData.name" :placeholder="t('agent.namePlaceholder')"
              :disabled="formData.id === 'default'" />
          </el-form-item>

          <el-form-item :label="t('agent.description')" prop="description">
            <el-input v-model="formData.description" type="textarea" :rows="3"
              :placeholder="t('agent.descriptionPlaceholder')" />
          </el-form-item>

          <el-form-item :label="t('agent.systemPrefix')" prop="systemPrefix">
            <div class="system-prefix-wrapper">
              <el-input v-model="formData.systemPrefix" type="textarea" :rows="25"
                :placeholder="t('agent.systemPrefixPlaceholder')" />
              <el-button class="optimize-btn-inline" size="small"
                         @click="openOptimizeModal" :disabled="isOptimizing">
                优化系统提示词
              </el-button>
            </div>
          </el-form-item>

          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item :label="t('agent.deepThinking')">
                <el-select v-model="formData.deepThinking" :placeholder="t('agent.selectOption')">
                  <el-option :label="t('agent.auto')" :value="null" />
                  <el-option :label="t('agent.enabled')" :value="true" />
                  <el-option :label="t('agent.disabled')" :value="false" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item :label="t('agent.multiAgent')">
                <el-select v-model="formData.multiAgent" :placeholder="t('agent.selectOption')">
                  <el-option :label="t('agent.auto')" :value="null" />
                  <el-option :label="t('agent.enabled')" :value="true" />
                  <el-option :label="t('agent.disabled')" :value="false" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item :label="t('agent.moreSuggest')">
                <el-switch v-model="formData.moreSuggest" :active-text="t('agent.enabled')"
                  :inactive-text="t('agent.disabled')" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item :label="t('agent.maxLoopCount')">
                <el-input-number v-model="formData.maxLoopCount" :min="1" :max="50" :step="1" />
              </el-form-item>
            </el-col>
          </el-row>

          
        </div>

        <!-- 中间分隔线 -->
        <div class="divider-line"></div>

        <!-- 右侧：系统上下文和工作流 -->
        <div class="right-panel">
          <!-- LLM 配置 -->
          <el-divider content-position="left">{{ t('agent.llmConfig') }}</el-divider>

          <el-form-item :label="t('agent.apiKey')">
            <el-input v-model="formData.llmConfig.apiKey" type="password" :placeholder="t('agent.apiKeyPlaceholder')"
              show-password />
          </el-form-item>

          <el-form-item :label="t('agent.baseUrl')">
            <el-input v-model="formData.llmConfig.baseUrl" :placeholder="t('agent.baseUrlPlaceholder')" />
          </el-form-item>

          <el-form-item :label="t('agent.model')">
            <el-input v-model="formData.llmConfig.model" :placeholder="t('agent.modelPlaceholder')" />
          </el-form-item>
          <el-divider content-position="left">{{ t('agent.mcpConfig') }}</el-divider>
          <el-form-item :label="t('agent.availableTools')">
            <el-select v-model="formData.availableTools" multiple :placeholder="t('agent.selectTools')"
              style="width: 100%">
              <el-option v-for="tool in props.tools" :key="tool.name" :label="tool.name" :value="tool.name" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('agent.availableSkills')">
            <el-select v-model="formData.availableSkills" multiple :placeholder="t('agent.selectSkills')"
              style="width: 100%">
              <el-option v-for="skill in props.skills" :key="skill" :label="skill" :value="skill" />
            </el-select>
          </el-form-item>
          <!-- 系统上下文 -->
          <el-divider content-position="left">{{ t('agent.systemContext') }}</el-divider>

          <div class="context-editor">
            <div v-for="(pair, index) in systemContextPairs" :key="index" class="context-pair">
              <el-row :gutter="10" align="middle">
                <el-col :span="10">
                  <el-input v-model="pair.key" :placeholder="t('agent.contextKey')"
                    @input="updateSystemContextPair(index, 'key', $event)" />
                </el-col>
                <el-col :span="10">
                  <el-input v-model="pair.value" :placeholder="t('agent.contextValue')"
                    @input="updateSystemContextPair(index, 'value', $event)" />
                </el-col>
                <el-col :span="4">
                  <el-button type="danger" size="small" @click="removeSystemContextPair(index)"
                    :disabled="systemContextPairs.length === 1 && !pair.key && !pair.value">
                    <el-icon>
                      <Delete />
                    </el-icon>
                  </el-button>
                </el-col>
              </el-row>
            </div>
            <el-button type="primary" size="small" @click="addSystemContextPair" style="margin-top: 10px;">
              {{ t('agent.addContext') }}
            </el-button>
          </div>

          <!-- 工作流 -->
          <el-divider content-position="left">{{ t('agent.workflows') }}</el-divider>

          <div class="workflow-editor">
            <div ref="workflowContainer" class="workflow-container">
              <div v-for="(workflow, index) in workflowPairs" :key="`workflow-${index}`" class="workflow-item"
                :data-index="index">
                <el-card shadow="never" style="margin-bottom: 10px;">
                  <template #header>
                    <el-row :gutter="10" align="middle">
                      <el-col :span="2">
                        <div class="drag-handle workflow-drag-handle">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2">
                            <circle cx="9" cy="12" r="1" />
                            <circle cx="9" cy="5" r="1" />
                            <circle cx="9" cy="19" r="1" />
                            <circle cx="15" cy="12" r="1" />
                            <circle cx="15" cy="5" r="1" />
                            <circle cx="15" cy="19" r="1" />
                          </svg>
                        </div>
                      </el-col>
                      <el-col :span="16">
                        <el-input v-model="workflow.key" :placeholder="t('agent.workflowName')"
                          @input="updateWorkflowPair(index, 'key', $event)" />
                      </el-col>
                      <el-col :span="6">
                        <el-button type="text" size="small" @click.stop="toggleWorkflowCollapse(index)"
                          style="margin-right: 8px;">
                          <el-icon style="font-weight: bold;">
                            <component :is="workflowCollapsed[index] ? 'ArrowDown' : 'ArrowUp'" />
                          </el-icon>
                        </el-button>
                        <el-button type="danger" size="small" @click="removeWorkflowPair(index)"
                          :title="t('common.delete')">
                          <el-icon>
                            <Delete />
                          </el-icon>
                        </el-button>
                      </el-col>
                    </el-row>
                  </template>

                  <transition name="workflow-collapse">
                    <div class="workflow-steps" v-show="!workflowCollapsed[index]">
                      <div class="steps-container" :ref="el => setStepContainer(el, index)">
                        <div v-for="(step, stepIndex) in workflow.steps" :key="`step-${index}-${stepIndex}`"
                          class="step-item" :data-step-index="stepIndex">
                          <el-row :gutter="10" align="middle">
                            <el-col :span="2">
                              <div class="drag-handle">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                                  <path
                                    d="M9 3h2v2H9V3zm0 4h2v2H9V7zm0 4h2v2H9v-2zm0 4h2v2H9v-2zm0 4h2v2H9v-2zm0 4h2v2H9v-2zm4-16h2v2h-2V3zm0 4h2v2h-2V7zm0 4h2v2h-2v-2zm0 4h2v2h-2v-2zm0 4h2v2h-2v-2z" />
                                </svg>
                              </div>
                            </el-col>
                            <el-col :span="18">
                              <el-input v-model="workflow.steps[stepIndex]" type="textarea"
                                :placeholder="`${t('agent.step')} ${stepIndex + 1}`"
                                @input="updateWorkflowStep(index, stepIndex, $event)"
                                :autosize="{ minRows: 2, maxRows: 6 }" resize="vertical" />
                            </el-col>
                            <el-col :span="4">
                              <el-button type="danger" size="small" @click="removeWorkflowStep(index, stepIndex)"
                                :disabled="workflow.steps.length === 1">
                                <el-icon>
                                  <Delete />
                                </el-icon>
                              </el-button>
                            </el-col>
                          </el-row>
                        </div>
                      </div>
                      <el-button type="primary" size="small" @click="addWorkflowStep(index)" style="margin-top: 5px;">
                        {{ t('agent.addStep') }}
                      </el-button>
                    </div>
                  </transition>
                </el-card>
              </div>
            </div>
            <el-button type="primary" @click="addWorkflowPair" style="margin-top: 10px;">
              {{ t('agent.addWorkflow') }}
            </el-button>
          </div>
        </div>
      </div>
    </el-form>

    <div class="form-footer">
      <el-button @click="handleClose">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" @click="handleSave">
        {{ t('common.save') }}
      </el-button>
    </div>

    <!-- 优化对话框 -->
    <el-dialog v-model="showOptimizeModal" title="优化系统提示词" width="640px" :close-on-click-modal="false"
               :close-on-press-escape="!isOptimizing" :show-close="!isOptimizing">
      <div class="form-group">
        <label class="form-label">优化目标 <span class="optional-text">(可选)</span></label>
        <el-input v-model="optimizationGoal" type="textarea" :rows="3"
                  placeholder="例如：提高专业性和准确性，增强工具使用能力..."
                  :disabled="isOptimizing || !!optimizedResult" />
        <div class="help-text">如果不填写优化目标，系统将进行通用优化</div>
      </div>

      <div v-if="optimizedResult" class="form-group" style="margin-top: 12px;">
        <label class="form-label">优化结果预览 <span class="help-text-inline">（可编辑）</span></label>
        <el-input v-model="optimizedResult" type="textarea" :rows="8"
                  placeholder="优化结果将显示在这里，您可以直接编辑..." />
        <div class="help-text">您可以直接编辑优化结果，确认无误后点击"应用优化"按钮</div>
      </div>

      <template #footer>
        <el-button @click="handleOptimizeCancel" :disabled="isOptimizing">取消</el-button>
        <template v-if="optimizedResult">
          <el-button type="default" @click="handleResetOptimization">重新优化</el-button>
          <el-button type="primary" @click="handleApplyOptimization">应用优化</el-button>
        </template>
        <template v-else>
          <el-button type="primary" :loading="isOptimizing" @click="handleOptimizeStart" :disabled="isOptimizing">
            开始优化
          </el-button>
        </template>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useLanguage } from '../utils/i18n.js'
import { ArrowDown, ArrowUp, Delete } from '@element-plus/icons-vue'
import Sortable from 'sortablejs'
import {agentAPI} from '../api/agent.js'

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
const formRef = ref(null)
const saving = ref(false)
const systemContextPairs = ref([{ key: '', value: '' }])
const workflowPairs = ref([{ key: '', steps: [''] }])
const workflowCollapsed = ref([]) // 工作流收缩状态
const workflowContainer = ref(null)
const stepContainers = ref(new Map())
const isInternalEdit = ref(false) // 标记是否为内部编辑

// Sortable instances
let workflowSortable = null
const stepSortables = new Map()

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
  maxLoopCount: 10,
  llmConfig: {
    apiKey: '',
    baseUrl: '',
    model: ''
  },
  availableTools: [],
  availableSkills: [],
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
  // 如果是内部编辑导致的变化，跳过处理
  if (isInternalEdit.value) {
    return
  }

  if (newAgent) {
    formData.value = {
      ...defaultFormData(),
      ...newAgent
    }

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
      ? workflowEntries.map(([key, value]) => ({
        key,
        steps: Array.isArray(value) ? value : (typeof value === 'string' ? value.split(',').map(s => s.trim()).filter(s => s) : [''])
      }))
      : [{ key: '', steps: [''] }]

    // 初始化工作流收缩状态（默认全部展开）
    workflowCollapsed.value = new Array(workflowPairs.value.length).fill(true)
  } else {
    formData.value = defaultFormData()
    systemContextPairs.value = [{ key: '', value: '' }]
    workflowPairs.value = [{ key: '', steps: [''] }]
    workflowCollapsed.value = [false]
  }

  // 重新初始化拖拽功能
  nextTick(() => {
    initializeDragAndDrop()
  })
}, { immediate: true })

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

// 在组件挂载时初始化拖拽
onMounted(() => {
  initializeDragAndDrop()
})

// 在组件卸载时销毁拖拽实例
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
  // 确保value是字符串类型
  systemContextPairs.value[index][field] = typeof value === 'string' ? value : String(value || '')
}

// 工作流处理方法
const addWorkflowPair = () => {
  workflowPairs.value.push({ key: '', steps: [''] })
  workflowCollapsed.value.push(false) // 新工作流默认展开
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
    workflowCollapsed.value = [false] // 重置收缩状态
  } else {
    workflowPairs.value = newPairs
    workflowCollapsed.value.splice(index, 1) // 删除对应的收缩状态
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
  workflowPairs.value[workflowIndex].steps.push('')
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
  workflowPairs.value[workflowIndex].steps[stepIndex] = value
  // 使用 nextTick 确保在下一个事件循环中重置标志
  nextTick(() => {
    isInternalEdit.value = false
  })
}

// 工作流收缩状态管理
const toggleWorkflowCollapse = (index) => {
  workflowCollapsed.value[index] = !workflowCollapsed.value[index]
}

const syncWorkflowCollapsedState = () => {
  // 确保收缩状态数组与工作流数组长度一致
  const currentLength = workflowPairs.value.length
  const collapsedLength = workflowCollapsed.value.length

  if (collapsedLength < currentLength) {
    // 添加新的收缩状态（默认展开）
    for (let i = collapsedLength; i < currentLength; i++) {
      workflowCollapsed.value.push(false)
    }
  } else if (collapsedLength > currentLength) {
    // 移除多余的收缩状态
    workflowCollapsed.value.splice(currentLength)
  }
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
      // 确保key和value都是字符串类型
      const key = typeof pair.key === 'string' ? pair.key.trim() : ''
      const value = typeof pair.value === 'string' ? pair.value.trim() : ''
      if (key && value) {
        systemContext[key] = value
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
.agent-edit-container {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 24px;
  margin: 20px 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  overflow-y: auto;
  max-height: calc(100vh - 120px);
}

.form-content {
  display: flex;
  gap: 24px;
  min-height: 500px;
}

.left-panel {
  flex: 1;
  min-width: 0;
}

.divider-line {
  width: 2px;
  background: repeating-linear-gradient(to bottom,
      #e5e7eb 0px,
      #e5e7eb 8px,
      transparent 8px,
      transparent 16px);
  flex-shrink: 0;
  margin: 0 12px;
}

.right-panel {
  flex: 1;
  min-width: 0;
}

.form-header {
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e5e7eb;
}

.form-title {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  color: #1f2937;
}

.form-footer {
  display: flex;
  justify-content: center;
  gap: 12px;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #e5e7eb;
}

/* 响应式设计 */
@media (max-width: 1200px) {
  .form-content {
    flex-direction: column;
    gap: 16px;
  }

  .divider-line {
    width: 100%;
    height: 2px;
    background: repeating-linear-gradient(to right,
        #e5e7eb 0px,
        #e5e7eb 8px,
        transparent 8px,
        transparent 16px);
    margin: 12px 0;
  }
}

:deep(.el-form-item__label) {
  font-weight: 500;
  color: #1f2937;
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

/* 系统提示词输入框内按钮定位 */
.system-prefix-wrapper {
  position: relative;
  width: 100%; /* 让系统提示词输入区域占满到左侧面板的分割线 */
}

.system-prefix-wrapper :deep(.el-textarea__inner) {
  padding-right: 120px; /* 为内嵌按钮留出空间，避免文本遮挡 */
}

/* 保证 textarea 组件本身也占满可用宽度 */
.system-prefix-wrapper :deep(.el-textarea) {
  width: 100%;
}

.optimize-btn-inline {

  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  background: transparent;
  color: #0000005f; /* 黑色文字 */
  border-color: transparent;
  box-shadow: none;
  --el-button-bg-color: transparent;
  --el-button-border-color: transparent;
  --el-button-text-color: #111827;
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

/* 工作流收缩/展开动画 */
.workflow-collapse-enter-active,
.workflow-collapse-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.workflow-collapse-enter-from,
.workflow-collapse-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.workflow-collapse-enter-to,
.workflow-collapse-leave-from {
  opacity: 1;
  max-height: 1000px;
}

/* 工作流步骤textarea样式 */
.workflow-steps .el-textarea__inner {
  min-height: 60px;
  line-height: 1.5;
  font-family: inherit;
}

.workflow-steps .el-textarea {
  width: 100%;
}

.step-item .el-textarea__inner:focus {
  border-color: #409eff;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.2);
}
</style>
