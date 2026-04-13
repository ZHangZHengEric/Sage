<template>
  <div class="h-screen w-full bg-background text-foreground flex flex-col overflow-hidden">
    <!-- Welcome Step: Animated Introduction -->
    <div v-if="step === 'welcome'" class="flex-1 flex flex-col items-center justify-center p-8 overflow-y-auto">
      <div class="max-w-4xl w-full flex flex-col items-center text-center space-y-12 py-8 animate-in fade-in zoom-in-95 duration-700">
        
        <!-- Animated Logo -->
        <div class="relative">
          <div class="absolute inset-0 bg-primary/30 blur-3xl rounded-full animate-pulse"></div>
          <div class="relative p-8  from-primary/20 to-primary/5 rounded-3xl  backdrop-blur-sm">
            <Bot class="w-24 h-24 text-primary animate-bounce" style="animation-duration: 2s;" />
          </div>
        </div>

        <div class="space-y-4">
          <h1 class="text-4xl md:text-6xl font-bold tracking-tight bg-gradient-to-r from-primary to-primary/60 bg-clip-text text-transparent">
            欢迎使用 Sage
          </h1>
          <p class="text-xl text-muted-foreground max-w-2xl mx-auto leading-relaxed">
            您的智能 AI 工作空间已准备就绪<br>让我们设置您的环境以开始使用
          </p>
        </div>
        
        <!-- Feature Cards with Hover Animation -->
        <div class="grid md:grid-cols-2 gap-6 w-full text-left">
          <div class="group p-8 rounded-2xl bg-gradient-to-br from-muted/50 to-muted/20 border border-transparent hover:border-primary/30 hover:shadow-lg hover:shadow-primary/10 transition-all duration-500 hover:-translate-y-1">
            <div class="flex items-center gap-4 mb-4">
              <div class="p-3 bg-blue-100 dark:bg-blue-900/30 rounded-xl group-hover:scale-110 transition-transform duration-300">
                <Brain class="w-6 h-6 text-blue-600 dark:text-blue-400" />
              </div>
              <h3 class="text-xl font-semibold">模型提供商</h3>
            </div>
            <p class="text-muted-foreground leading-relaxed">
              AI 的"大脑"。连接到 OpenAI、DeepSeek 或其他服务以为您的代理提供动力。
            </p>
          </div>
          
          <div class="group p-8 rounded-2xl bg-gradient-to-br from-muted/50 to-muted/20 border border-transparent hover:border-green-500/30 hover:shadow-lg hover:shadow-green-500/10 transition-all duration-500 hover:-translate-y-1">
            <div class="flex items-center gap-4 mb-4">
              <div class="p-3 bg-green-100 dark:bg-green-900/30 rounded-xl group-hover:scale-110 transition-transform duration-300">
                <MessageSquare class="w-6 h-6 text-green-600 dark:text-green-400" />
              </div>
              <h3 class="text-xl font-semibold">智能体</h3>
            </div>
            <p class="text-muted-foreground leading-relaxed">
              您与之交互的"角色"。定义它的行为方式、使用的工具及其个性。
            </p>
          </div>
        </div>

        <!-- Animated Button -->
        <Button size="lg" @click="handleWelcomeNext" class="px-12 py-6 text-lg rounded-full shadow-lg shadow-primary/25 hover:shadow-xl hover:shadow-primary/30 transition-all duration-300 hover:scale-105 group">
          开始使用
          <ArrowRight class="ml-2 w-6 h-6 group-hover:translate-x-1 transition-transform" />
        </Button>
      </div>
    </div>

    <!-- Model Provider Step: Animated Form -->
    <div v-else-if="step === 'model'" class="flex-1 overflow-y-auto bg-background">
      <div class="min-h-full flex flex-col items-center justify-center p-4">
        <!-- Header -->
        <div class="space-y-2 text-center mb-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
          <h2 class="text-3xl font-bold bg-gradient-to-r from-primary to-primary/60 bg-clip-text text-transparent">
            {{ currentStepTitle }}
          </h2>
          <p class="text-lg text-muted-foreground">{{ currentStepDescription }}</p>
        </div>

        <div class="w-full max-w-3xl flex gap-6 items-start justify-center">
          
          <!-- Left Side: Form Content -->
          <div class="flex-1 max-w-2xl space-y-6">
    
            <!-- Provider Selection Card -->
            <div class="bg-card/50 p-8 rounded-2xl border shadow-sm backdrop-blur-sm animate-in fade-in slide-in-from-bottom-4 duration-500 delay-200">
              <!-- Provider Selection with Toggle -->
              <div class="space-y-4">
                <div class="flex items-center justify-between">
                  <Label class="text-base font-medium">模型提供商 <span class="text-destructive">*</span></Label>
                  <button 
                    @click="toggleProviderInputMode" 
                    class="text-sm text-muted-foreground hover:text-primary transition-colors underline underline-offset-2"
                  >
                    {{ providerInputMode === 'select' ? '自定义模型提供商' : '使用推荐提供商' }}
                  </button>
                </div>
                
                <!-- Provider Select Mode -->
                <Select v-if="providerInputMode === 'select'" v-model="selectedProvider" @update:model-value="handleProviderChange">
                  <SelectTrigger class="h-12">
                    <SelectValue placeholder="请选择模型提供商" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem v-for="provider in MODEL_PROVIDERS" :key="provider.name" :value="provider.name">
                        <div class="flex items-center gap-3">
                          <span class="font-medium shrink-0">{{ provider.name }}</span>
                          <span class="text-xs text-muted-foreground truncate">{{ provider.base_url }}</span>
                        </div>
                      </SelectItem>
                    </SelectGroup>
                  </SelectContent>
                </Select>
                
                <!-- Provider Custom Input Mode -->
                <div v-else class="space-y-3">
                  <Input 
                    v-model="customProviderName" 
                    placeholder="请输入提供商名称，如：My Custom Provider" 
                    class="h-12"
                    @update:model-value="onCustomProviderChange"
                  />
                  <Input 
                    v-model="modelForm.base_url" 
                    placeholder="请输入符合OpenAI 规范的Base URL，如：https://api.example.com/v1" 
                    class="h-12"
                    @update:model-value="onKeyConfigChange"
                  />
                </div>
              </div>
            </div>

            <!-- Config Fields (Animated Appear) -->
            <div 
              v-if="showConfigFields" 
              class="space-y-6 bg-card/50 p-8 rounded-2xl border shadow-sm backdrop-blur-sm config-fields-appear"
            >
                <!-- Base URL (only for custom mode) -->
                <div v-if="providerInputMode === 'custom'" class="grid gap-2">
                  <Label class="text-base">{{ t('modelProvider.baseUrl') }} <span class="text-destructive">*</span></Label>
                  <Input v-model="modelForm.base_url" placeholder="https://api.example.com/v1" class="h-12" @update:model-value="onKeyConfigChange" />
                </div>

                <!-- API Key -->
                <div class="grid gap-2">
                  <div class="flex items-center justify-between">
                    <Label class="text-base">{{ t('modelProvider.apiKey') }} <span class="text-destructive">*</span></Label>
                    <Button
                      v-if="currentProvider?.website"
                      variant="link"
                      size="sm"
                      class="h-auto p-0 text-primary"
                      @click="openProviderWebsite"
                    >
                      获取 API Key
                      <ArrowRight class="ml-1 w-3 h-3" />
                    </Button>
                  </div>
                  <Input v-model="modelForm.api_keys_str" :placeholder="t('modelProvider.apiKeyPlaceholder')" class="h-12" @update:model-value="onKeyConfigChange" />
                </div>

                <!-- Model Selection -->
                <div class="grid gap-3">
                  <div class="flex items-center justify-between">
                    <Label class="text-base">模型名称 <span class="text-destructive">*</span></Label>
                    <!-- 只有选择预设提供商时才显示切换按钮 -->
                    <button 
                      v-if="providerInputMode === 'select'"
                      @click="toggleModelInputMode" 
                      class="text-sm text-muted-foreground hover:text-primary transition-colors underline underline-offset-2"
                    >
                      {{ modelInputMode === 'select' ? '自定义模型名称' : '使用推荐模型' }}
                    </button>
                  </div>
                  
                  <!-- Model Select Mode (only for preset providers) -->
                  <Select v-if="providerInputMode === 'select' && modelInputMode === 'select'" v-model="modelForm.model" @update:model-value="onKeyConfigChange">
                    <SelectTrigger class="h-12">
                      <SelectValue placeholder="请选择模型" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        <SelectItem v-for="model in currentProviderModels" :key="model" :value="model">
                          {{ model }}
                        </SelectItem>
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  
                  <!-- Model Custom Input Mode (for custom providers or when toggled) -->
                  <Input 
                    v-else
                    v-model="customModelName" 
                    placeholder="请输入模型名称" 
                    class="h-12"
                    @update:model-value="onCustomModelChange"
                  />
                  
                </div>
              </div>
          </div>

          <!-- Right Side: Action Button -->
          <div class="self-center animate-in fade-in slide-in-from-right-4 duration-500 delay-300 ml-4">
            <Button 
              size="lg" 
              @click="handleModelSubmit" 
              :disabled="loading || !canSave" 
              class="w-14 h-14 rounded-full p-0 flex items-center justify-center shadow-lg shadow-primary/25 hover:shadow-xl hover:shadow-primary/30 transition-all duration-300 hover:scale-105"
            >
              <Loader v-if="loading" class="w-6 h-6 animate-spin" />
              <ArrowRight v-else class="w-6 h-6" />
            </Button>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Creating Agent State -->
    <div v-else-if="step === 'creating_agent'" class="flex-1 flex items-center justify-center">
      <div class="flex flex-col items-center gap-6">
        <div class="relative">
          <div ref="agentLottieContainer" class="w-48 h-48"></div>
          <div class="absolute inset-0 bg-primary/20 blur-3xl rounded-full animate-pulse"></div>
        </div>
        <div class="text-center space-y-2">
          <h3 class="text-xl font-semibold">正在初始化 Agent...</h3>
          <p class="text-muted-foreground">请稍候，即将进入您的工作空间</p>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useLanguage } from '@/utils/i18n'
