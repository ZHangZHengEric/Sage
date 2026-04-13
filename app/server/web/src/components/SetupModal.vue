<template>
  <Dialog :open="visible" @update:open="handleDialogOpenChange">
    <DialogContent
      class="sm:max-w-[500px] overflow-hidden"
      :show-close="false"
      @escape-key-down="preventDialogClose"
      @pointer-down-outside="preventDialogClose"
      @interact-outside="preventDialogClose"
    >
      <DialogHeader>
        <DialogTitle>完善配置信息</DialogTitle>
        <DialogDescription>
          配置模型提供商以激活 AI 能力。配置完成后，系统将自动为您创建一个默认智能体 (Zavix)，助您快速上手。
        </DialogDescription>
      </DialogHeader>
      
      <div class="grid gap-4 py-4">
        <div class="grid gap-2">
          <Label>{{ t('modelProvider.name') }}</Label>
          <div class="space-y-3">
            <Select :model-value="selectedProvider" @update:model-value="handleProviderChange">
              <SelectTrigger>
                <SelectValue :placeholder="t('modelProvider.selectProviderPlaceholder')" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem v-for="provider in MODEL_PROVIDERS" :key="provider.name" :value="provider.name">
                    {{ provider.name }}
                  </SelectItem>
                  <SelectItem value="Custom">{{ t('modelProvider.custom') }}</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            
            <Input v-if="selectedProvider === 'Custom'" v-model="form.name" :placeholder="t('modelProvider.customNamePlaceholder')" @update:model-value="handleConfigChange" />
          </div>
        </div>
        
        <div class="grid gap-2">
          <Label>{{ t('modelProvider.baseUrl') }}</Label>
          <Input v-model="form.base_url" placeholder="https://api.openai.com/v1" @update:model-value="handleConfigChange" />
        </div>
        
        <div class="grid gap-2">
          <div class="flex items-center justify-between">
            <Label>{{ t('modelProvider.apiKey') }}</Label>
            <Button 
              v-if="currentProvider?.website" 
              variant="link" 
              size="sm" 
              class="h-auto p-0 text-primary" 
              @click="openProviderWebsite"
            >
              Get API Key
              <ArrowRight class="ml-1 w-3 h-3" />
            </Button>
          </div>
          <Input
            v-model="form.api_keys_str"
            :placeholder="t('modelProvider.apiKeyPlaceholder')"
            @update:model-value="handleApiKeyInput"
          />
        </div>
        
        <div class="grid gap-2">
           <div class="flex items-center justify-between">
             <Label>{{ t('modelProvider.model') }}</Label>
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
                   v-model="form.model" 
                   :placeholder="t('modelProvider.modelPlaceholder')" 
                   class="pr-10"
                   @update:model-value="handleConfigChange"
                />
                <div class="absolute right-0 top-0 h-full">
                   <Select :model-value="''" @update:model-value="(val) => { form.model = val; handleConfigChange() }">
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
           <Input v-else v-model="form.model" :placeholder="t('modelProvider.modelPlaceholder')" />
        </div>
      </div>
      
      <DialogFooter class="flex sm:justify-end items-center w-full">
        <div class="flex gap-2">
          <Button type="button" variant="secondary" @click="handleVerify" :disabled="verifying">
            <Loader v-if="verifying" class="mr-2 h-4 w-4 animate-spin" />
            {{ t('common.verify') || '验证' }}
          </Button>
          <Button @click="handleSubmit" :disabled="submitting">
            <Loader v-if="submitting" class="mr-2 h-4 w-4 animate-spin" />
            {{ t('common.save') }}
          </Button>
        </div>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { useLanguage } from '@/utils/i18n'
import { MODEL_PROVIDERS } from '@/utils/modelProviders'
import { modelProviderAPI } from '@/api/modelProvider'
import { userAPI } from '@/api/user'
import { agentAPI } from '@/api/agent'
import { skillAPI } from '@/api/skill'
import { toast } from 'vue-sonner'
import { Loader, ArrowRight } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close'])
const { t } = useLanguage()

const verifying = ref(false)
const submitting = ref(false)
const selectedProvider = ref('')

const form = reactive({
  name: '',
  base_url: '',
  api_keys_str: '',
  model: '',
  maxTokens: null,
  temperature: 0.7,
  topP: 0.95,
  presencePenalty: 0,
  maxModelLen: 64000,
  supportsMultimodal: false,
  supportsStructuredOutput: false
})

const currentProvider = computed(() => MODEL_PROVIDERS.find(p => p.name === selectedProvider.value))

const buildApiKeys = () => {
  const apiKey = form.api_keys_str.trim()
  return apiKey ? [apiKey] : []
}

const buildProviderPayload = () => ({
  name: form.name,
  base_url: form.base_url,
  api_keys: buildApiKeys(),
  model: form.model,
  ...(() => {
    const maxTokensValue = Number(form.maxTokens)
    return Number.isFinite(maxTokensValue) ? { max_tokens: maxTokensValue } : {}
  })(),
  temperature: form.temperature,
  top_p: form.topP,
  presence_penalty: form.presencePenalty,
  max_model_len: form.maxModelLen,
  supports_multimodal: form.supportsMultimodal,
  supports_structured_output: form.supportsStructuredOutput
})

