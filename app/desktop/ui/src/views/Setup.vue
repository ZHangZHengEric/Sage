<template>
  <div class="h-screen w-full bg-background text-foreground flex flex-col overflow-hidden animate-in fade-in duration-300">
    
    <!-- Welcome Step: Centered Full Screen -->
    <div v-if="step === 'welcome'" class="flex-1 flex flex-col items-center justify-center p-8 overflow-y-auto">
      <div class="max-w-4xl w-full flex flex-col items-center text-center space-y-12 py-8">
        
        <div class="space-y-6">
          <div class="p-8 bg-primary/5 rounded-full inline-block mb-4">
            <Bot class="w-24 h-24 text-primary" />
          </div>
          <h1 class="text-4xl md:text-5xl font-bold tracking-tight">Welcome to Sage</h1>
          <p class="text-xl text-muted-foreground max-w-2xl mx-auto leading-relaxed">
            Your intelligent AI workspace is almost ready. Let's set up your environment to get started.
          </p>
        </div>
        
        <div class="grid md:grid-cols-2 gap-8 w-full text-left">
          <div class="p-8 rounded-2xl bg-muted/30 border border-transparent hover:border-primary/20 hover:bg-muted/50 transition-all duration-300">
            <div class="flex items-center gap-4 mb-4">
              <div class="p-3 bg-blue-100 dark:bg-blue-900/30 rounded-xl">
                <Brain class="w-6 h-6 text-blue-600 dark:text-blue-400" />
              </div>
              <h3 class="text-xl font-semibold">Model Provider</h3>
            </div>
            <p class="text-muted-foreground leading-relaxed">
              The "Brain" of the AI. Connect to services like OpenAI, DeepSeek, or others to power your agents.
            </p>
          </div>
          
          <div class="p-8 rounded-2xl bg-muted/30 border border-transparent hover:border-primary/20 hover:bg-muted/50 transition-all duration-300">
            <div class="flex items-center gap-4 mb-4">
              <div class="p-3 bg-green-100 dark:bg-green-900/30 rounded-xl">
                <MessageSquare class="w-6 h-6 text-green-600 dark:text-green-400" />
              </div>
              <h3 class="text-xl font-semibold">Agent</h3>
            </div>
            <p class="text-muted-foreground leading-relaxed">
              The "Persona" you interact with. Define how it behaves, what tools it uses, and its personality.
            </p>
          </div>
        </div>

        <Button size="lg" @click="handleWelcomeNext" class="px-12 py-6 text-lg rounded-full shadow-lg hover:shadow-xl transition-all">
          Get Started
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
              <Label class="text-base">{{ t('modelProvider.name') }}</Label>
              <Input v-model="modelForm.name" placeholder="My LLM Provider" class="h-11" />
            </div>
            
            <div class="grid gap-2">
              <Label class="text-base">{{ t('modelProvider.baseUrl') }}</Label>
              <Input v-model="modelForm.base_url" placeholder="https://api.openai.com/v1" class="h-11" />
              <div class="flex gap-3 text-sm flex-wrap pt-1">
                  <span class="cursor-pointer text-primary hover:underline" @click="modelForm.base_url='https://api.openai.com/v1'">OpenAI</span>
                  <span class="cursor-pointer text-primary hover:underline" @click="modelForm.base_url='https://api.deepseek.com'">DeepSeek</span>
                  <span class="cursor-pointer text-primary hover:underline" @click="modelForm.base_url='https://dashscope.aliyuncs.com/compatible-mode/v1'">Aliyun</span>
                  <span class="cursor-pointer text-primary hover:underline" @click="modelForm.base_url='https://ark.cn-beijing.volces.com/api/v3'">ByteDance</span>
              </div>
            </div>
            
            <div class="grid gap-2">
              <Label class="text-base">{{ t('modelProvider.apiKey') }}</Label>
              <Textarea v-model="modelForm.api_keys_str" :placeholder="t('modelProvider.apiKeyPlaceholder')" class="min-h-[100px] resize-none" />
            </div>
            
            <div class="grid gap-2">
               <Label class="text-base">{{ t('modelProvider.model') }}</Label>
               <Input v-model="modelForm.model" :placeholder="t('modelProvider.modelPlaceholder')" class="h-11" />
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

          <div class="flex justify-end pt-4">
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

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import AgentEdit from '@/components/AgentEdit.vue'

const router = useRouter()
const { t } = useLanguage()

const step = ref('loading') // loading, welcome, model, agent
const loading = ref(false)
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
  api_keys_str: '',
  model: '',
  maxTokens: 4096,
  temperature: 0.7,
  topP: 0.95,
  presencePenalty: 0,
  maxModelLen: 32000
})

const currentStepTitle = computed(() => {
  if (step.value === 'model') return 'Connect Model Provider'
  if (step.value === 'agent') return 'Create First Agent'
  return 'Loading...'
})

const currentStepDescription = computed(() => {
  if (step.value === 'model') return 'First, we need to connect to an LLM provider (the "Brain") to power your agents.'
  if (step.value === 'agent') return 'Now, create your first Agent (the "Persona") to start chatting.'
  return 'Checking system status...'
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

const handleModelSubmit = async () => {
  if (!modelForm.name || !modelForm.base_url || !modelForm.api_keys_str || !modelForm.model) {
    toast.error('Please fill in all required fields')
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
    toast.error(error.message || 'Failed to save model provider')
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

    toast.success('Setup completed successfully!')
    router.replace('/')
  } catch (error) {
    console.error('Failed to save setup:', error)
    toast.error('Failed to complete setup') 
  } finally {
    loading.value = false
    if (doneCallback) doneCallback()
  }
}

onMounted(() => {
  fetchSystemInfo()
})
</script>