import { systemAPI } from '@/api/system'
import { modelProviderAPI } from '@/api/modelProvider'
import { agentAPI } from '@/api/agent'
import { toolAPI } from '@/api/tool'
import { skillAPI } from '@/api/skill'
import { toast } from 'vue-sonner'
import { Loader, Bot, Brain, MessageSquare, ArrowRight, RefreshCw, CheckCircle } from 'lucide-vue-next'
import { open } from '@tauri-apps/plugin-shell'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { MODEL_PROVIDERS } from '@/utils/modelProviders'

const router = useRouter()
const { t } = useLanguage()



// Steps: loading, welcome, model, creating_agent
const step = ref('loading')
const loading = ref(false)
const verifying = ref(false)
const verified = ref(false)
const tools = ref([])
const skills = ref([])
const systemStatus = ref({
  has_model_provider: false,
  has_agent: false
})

// Input Mode Toggles
const providerInputMode = ref('select') // 'select' | 'custom'
const modelInputMode = ref('select') // 'select' | 'custom'
const showConfigFields = ref(false)

// Model Form State
const modelForm = reactive({
  name: '',
  base_url: '',
  api_keys_str: '',
  model: '',
  supportsMultimodal: false,
  supportsStructuredOutput: false
})

const DEFAULT_TEMPERATURE = 0.3
const DEFAULT_TOP_P = 0.95
const DEFAULT_PRESENCE_PENALTY = 0
const DEFAULT_MAX_MODEL_LEN = 64000

