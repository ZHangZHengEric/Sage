import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

export const useAgentEditStore = defineStore('agent-edit', () => {
  // Constants
  const STEPS = [
    { id: 1, key: 'basic', label: '基础配置' },
    { id: 2, key: 'capabilities', label: '能力扩展' }
  ]

  // State
  const currentStep = ref(1)
  const isInternalEdit = ref(false)
  const errors = ref({})
  const saving = ref(false)
  
  // Default Data
  const defaultFormData = {
    id: null,
    name: '',
    description: '',
    systemPrefix: '',
    deepThinking: false,
    agentMode: 'simple',
    moreSuggest: false,
    memoryType: "session",
    maxLoopCount: 10,
    llm_provider_id: null,
    llmConfig: {},
    systemContext: {},
    availableTools: [],
    availableSkills: [],
    availableKnowledgeBases: [],
    availableWorkflows: {},
    availableSubAgentIds: []
  }

  const formData = ref(JSON.parse(JSON.stringify(defaultFormData)))

  // Helper to generate unique IDs for UI tracking
  const generateId = () => Date.now().toString(36) + Math.random().toString(36).substr(2)

  // Helper State for complex fields (Workflows, Context)
  // These are transformed to/from formData when saving/loading
  const systemContextPairs = ref([{ key: '', value: '' }])
  const workflowPairs = ref([{ id: generateId(), key: '', steps: [''] }])

  // Computed
  const isStep1Valid = computed(() => {
    return !!formData.value.name
  })

  const isCurrentStepValid = computed(() => {
    if (currentStep.value === 1) return isStep1Valid.value
    return true // Other steps have optional fields mostly
  })

  // Actions
  const addSystemContextPair = () => {
    systemContextPairs.value.push({ key: '', value: '' })
  }

  const removeSystemContextPair = (index) => {
    if (systemContextPairs.value.length > 1) {
      systemContextPairs.value.splice(index, 1)
    } else {
      systemContextPairs.value[0] = { key: '', value: '' }
    }
  }

  const updateSystemContextPair = (index, field, value) => {
    systemContextPairs.value[index][field] = value
  }

  const addWorkflowPair = () => {
    workflowPairs.value.push({ id: generateId(), key: '', steps: [''] })
  }

  const removeWorkflowPair = (index) => {
    workflowPairs.value.splice(index, 1)
  }

  const updateWorkflowPair = (index, field, value) => {
    workflowPairs.value[index][field] = value
  }

  const addWorkflowStep = (workflowIndex) => {
    workflowPairs.value[workflowIndex].steps.push('')
  }

  const removeWorkflowStep = (workflowIndex, stepIndex) => {
    const steps = workflowPairs.value[workflowIndex].steps
    if (steps.length > 1) {
      steps.splice(stepIndex, 1)
    } else {
      steps[0] = ''
    }
  }

  const updateWorkflowStep = (workflowIndex, stepIndex, value) => {
    workflowPairs.value[workflowIndex].steps[stepIndex] = value
  }

  const toggleTool = (name) => {
    if (!Array.isArray(formData.value.availableTools)) formData.value.availableTools = []
    const list = formData.value.availableTools
    const index = list.indexOf(name)
    if (index === -1) list.push(name)
    else list.splice(index, 1)
  }

  const toggleSkill = (name) => {
    if (!Array.isArray(formData.value.availableSkills)) formData.value.availableSkills = []
    const list = formData.value.availableSkills
    const index = list.indexOf(name)
    if (index === -1) list.push(name)
    else list.splice(index, 1)
  }

  const toggleKnowledgeBase = (id) => {
    if (!Array.isArray(formData.value.availableKnowledgeBases)) formData.value.availableKnowledgeBases = []
    const list = formData.value.availableKnowledgeBases
    const index = list.indexOf(id)
    if (index === -1) list.push(id)
    else list.splice(index, 1)
  }

  const initForm = (agentData = null, options = {}) => {
    const { preserveStep = false } = options

    if (agentData) {
      formData.value = JSON.parse(JSON.stringify({ ...defaultFormData, ...agentData }))
      if (!Array.isArray(formData.value.availableTools)) formData.value.availableTools = []
      if (!Array.isArray(formData.value.availableSkills)) formData.value.availableSkills = []
      if (!Array.isArray(formData.value.availableKnowledgeBases)) formData.value.availableKnowledgeBases = []
      if (!Array.isArray(formData.value.availableSubAgentIds)) formData.value.availableSubAgentIds = []
      if (!formData.value.systemContext || typeof formData.value.systemContext !== 'object') formData.value.systemContext = {}
      if (!formData.value.availableWorkflows || typeof formData.value.availableWorkflows !== 'object') formData.value.availableWorkflows = {}
      if (!formData.value.llmConfig || typeof formData.value.llmConfig !== 'object') {
        formData.value.llmConfig = JSON.parse(JSON.stringify(defaultFormData.llmConfig))
      }
      // Parse context and workflows back to pairs
      systemContextPairs.value = Object.entries(formData.value.systemContext || {}).map(([k, v]) => ({ key: k, value: v }))
      if (systemContextPairs.value.length === 0) systemContextPairs.value.push({ key: '', value: '' })

      workflowPairs.value = Object.entries(formData.value.availableWorkflows || {}).map(([k, v]) => ({ id: generateId(), key: k, steps: v }))
      if (workflowPairs.value.length === 0) workflowPairs.value.push({ id: generateId(), key: '', steps: [''] })
    } else {
      formData.value = JSON.parse(JSON.stringify(defaultFormData))
      systemContextPairs.value = [{ key: '', value: '' }]
      workflowPairs.value = [{ id: generateId(), key: '', steps: [''] }]
    }
    
    if (!preserveStep) {
      currentStep.value = 1
    }
    errors.value = {}
  }

  const validateStep1 = () => {
    const newErrors = {}
    if (!formData.value.name) newErrors.name = '名称不能为空'
    
    // Character limits
    if (formData.value.description && formData.value.description.length > 500) {
      newErrors.description = '描述不能超过500字'
    }
    if (formData.value.systemPrefix && formData.value.systemPrefix.length > 20000) { // Arbitrary large limit
       newErrors.systemPrefix = '系统提示词过长'
    }

    errors.value = newErrors
    return Object.keys(newErrors).length === 0
  }

  const nextStep = () => {
    if (currentStep.value === 1) {
      if (!validateStep1()) return
    }
    if (currentStep.value < STEPS.length) {
      currentStep.value++
    }
  }

  const prevStep = () => {
    if (currentStep.value > 1) {
      currentStep.value--
    }
  }

  const setStep = (stepId) => {
    // Can only jump to steps if previous steps are valid
    if (stepId === currentStep.value) return

    // If target step is greater than 1, step 1 must be valid
    if (stepId > 1 && !validateStep1()) {
      // If currently not at step 1, go to step 1 to show errors
      if (currentStep.value !== 1) {
        currentStep.value = 1
      }
      return
    }

    currentStep.value = stepId
  }

  // Sync complex fields to formData before save
  const prepareForSave = () => {
    // Context
    const context = {}
    systemContextPairs.value.forEach(p => {
      if (p.key) context[p.key] = p.value
    })
    formData.value.systemContext = context

    // Workflows
    const workflows = {}
    workflowPairs.value.forEach(p => {
      if (p.key) workflows[p.key] = p.steps.filter(s => s)
    })
    formData.value.availableWorkflows = workflows
  }

  // Persist to localStorage for draft
  watch(formData, (newVal) => {
    localStorage.setItem('agent_edit_draft', JSON.stringify(newVal))
  }, { deep: true })


  return {
    STEPS,
    currentStep,
    formData,
    errors,
    saving,
    systemContextPairs,
    workflowPairs,
    isStep1Valid,
    isCurrentStepValid,
    initForm,
    nextStep,
    prevStep,
    setStep,
    validateStep1,
    prepareForSave,
    addSystemContextPair,
    removeSystemContextPair,
    updateSystemContextPair,
    addWorkflowPair,
    removeWorkflowPair,
    updateWorkflowPair,
    addWorkflowStep,
    removeWorkflowStep,
    updateWorkflowStep,
    toggleTool,
    toggleSkill,
    toggleKnowledgeBase
  }
})
