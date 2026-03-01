<template>
  <div class="h-screen w-full bg-background text-foreground flex flex-col overflow-hidden animate-in fade-in duration-300">
    
    <!-- Welcome Step: Centered Full Screen -->
    <div v-if="step === 'welcome'" class="flex-1 flex flex-col items-center justify-center p-8 overflow-y-auto">
      <div class="max-w-4xl w-full flex flex-col items-center text-center space-y-12 py-8">
        
        <div class="space-y-6">
          <div class="p-8 bg-primary/5 rounded-full inline-block mb-4">
            <Bot class="w-24 h-24 text-primary" />
          </div>
          <h1 class="text-4xl md:text-5xl font-bold tracking-tight">欢迎使用 Sage</h1>
          <p class="text-xl text-muted-foreground max-w-2xl mx-auto leading-relaxed">
            您的智能 AI 工作空间已准备就绪。让我们设置您的环境以开始使用。
          </p>
        </div>
        
        <div class="grid md:grid-cols-2 gap-8 w-full text-left">
          <div class="p-8 rounded-2xl bg-muted/30 border border-transparent hover:border-primary/20 hover:bg-muted/50 transition-all duration-300">
            <div class="flex items-center gap-4 mb-4">
              <div class="p-3 bg-blue-100 dark:bg-blue-900/30 rounded-xl">
                <Brain class="w-6 h-6 text-blue-600 dark:text-blue-400" />
              </div>
              <h3 class="text-xl font-semibold">模型提供商</h3>
            </div>
            <p class="text-muted-foreground leading-relaxed">
              AI 的“大脑”。连接到 OpenAI、DeepSeek 或其他服务以为您的代理提供动力。
            </p>
          </div>
          
          <div class="p-8 rounded-2xl bg-muted/30 border border-transparent hover:border-primary/20 hover:bg-muted/50 transition-all duration-300">
            <div class="flex items-center gap-4 mb-4">
              <div class="p-3 bg-green-100 dark:bg-green-900/30 rounded-xl">
                <MessageSquare class="w-6 h-6 text-green-600 dark:text-green-400" />
              </div>
              <h3 class="text-xl font-semibold">智能体</h3>
            </div>
            <p class="text-muted-foreground leading-relaxed">
              您与之交互的“角色”。定义它的行为方式、使用的工具及其个性。
            </p>
          </div>
        </div>

        <Button size="lg" @click="handleWelcomeNext" class="px-12 py-6 text-lg rounded-full shadow-lg hover:shadow-xl transition-all">
          开始使用
          <ArrowRight class="ml-2 w-6 h-6" />
        </Button>
      </div>
    </div>

    <!-- Model Provider Step: Centered Form with Scroll -->
    <div v-else-if="step === 'model'" class="flex-1 overflow-y-auto bg-background">
      <div class="min-h-full flex flex-col items-center justify-center p-8">
        <div class="max-w-2xl w-full space-y-8 py-8">
          <div class="space-y-2 text-center">
            <h2 class="text-3xl font-bold">{{ currentStepTitle }}</h2>
            <p class="text-lg text-muted-foreground">{{ currentStepDescription }}</p>
          </div>

          <div class="space-y-6 bg-card/50 p-8 rounded-xl border shadow-sm backdrop-blur-sm">
            <div class="grid gap-2">
              <Label class="text-base">{{ t('modelProvider.providerLabel') }} <span class="text-destructive">*</span></Label>
              <Select :model-value="selectedProvider" @update:model-value="handleProviderChange">
                <SelectTrigger class="h-11">
                  <SelectValue :placeholder="t('modelProvider.selectProviderPlaceholder')" />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectLabel>{{ t('modelProvider.providerLabel') }}</SelectLabel>
                    <SelectItem v-for="provider in MODEL_PROVIDERS" :key="provider.name" :value="provider.name">
                      {{ provider.name }}
                    </SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
            
            <div class="grid gap-2">
              <Label class="text-base">{{ t('modelProvider.baseUrl') }} <span class="text-destructive">*</span></Label>
              <Input v-model="modelForm.base_url" placeholder="https://api.openai.com/v1" class="h-11" />
            </div>
            
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
              <Input v-model="modelForm.api_keys_str" :placeholder="t('modelProvider.apiKeyPlaceholder')" class="h-11" />
            </div>
            
            <div class="grid gap-2">
               <div class="flex items-center justify-between">
                 <Label class="text-base">{{ t('modelProvider.model') }} <span class="text-destructive">*</span></Label>
                 <Button 
                   v-if="currentProvider?.model_list_url" 
                   variant="link" 
                   size="sm" 
                   class="h-auto p-0 text-primary" 
                   @click="openProviderModelList"
                 >
                   查看模型列表
                   <ArrowRight class="ml-1 w-3 h-3" />
                 </Button>
               </div>
               <div v-if="currentProvider?.models?.length" class="flex gap-2">
                 <div class="flex-1 relative">
                   <Input 
                     v-model="modelForm.model" 
                     :placeholder="t('modelProvider.modelPlaceholder')" 
                     class="h-11 pr-10" 
                   />
                   <div v-if="currentProvider?.models?.length" class="absolute right-0 top-0 h-full">
                     <Select :model-value="''" @update:model-value="(val) => modelForm.model = val">
                        <SelectTrigger class="h-full w-8 px-0 border-l-0 rounded-l-none focus:ring-0">
                          <span class="sr-only">Select model</span>
                        </SelectTrigger>
                        <SelectContent align="end" class="min-w-[200px]">
                          <SelectItem v-for="m in currentProvider.models" :key="m" :value="m">
                            {{ m }}
                          </SelectItem>
                        </SelectContent>
                     </Select>
                   </div>
                 </div>
               </div>
               <Input v-else v-model="modelForm.model" :placeholder="t('modelProvider.modelPlaceholder')" class="h-11" />
               <p class="text-sm text-muted-foreground">{{ t('modelProvider.modelHint') }}</p>
            </div>
            
            <div class="grid grid-cols-2 gap-6">
              <div class="grid gap-2">
                <Label>{{ t('agent.maxTokens') }}</Label>
                <Input type="number" v-model.number="modelForm.maxTokens" placeholder="4096" class="h-11" />
              </div>
              <div class="grid gap-2">
                <Label>{{ t('agent.temperature') }}</Label>
                <Input type="number" v-model.number="modelForm.temperature" step="0.1" placeholder="0.7" class="h-11" />
              </div>
            </div>
          </div>

          <div class="flex justify-between pt-4">
            <Button variant="outline" size="lg" @click="handleVerify" :disabled="verifying || loading" class="h-12 px-6">
               <Loader v-if="verifying" class="mr-2 h-5 w-5 animate-spin" />
               验证连接
            </Button>
            <Button size="lg" @click="handleModelSubmit" :disabled="loading" class="px-8 h-12 text-base">
              <Loader v-if="loading" class="mr-2 h-5 w-5 animate-spin" />
              {{ t('common.nextStep') }}
            </Button>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Agent Step: Full Screen Editor -->
    <div v-else-if="step === 'agent'" class="flex-1 flex flex-col overflow-hidden">
      <div class="border-b px-8 py-4 flex items-center justify-between bg-background/80 backdrop-blur-sm z-10">
        <div>
          <h2 class="text-2xl font-bold">{{ currentStepTitle }}</h2>
          <p class="text-muted-foreground">{{ currentStepDescription }}</p>
        </div>
        <!-- Optional: Add a skip or help button here if needed -->
      </div>
      
      <div class="flex-1 overflow-hidden relative">
        <AgentEdit 
          :visible="true" 
          :is-setup="true" 
          :tools="tools"
          :skills="skills"
          @save="handleAgentSaved" 
          class="h-full w-full"
        />
      </div>
    </div>

    <!-- Loading State -->
    <div v-else class="flex-1 flex items-center justify-center">
      <Loader class="w-12 h-12 animate-spin text-primary" />
    </div>

  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useLanguage } from '@/utils/i18n'