const handleProviderChange = (val) => {
  selectedProvider.value = val
  if (val === 'Custom') {
    form.name = ''
    form.base_url = ''
    form.model = ''
    handleConfigChange()
    return
  }
  const provider = MODEL_PROVIDERS.find(p => p.name === val)
  if (provider) {
    form.name = provider.name
    form.base_url = provider.base_url
    // form.model = provider.models[0] || ''
  }
  handleConfigChange()
}

const openProviderWebsite = () => {
  if (currentProvider.value?.website) {
    window.open(currentProvider.value.website, '_blank')
  }
}

const handleApiKeyInput = (value) => {
  form.api_keys_str = `${value ?? ''}`.split(/\r?\n/, 1)[0]
  handleConfigChange()
}

const handleConfigChange = () => {
  form.supportsMultimodal = false
  form.supportsStructuredOutput = false
}

const openProviderModelList = () => {
  if (currentProvider.value?.model_list_url) {
    window.open(currentProvider.value.model_list_url, '_blank')
  }
}

const preventDialogClose = (event) => {
  event.preventDefault()
}

const handleDialogOpenChange = (open) => {
  if (!open) {
    return
  }
}

const syncCurrentUserStatus = async () => {
  try {
    const session = await userAPI.checkLogin()
    if (!session?.user) {
      return
    }

    const userInfo = {
      ...session.user,
      has_provider: session.has_provider,
      has_agent: session.has_agent
    }
    localStorage.setItem('userInfo', JSON.stringify(userInfo))
    localStorage.setItem('isLoggedIn', 'true')
    localStorage.setItem('loginTime', Date.now().toString())
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('user-updated'))
    }
  } catch (error) {
    console.error('Failed to sync user status after provider setup:', error)
    try {
      const currentUser = JSON.parse(localStorage.getItem('userInfo') || '{}')
      const nextUser = { ...currentUser, has_provider: true }
      localStorage.setItem('userInfo', JSON.stringify(nextUser))
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('user-updated'))
      }
    } catch (storageError) {
      console.error('Failed to update local user status after provider setup:', storageError)
    }
  }
}

const handleVerify = async () => {
  const data = buildProviderPayload()
  
  if (!data.name || !data.base_url || !data.api_keys.length || !data.model) {
     toast.error(t('common.fillRequired') || '请填写必填项')
     return
  }
  
  verifying.value = true
  try {
    const result = await modelProviderAPI.verifyModelProvider(data)
    form.supportsMultimodal = Boolean(result?.supports_multimodal)
    form.supportsStructuredOutput = Boolean(result?.supports_structured_output)
    toast.success(t('common.verifySuccess') || '验证成功')
  } catch (error) {
    toast.error(error.message || '验证失败')
  } finally {
    verifying.value = false
  }
}

const createDefaultAgent = async (providerId) => {
  try {
    // 1. Get available skills
    let skillNames = []
    try {
        const skillsRes = await skillAPI.getSkills()
        if (skillsRes && skillsRes.skills) {
            skillNames = skillsRes.skills.map(s => s.name)
        }
    } catch (e) {
        console.error('Failed to fetch skills:', e)
    }

    // 2. Get default system prompt
    let systemPrompt = ''
    try {
        const promptRes = await agentAPI.getDefaultSystemPrompt()
        if (promptRes && promptRes.content) {
            systemPrompt = promptRes.content
        }
    } catch (e) {
        console.error('Failed to get default system prompt', e)
    }
    
    // 3. Construct agent data
    const agentData = {
      name: 'Zavix',
      description: '默认智能体',
      maxLoopCount: 100,
      memoryType: "session",
      agentMode: "fibre",
      availableTools: [
        'todo_write', 
        'todo_read', 
        'execute_shell_command', 
        'execute_python_code', 
        'execute_javascript_code', 
        'file_read', 
        'file_write', 
        'download_file_from_url', 
        'file_update',
        'load_skill',
        'add_task',
        'delete_task',
        'complete_task',
        'enable_task',
        'get_task_details',
        'fetch_webpages'
      ],
      availableSkills: skillNames,
      systemPrefix: systemPrompt,
      llm_provider_id: providerId
    }
    
    // 4. Create Agent
    await agentAPI.createAgent(agentData)
    toast.success('已自动创建默认智能体 Zavix')
    
  } catch (error) {
    console.error('Failed to create default agent:', error)
    toast.error('创建默认智能体失败: ' + error.message)
  }
}

const handleSubmit = async () => {
  const data = {
    ...buildProviderPayload(),
    is_default: true
  }
  
  if (!data.name || !data.base_url || !data.api_keys.length || !data.model) {
     toast.error(t('common.fillRequired') || '请填写必填项')
     return
  }

  submitting.value = true
  try {
    const res = await modelProviderAPI.createModelProvider(data)
    await syncCurrentUserStatus()
    emit('close')
    await createDefaultAgent(res?.id)
  } catch (error) {
    toast.error(error.message)
  } finally {
    submitting.value = false
  }
}

</script>