const selectedProvider = ref('')
const currentProvider = computed(() => MODEL_PROVIDERS.find(p => p.name === selectedProvider.value))
const currentProviderModels = computed(() => currentProvider.value?.models || [])

// Custom Input Values
const customProviderName = ref('')
const customModelName = ref('')


const canSave = computed(() => {
  // 检查所有必填字段是否已填写
  if (providerInputMode.value === 'select') {
    return selectedProvider.value && modelForm.base_url && modelForm.api_keys_str && 
           (modelInputMode.value === 'custom' ? customModelName.value : modelForm.model)
  } else {
    return customProviderName.value && modelForm.base_url && modelForm.api_keys_str && 
           customModelName.value
  }
})

const actualProviderName = computed(() => {
  return providerInputMode.value === 'select' ? selectedProvider.value : customProviderName.value
})

const actualModelName = computed(() => {
  return modelInputMode.value === 'custom' ? customModelName.value : modelForm.model
})

// Methods
const toggleProviderInputMode = () => {
  providerInputMode.value = providerInputMode.value === 'select' ? 'custom' : 'select'
  // Reset related fields
  if (providerInputMode.value === 'custom') {
    selectedProvider.value = ''
    modelForm.name = ''
    modelForm.base_url = ''
    // 切换到自定义模式时强制使用自定义模型名称
    modelInputMode.value = 'custom'
    modelForm.model = ''
    customModelName.value = ''
    // 切换到自定义模式时显示配置表单
    showConfigFields.value = true
  } else {
    customProviderName.value = ''
    modelForm.name = ''
    modelForm.base_url = ''
    // 切换回预设模式时恢复模型选择模式
    modelInputMode.value = 'select'
    customModelName.value = ''
    showConfigFields.value = false
  }
  verified.value = false
  modelForm.supportsMultimodal = false
  modelForm.supportsStructuredOutput = false
}