import { systemAPI } from '@/api/system'
import { modelProviderAPI } from '@/api/modelProvider'
import { agentAPI } from '@/api/agent'
import { toolAPI } from '@/api/tool'
import { skillAPI } from '@/api/skill'
import { toast } from 'vue-sonner'
import { Loader, Bot, Brain, MessageSquare, ArrowRight } from 'lucide-vue-next'
import { open } from '@tauri-apps/api/shell'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
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
import AgentEdit from '@/components/AgentEdit.vue'

const router = useRouter()
const { t } = useLanguage()

const step = ref('loading') // loading, welcome, model, agent
const loading = ref(false)
const verifying = ref(false)
const tools = ref([])
const skills = ref([])
const systemStatus = ref({
  has_model_provider: false,
  has_agent: false
})

// Model Form State
const modelForm = reactive({
  name: 'Default Provider',
  base_url: '',
  api_keys_str: 'sk-xxxxxxxx',
  model: '',
  maxTokens: 4096,
  temperature: 0.7,
  topP: 0.95,
  presencePenalty: 0,
  maxModelLen: 32000
})

const selectedProvider = ref('')
const currentProvider = computed(() => MODEL_PROVIDERS.find(p => p.name === selectedProvider.value))

const isCustomModel = ref(false)

const handleProviderChange = (val) => {
  selectedProvider.value = val
  const provider = MODEL_PROVIDERS.find(p => p.name === val)
  if (provider) {
    // modelForm.name = provider.name // Don't override name for setup
    modelForm.base_url = provider.base_url
    // modelForm.model = provider.models[0] || '' // Don't auto-select first model
    isCustomModel.value = false
  }
}

const openProviderWebsite = async () => {
  if (currentProvider.value?.website) {
    try {
      await open(currentProvider.value.website)
    } catch (error) {
      console.error('Failed to open external link:', error)
      // Fallback to window.open if Tauri open fails (e.g. in browser mode)
      window.open(currentProvider.value.website, '_blank')
    }
  }
}