const toggleModelInputMode = () => {
  modelInputMode.value = modelInputMode.value === 'select' ? 'custom' : 'select'
  // Reset model field
  if (modelInputMode.value === 'custom') {
    modelForm.model = ''
  } else {
    customModelName.value = ''
  }
  verified.value = false
  modelForm.supportsMultimodal = false
  modelForm.supportsStructuredOutput = false
}

const handleProviderChange = (val) => {
  selectedProvider.value = val
  const provider = MODEL_PROVIDERS.find(p => p.name === val)
  if (provider) {
    modelForm.name = provider.name
    modelForm.base_url = provider.base_url
  }
  verified.value = false
  customModelName.value = ''
  modelForm.supportsMultimodal = false
  modelForm.supportsStructuredOutput = false
  // Show config fields with animation
  showConfigFields.value = true
}

const onCustomProviderChange = (val) => {
  customProviderName.value = val
  modelForm.name = val
  // Show config fields when provider name is entered
  if (val && modelForm.base_url) {
    showConfigFields.value = true
  }
  onKeyConfigChange()
}

const onCustomModelChange = (val) => {
  customModelName.value = val
  onKeyConfigChange()
}

const onKeyConfigChange = () => {
  verified.value = false
  modelForm.supportsMultimodal = false
  modelForm.supportsStructuredOutput = false
}

const buildProviderPayload = () => ({
  name: actualProviderName.value,
  base_url: modelForm.base_url,
  api_keys: modelForm.api_keys_str.trim().split(/[\n,]+/).map(k => k.trim()).filter(k => k),
  model: actualModelName.value,
  temperature: DEFAULT_TEMPERATURE,
  top_p: DEFAULT_TOP_P,
  presence_penalty: DEFAULT_PRESENCE_PENALTY,
  max_model_len: DEFAULT_MAX_MODEL_LEN,
  is_default: true,
  supports_multimodal: modelForm.supportsMultimodal,
  supports_structured_output: modelForm.supportsStructuredOutput
})

const verifyProviderCapabilities = async () => {
  const data = buildProviderPayload()
  const result = await modelProviderAPI.verifyModelProvider(data)
  modelForm.supportsMultimodal = Boolean(result?.supports_multimodal)
  modelForm.supportsStructuredOutput = Boolean(result?.supports_structured_output)

  return {
    ...data,
    supports_multimodal: modelForm.supportsMultimodal,
    supports_structured_output: modelForm.supportsStructuredOutput
  }
}

const openProviderWebsite = async () => {
  if (currentProvider.value?.website) {
    try {
      await open(currentProvider.value.website)
    } catch (error) {
      console.error('Failed to open external link:', error)
      window.open(currentProvider.value.website, '_blank')
    }
  }
}

const currentStepTitle = computed(() => {
  if (step.value === 'model') return '连接模型提供商'
  return '加载中...'
})

const currentStepDescription = computed(() => {
  if (step.value === 'model') return '首先，我们需要连接到一个 LLM 提供商（"大脑"）来为您的智能体提供动力。'
  return '正在检查系统状态...'
})

const redirectToFreshChat = () => {
  router.replace({
    name: 'Chat',
    query: {
      reload_new_chat: Date.now()
    }
  })
}

const fetchSystemInfo = async () => {
  try {
    const res = await systemAPI.getSystemInfo()
    systemStatus.value = res
    
    if (!res.has_model_provider || !res.has_agent) {
      if (res.has_model_provider && !res.has_agent) {
        createDefaultAgent()
      } else {
        step.value = 'welcome'
      }
    } else {
      redirectToFreshChat()
    }
  } catch (error) {
    console.error('Failed to fetch system info:', error)
    toast.error('Failed to initialize system info')
    step.value = 'welcome'
  }
}

const handleWelcomeNext = () => {
  if (!systemStatus.value.has_model_provider) {
    step.value = 'model'
  } else if (!systemStatus.value.has_agent) {
    createDefaultAgent()
  } else {
    redirectToFreshChat()
  }
}

const fetchResources = async () => {
  try {
    const [toolsRes, skillsRes] = await Promise.all([
      toolAPI.getTools(),
      skillAPI.getSkills()
    ])
    tools.value = toolsRes?.tools || []
    skills.value = skillsRes?.skills || []
  } catch (error) {
    console.error('Failed to fetch resources:', error)
  }
}