const openProviderModelList = async () => {
  if (currentProvider.value?.model_list_url) {
    try {
      await open(currentProvider.value.model_list_url)
    } catch (error) {
      console.error('Failed to open external link:', error)
      window.open(currentProvider.value.model_list_url, '_blank')
    }
  }
}

const currentStepTitle = computed(() => {
  if (step.value === 'model') return '连接模型提供商'
  if (step.value === 'agent') return '创建第一个智能体'
  return '加载中...'
})

const currentStepDescription = computed(() => {
  if (step.value === 'model') return '首先，我们需要连接到一个 LLM 提供商（“大脑”）来为您的智能体提供动力。'
  if (step.value === 'agent') return '现在，创建您的第一个智能体（“角色”）以开始聊天。'
  return '正在检查系统状态...'
})

const fetchSystemInfo = async () => {
  try {
    const res = await systemAPI.getSystemInfo()
    systemStatus.value = res
    
    if (!res.has_model_provider || !res.has_agent) {
      if (res.has_model_provider && !res.has_agent) {
          // Skip welcome if model provider is already configured
          step.value = 'agent'
          fetchResources()
      } else {
          step.value = 'welcome'
      }
    } else {
      router.replace('/')
    }
  } catch (error) {
    console.error('Failed to fetch system info:', error)
    toast.error('Failed to initialize system info')
  }
}

const handleWelcomeNext = () => {
  if (!systemStatus.value.has_model_provider) {
    step.value = 'model'
  } else if (!systemStatus.value.has_agent) {
    step.value = 'agent'
  } else {
    router.replace('/')
  }
}

const fetchResources = async () => {
  try {
    const [toolsRes, skillsRes] = await Promise.all([
      toolAPI.getTools(),
      skillAPI.getSkills()
    ])
    if (toolsRes && toolsRes.tools) {
        tools.value = toolsRes.tools
    } else {
        tools.value = []
    }
    
    if (skillsRes && skillsRes.skills) {
        skills.value = skillsRes.skills
    } else {
        skills.value = []
    }
  } catch (error) {
    console.error('Failed to fetch resources:', error)
  }
}

const handleVerify = async () => {
  if (!modelForm.name || !modelForm.base_url || !modelForm.api_keys_str || !modelForm.model) {
    toast.error('请填写所有必填字段')
    return
  }

  verifying.value = true
  try {
    const data = {
      name: modelForm.name,
      base_url: modelForm.base_url,
      api_keys: modelForm.api_keys_str.split(/[\n,]+/).map(k => k.trim()).filter(k => k),
      model: modelForm.model,
      max_tokens: modelForm.maxTokens,
      temperature: modelForm.temperature,
      top_p: modelForm.topP,
      presence_penalty: modelForm.presencePenalty,
      max_model_len: modelForm.maxModelLen,
      is_default: true
    }
    await modelProviderAPI.verifyModelProvider(data)
    toast.success('连接验证成功')
  } catch (error) {
    console.error('Failed to verify model provider:', error)
    toast.error(error.message || '连接验证失败')
  } finally {
    verifying.value = false
  }
}

const handleModelSubmit = async () => {
  if (!modelForm.name || !modelForm.base_url || !modelForm.api_keys_str || !modelForm.model) {
    toast.error('请填写所有必填字段')
    return
  }
  
  loading.value = true
  try {
    const data = {
      name: modelForm.name,
      base_url: modelForm.base_url,
      api_keys: modelForm.api_keys_str.split(/[\n,]+/).map(k => k.trim()).filter(k => k),
      model: modelForm.model,
      max_tokens: modelForm.maxTokens,
      temperature: modelForm.temperature,
      top_p: modelForm.topP,
      presence_penalty: modelForm.presencePenalty,
      max_model_len: modelForm.maxModelLen,
      is_default: true
    }

    await modelProviderAPI.createModelProvider(data)
    
    step.value = 'agent'
    // Fetch resources now so they are available for Agent step
    await fetchResources()
  } catch (error) {
    console.error('Failed to save model provider:', error)
    toast.error(error.message || '保存模型提供商失败')
  } finally {
    loading.value = false
  }
}

const handleAgentSaved = async (agentData, shouldExit = true, doneCallback = null) => {
  // Only save to backend if it is the final step
  if (!shouldExit) {
     if (doneCallback) doneCallback()
     return
  }

  loading.value = true
  try {
    // 2. Then save the Agent
    let result
    if (agentData.id) {
       result = await agentAPI.updateAgent(agentData.id, agentData)
    } else {
       // Ensure llm_provider_id is not set (will use default) or set it if we have it
       // Since we just created the default provider, the backend will pick it up automatically if not provided.
       // Or we can query it back. For now, let's rely on backend default logic.
       result = await agentAPI.createAgent(agentData)
    }

    toast.success('设置完成！')
    router.replace('/')
  } catch (error) {
    console.error('Failed to save setup:', error)
    toast.error('设置失败') 
  } finally {
    loading.value = false
    if (doneCallback) doneCallback()
  }
}

onMounted(() => {
  fetchSystemInfo()
})
</script>