const handleVerify = async () => {
  if (!actualProviderName.value || !modelForm.base_url || !modelForm.api_keys_str || !actualModelName.value) {
    toast.error('请填写所有必填字段')
    return
  }

  verifying.value = true
  try {
    const data = await verifyProviderCapabilities()
    verified.value = true
    if (data.supports_multimodal && data.supports_structured_output) {
      toast.success('连接验证成功，已检测到多模态和结构化输出支持')
    } else if (data.supports_multimodal) {
      toast.success('连接验证成功，已检测到多模态支持')
    } else if (data.supports_structured_output) {
      toast.success('连接验证成功，已检测到结构化输出支持')
    } else {
      toast.success('连接验证成功')
    }
  } catch (error) {
    console.error('Failed to verify model provider:', error)
    verified.value = false
    toast.error(error.message || '连接验证失败')
  } finally {
    verifying.value = false
  }
}

const createDefaultAgent = async (providerId = null) => {
  step.value = 'creating_agent'
  loading.value = true
  
  try {
    await fetchResources()
    
    let systemPrompt = ''
    try {
      const promptRes = await agentAPI.getDefaultSystemPrompt()
      if (promptRes?.system_prompt) {
        systemPrompt = promptRes.system_prompt
      }
    } catch (e) {
      console.error('Failed to get default system prompt', e)
    }

    let currentProviderId = providerId
    let currentProviderSupportsMultimodal = false
    if (!currentProviderId) {
      try {
        const providers = await modelProviderAPI.listModelProviders()
        if (providers?.length > 0) {
          const defaultProvider = providers.find(p => p.is_default)
          const selectedProvider = defaultProvider || providers[0]
          currentProviderId = selectedProvider.id
          currentProviderSupportsMultimodal = Boolean(selectedProvider.supports_multimodal)
        }
      } catch (e) {
        console.error('Failed to fetch providers for default agent', e)
      }
    } else {
      try {
        const providers = await modelProviderAPI.listModelProviders()
        const selectedProvider = providers?.find(p => p.id === currentProviderId)
        currentProviderSupportsMultimodal = Boolean(selectedProvider?.supports_multimodal)
      } catch (e) {
        console.error('Failed to fetch provider capability for default agent', e)
      }
    }

    if (!currentProviderId) {
      toast.error('未找到模型提供商，请先配置。')
      step.value = 'model'
      loading.value = false
      return
    }

    const agentData = {
      id: 'default_agent',
      name: 'Zavix',
      description: '默认智能体',
      is_default: true,
      maxLoopCount: 100,
      memoryType: "user",
      agentMode: "fibre",
      availableTools: [
        'todo_write', 'todo_read', 'execute_shell_command',
        'file_read', 'file_write','search_memory','questionnaire','analyze_image',
        'file_update', 'load_skill', 'add_task', 'delete_task', 'complete_task',
        'enable_task', 'get_task_details', 'fetch_webpages', 'search_web_page', 'search_image_from_web'
      ],
      availableSkills: skills.value.map(s => s.name),
      systemPrefix: systemPrompt,
      llm_provider_id: currentProviderId,
      enableMultimodal: currentProviderSupportsMultimodal
    }
    
    await agentAPI.createAgent(agentData)
    redirectToFreshChat()
  } catch (error) {
    console.error('Failed to create agent:', error)
    toast.error('创建默认 Agent 失败: ' + error.message)
    step.value = 'welcome' 
  } finally {
    loading.value = false
  }
}

const handleModelSubmit = async () => {
  if (!actualProviderName.value || !modelForm.base_url || !modelForm.api_keys_str || !actualModelName.value) {
    toast.error('请填写所有必填字段')
    return
  }

  // 先验证连接
  loading.value = true
  try {
    const verifyData = await verifyProviderCapabilities()
    verified.value = true
    
    // 验证成功后保存
    const res = await modelProviderAPI.createModelProvider(verifyData)
    await createDefaultAgent(res?.id)
  } catch (error) {
    console.error('Failed to save model provider:', error)
    toast.error(error.message || '连接模型验证失败，请检查配置')
    loading.value = false
  }
}

// Lifecycle
onMounted(() => {
  
  // Fetch system info after a short delay for animation
  setTimeout(() => {
    fetchSystemInfo()
  }, 1500)
})
</script>

<style scoped>
/* Custom animations */
@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
}

@keyframes glow {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

@keyframes slideUpFade {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.animate-float {
  animation: float 3s ease-in-out infinite;
}

.animate-glow {
  animation: glow 2s ease-in-out infinite;
}

.config-fields-appear {
  animation: slideUpFade 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  will-change: transform, opacity;
}
</style>
