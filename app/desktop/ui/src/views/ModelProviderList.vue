<template>
  <div class="h-full overflow-y-auto bg-background">
    <div class="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-6">
      <div class="flex items-center justify-between gap-4 border-b border-border/55 pb-3">
        <div class="min-w-0">
          <h1 class="text-[15px] font-semibold tracking-tight text-foreground">{{ t('modelProvider.title') }}</h1>
          <p class="text-[11px] text-muted-foreground">
            {{ providers.length }} {{ t('modelProvider.count') }} · {{ t('modelProvider.description') }}
          </p>
        </div>

        <Button class="h-9 rounded-xl px-3.5" @click="handleCreate">
          <Plus class="mr-2 h-4 w-4" />
          {{ t('modelProvider.createTitle') }}
        </Button>
      </div>

      <div v-if="providers && providers.length > 0" class="overflow-hidden rounded-[22px] border border-border/60 bg-background/40">
        <div
          v-for="(provider, index) in providers"
          :key="provider.id"
          :class="[
            'group grid grid-cols-[minmax(0,1.25fr),minmax(0,1fr),auto] items-center gap-4 px-5 py-4 transition-colors hover:bg-muted/20',
            { 'border-t border-border/60': index > 0 }
          ]"
        >
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <h3 class="truncate text-[14px] font-semibold tracking-tight text-foreground">{{ provider.name }}</h3>
              <Badge v-if="provider.is_default" variant="secondary" class="h-5 rounded-full px-2 text-[10px]">
                {{ t('common.default') }}
              </Badge>
              <Badge v-if="provider.supports_multimodal" variant="outline" class="h-5 rounded-full px-2 text-[10px]">
                {{ t('modelProvider.multimodalLabel') }}
              </Badge>
            </div>
            <div class="mt-1 flex items-center gap-2 overflow-hidden text-[11px] text-muted-foreground">
              <span class="truncate">{{ provider.base_url }}</span>
            </div>
          </div>

          <div class="min-w-0">
            <div class="flex items-center gap-2 overflow-hidden">
              <Badge variant="outline" class="h-6 max-w-full rounded-full px-2.5 text-[10px] font-medium">
                <span class="truncate">{{ provider.model }}</span>
              </Badge>
            </div>
            <div class="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
              <span>max {{ provider.max_tokens ?? 4096 }}</span>
              <span class="text-border/80">·</span>
              <span>T {{ provider.temperature ?? 0.7 }}</span>
            </div>
          </div>

          <div class="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
            <Button variant="ghost" size="icon" class="h-8 w-8 rounded-full" @click="handleEdit(provider)">
              <Edit class="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon" class="h-8 w-8 rounded-full" @click="handleDelete(provider)" :disabled="provider.is_default">
              <Trash2 class="h-4 w-4 text-destructive" />
            </Button>
          </div>
        </div>
      </div>
    
      <div v-else class="flex flex-col items-center justify-center rounded-[22px] border border-dashed border-border/60 bg-background/30 py-16 text-center">
        <div class="mb-4 rounded-2xl border border-border/60 bg-muted/30 p-3">
          <Bot class="h-7 w-7 text-muted-foreground" />
        </div>
        <h3 class="text-[15px] font-semibold tracking-tight">{{ t('modelProvider.noProviders') || 'No Providers' }}</h3>
        <p class="mt-2 max-w-sm text-[12px] leading-5 text-muted-foreground">
          {{ t('modelProvider.noProvidersDesc') || 'Get started by creating your first model provider.' }}
        </p>
        <Button class="mt-6 h-9 rounded-xl px-3.5" @click="handleCreate">
          <Plus class="mr-2 h-4 w-4" />
          {{ t('modelProvider.createTitle') }}
        </Button>
      </div>
    </div>

    <!-- Dialog -->
    <Dialog :open="dialogOpen" @update:open="dialogOpen = $event">
      <DialogContent class="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>{{ isEdit ? t('modelProvider.editTitle') : t('modelProvider.createTitle') }}</DialogTitle>
        </DialogHeader>
        <div class="grid gap-5 py-4">
          <div class="grid gap-3 rounded-2xl border border-border/60 bg-muted/[0.18] p-4">
            <div class="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">{{ t('modelProvider.providerLabel') }}</div>
            <div class="grid gap-3">
              <Label>{{ t('modelProvider.name') }} <span class="text-destructive">*</span></Label>
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
              
              <Input v-if="selectedProvider === 'Custom'" v-model="form.name" :placeholder="t('modelProvider.customNamePlaceholder')" />
            </div>
            <div class="grid gap-2">
              <Label>{{ t('modelProvider.baseUrl') }} <span class="text-destructive">*</span></Label>
              <Input v-model="form.base_url" placeholder="https://api.openai.com/v1" @update:model-value="onKeyConfigChange" />
            </div>
            <div class="grid gap-2">
              <div class="flex items-center justify-between">
                <Label>{{ t('modelProvider.apiKey') }} <span class="text-destructive">*</span></Label>
                <Button
                  v-if="currentProvider?.website"
                  variant="link"
                  size="sm"
                  class="h-auto p-0 text-primary"
                  @click="openProviderWebsite"
                >
                  Get API Key
                  <ArrowRight class="ml-1 h-3 w-3" />
                </Button>
              </div>
              <Input v-model="form.api_keys_str" :placeholder="t('modelProvider.apiKeyPlaceholder')" @update:model-value="onKeyConfigChange" />
            </div>
            <div class="grid gap-2">
              <Label>{{ t('modelProvider.model') }} <span class="text-destructive">*</span></Label>
               <Select :model-value="selectedModel" @update:model-value="handleModelChange">
                 <SelectTrigger>
                   <SelectValue :placeholder="t('modelProvider.modelPlaceholder')" />
                 </SelectTrigger>
                 <SelectContent>
                   <SelectGroup>
                     <SelectItem v-for="model in availableModels" :key="model" :value="model">
                       {{ model }}
                     </SelectItem>
                     <SelectItem value="Custom">{{ t('modelProvider.custom') }}</SelectItem>
                   </SelectGroup>
                 </SelectContent>
               </Select>
               <Input v-if="selectedModel === 'Custom'" v-model="form.model" :placeholder="t('modelProvider.modelPlaceholder')" @update:model-value="onKeyConfigChange" />
            </div>
          </div>
          
          <div class="grid gap-3 rounded-2xl border border-border/60 bg-background/60 p-4">
            <div class="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">{{ t('modelProvider.parameters') }}</div>
            <div class="grid grid-cols-2 gap-4">
              <div class="grid gap-2">
                <Label>{{ t('agent.maxTokens') }}</Label>
                <Input type="number" v-model.number="form.maxTokens" placeholder="4096" />
              </div>
              <div class="grid gap-2">
                <Label>{{ t('agent.temperature') }}</Label>
                <Input type="number" v-model.number="form.temperature" step="0.1" placeholder="0.7" />
              </div>
            </div>
            <div class="grid grid-cols-2 gap-4">
              <div class="grid gap-2">
                <Label>{{ t('agent.topP') }}</Label>
                <Input type="number" v-model.number="form.topP" step="0.1" placeholder="0.9" />
              </div>
              <div class="grid gap-2">
                <Label>{{ t('agent.presencePenalty') }}</Label>
                <Input type="number" v-model.number="form.presencePenalty" step="0.1" placeholder="0.0" />
              </div>
            </div>
            <div class="grid gap-2">
                <Label>{{ t('agent.maxModelLen') }}</Label>
                <Input type="number" v-model.number="form.maxModelLen" placeholder="32000" />
            </div>
          </div>

          <!-- 多模态支持 -->
          <div class="grid gap-3 rounded-2xl border border-border/60 bg-background/60 p-4">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <Checkbox id="multimodal" v-model:checked="form.supportsMultimodal" />
                <Label for="multimodal" class="cursor-pointer">{{ t('modelProvider.multimodalLabel') }}</Label>
              </div>
              <Button
                v-if="form.supportsMultimodal"
                type="button"
                variant="outline"
                size="sm"
                @click="handleVerifyMultimodal"
                :disabled="verifyingMultimodal || !form.model"
              >
                <Loader v-if="verifyingMultimodal" class="mr-2 h-4 w-4 animate-spin" />
                {{ multimodalVerified ? t('modelProvider.multimodalVerified') : t('modelProvider.multimodalVerify') }}
              </Button>
            </div>
            <p v-if="form.supportsMultimodal && !multimodalVerified" class="text-xs text-amber-600">
              {{ t('modelProvider.multimodalVerifyHint') }}
            </p>
   
          </div>
        </div>
        <DialogFooter class="flex sm:justify-between items-center w-full">
          <Button type="button" variant="secondary" @click="handleVerify" :disabled="verifying">
            <Loader v-if="verifying" class="mr-2 h-4 w-4 animate-spin" />
            {{ t('common.verify') }}
          </Button>
          <div class="flex gap-2">
            <Button variant="outline" @click="dialogOpen = false">{{ t('common.cancel') }}</Button>
            <Button @click="submitForm" :disabled="!canSave">{{ t('common.save') }}</Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    <AppConfirmDialog ref="confirmDialogRef" />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { Plus, Edit, Trash2, Bot, ArrowRight, Loader } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { open } from '@tauri-apps/plugin-shell'
import AppConfirmDialog from '@/components/AppConfirmDialog.vue'
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
  DialogFooter,
} from '@/components/ui/dialog'
import { useLanguage } from '@/utils/i18n'
import { modelProviderAPI } from '@/api/modelProvider'
import { MODEL_PROVIDERS } from '@/utils/modelProviders'
import { toast } from 'vue-sonner'

const { listModelProviders, createModelProvider, updateModelProvider, deleteModelProvider } = modelProviderAPI

const { t } = useLanguage()
const providers = ref([])
const dialogOpen = ref(false)
const isEdit = ref(false)
const currentId = ref(null)
const verifying = ref(false)
const verified = ref(false)
const verifyingMultimodal = ref(false)
const multimodalVerified = ref(false)
const confirmDialogRef = ref(null)

// Basic form state
const form = reactive({
  name: '',
  base_url: '',
  api_keys_str: '',
  model: '',
  maxTokens: 8192,
  temperature: 0.7,
  topP: 0.95,
  presencePenalty: 0,
  maxModelLen: 64000,
  supportsMultimodal: false
})

// 存储原始值用于比较（编辑模式）
const originalValues = reactive({
  base_url: '',
  api_keys_str: '',
  model: '',
  supportsMultimodal: false
})

const selectedProvider = ref('')
const currentProvider = computed(() => MODEL_PROVIDERS.find(p => p.name === selectedProvider.value))
const selectedModel = ref('')

const availableModels = computed(() => {
  if (currentProvider.value && currentProvider.value.models) {
    return currentProvider.value.models
  }
  return []
})

// 保存按钮是否可点击
const canSave = computed(() => {
  if (!isEdit.value) {
    // 新建模式：根据多模态开关决定需要哪种验证
    if (form.supportsMultimodal) {
      return multimodalVerified.value
    } else {
      return verified.value
    }
  }

  // 编辑模式
  // 检查关键配置是否发生变化
  const configChanged =
    form.base_url !== originalValues.base_url ||
    form.api_keys_str !== originalValues.api_keys_str ||
    form.model !== originalValues.model

  // 检查多模态是否从关闭变为开启
  const multimodalNewlyEnabled = form.supportsMultimodal && !originalValues.supportsMultimodal

  if (multimodalNewlyEnabled) {
    // 新开启多模态，必须验证多模态
    return multimodalVerified.value
  } else if (configChanged) {
    // 关键配置变化，根据当前多模态状态决定验证类型
    if (form.supportsMultimodal) {
      return multimodalVerified.value
    } else {
      return verified.value
    }
  }

  // 没有变化，可以保存
  return true
})

const handleProviderChange = (val) => {
  selectedProvider.value = val
  if (val === 'Custom') {
    form.name = ''
    form.base_url = ''
    form.model = ''
    selectedModel.value = ''
    verified.value = false
    multimodalVerified.value = false
    form.supportsMultimodal = false
    return
  }
  const provider = MODEL_PROVIDERS.find(p => p.name === val)
  if (provider) {
    form.name = provider.name
    form.base_url = provider.base_url
    if (provider.models && provider.models.length > 0) {
      selectedModel.value = provider.models[0]
      form.model = provider.models[0]
    } else {
      selectedModel.value = ''
      form.model = ''
    }
  }
  verified.value = false
  multimodalVerified.value = false
  form.supportsMultimodal = false
}

const handleModelChange = (val) => {
  selectedModel.value = val
  if (val !== 'Custom') {
    form.model = val
  } else {
    form.model = ''
  }
  onKeyConfigChange()
}

const onKeyConfigChange = () => {
  // 当关键配置变化时，重置验证状态
  verified.value = false
  multimodalVerified.value = false
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

const fetchProviders = async () => {
  try {
    const res = await listModelProviders()
    providers.value = res || []
  } catch (error) {
    console.error('Failed to fetch providers:', error)
    providers.value = []
  }
}

const handleCreate = () => {
  isEdit.value = false
  currentId.value = null
  form.name = ''
  selectedProvider.value = ''
  selectedModel.value = ''
  form.base_url = ''
  form.api_keys_str = ''
  form.model = ''
  form.maxTokens = 8192
  form.temperature = 0.7
  form.topP = 0.95
  form.presencePenalty = 0
  form.maxModelLen = 64000
  form.supportsMultimodal = false
  verified.value = false
  multimodalVerified.value = false
  // 清空原始值
  originalValues.base_url = ''
  originalValues.api_keys_str = ''
  originalValues.model = ''
  originalValues.supportsMultimodal = false
  dialogOpen.value = true
}

const handleEdit = (provider) => {
  try {
    isEdit.value = true
    currentId.value = provider.id
    form.name = provider.name

    // Try to match provider
    const known = MODEL_PROVIDERS.find(p => p.base_url === provider.base_url)
    selectedProvider.value = known ? known.name : 'Custom'

    form.base_url = provider.base_url

    // Handle API keys safely
    let keys = provider.api_keys
    if (!Array.isArray(keys)) {
        keys = (typeof keys === 'string' && keys) ? [keys] : []
    }
    form.api_keys_str = keys.join(',')

    form.model = provider.model
    
    // Initialize selectedModel
    if (known && known.models && known.models.includes(provider.model)) {
      selectedModel.value = provider.model
    } else {
      selectedModel.value = 'Custom'
    }

    form.maxTokens = provider.max_tokens ?? 4096
    form.temperature = provider.temperature ?? 0.7
    form.topP = provider.top_p ?? 0.9
    form.presencePenalty = provider.presence_penalty ?? 0.0
    form.maxModelLen = provider.max_model_len ?? 32000
    form.supportsMultimodal = provider.supports_multimodal ?? false

    // 保存原始值用于比较
    originalValues.base_url = provider.base_url
    originalValues.api_keys_str = keys.join(',')
    originalValues.model = provider.model
    originalValues.supportsMultimodal = provider.supports_multimodal ?? false

    // 编辑模式初始状态设为已验证（如果没有变化）
    verified.value = true
    multimodalVerified.value = form.supportsMultimodal

    dialogOpen.value = true
  } catch (error) {
    console.error('Failed to open edit dialog:', error)
    toast.error('Unable to open edit dialog')
  }
}

const handleDelete = async (provider) => {
  const confirmed = await confirmDialogRef.value.confirm(t('common.confirmDelete'))
  if (!confirmed) return
  try {
    await deleteModelProvider(provider.id)
    toast.success(t('common.deleteSuccess'))
    fetchProviders()
  } catch (error) {
    toast.error(error.message)
  }
}

const handleVerify = async () => {
  const data = {
    name: form.name,
    base_url: form.base_url,
    api_keys: form.api_keys_str.trim().split(/[\n,]+/).map(k => k.trim()).filter(k => k),
    model: form.model,
    max_tokens: form.maxTokens,
    temperature: form.temperature,
    top_p: form.topP,
    presence_penalty: form.presencePenalty,
    max_model_len: form.maxModelLen
  }

  if (!data.name || !data.base_url || !data.api_keys.length || !data.model) {
     toast.error(t('common.fillRequired'))
     return
  }

  verifying.value = true
  try {
    await modelProviderAPI.verifyModelProvider(data)
    verified.value = true
    toast.success(t('common.verifySuccess'))
  } catch (error) {
    verified.value = false
    toast.error(error.message || t('modelProvider.verifyFailed'))
  } finally {
    verifying.value = false
  }
}

const handleVerifyMultimodal = async () => {
  if (!form.model) {
    toast.error(t('modelProvider.fillModelNameFirst'))
    return
  }

  verifyingMultimodal.value = true
  try {
    const data = {
      name: form.name,
      base_url: form.base_url,
      api_keys: form.api_keys_str.trim().split(/[\n,]+/).map(k => k.trim()).filter(k => k),
      model: form.model,
      max_tokens: form.maxTokens,
      temperature: form.temperature,
      top_p: form.topP,
      presence_penalty: form.presencePenalty,
      max_model_len: form.maxModelLen
    }
    const res = await modelProviderAPI.verifyMultimodal(data)
    if (res?.supports_multimodal) {
      multimodalVerified.value = true
      if (res?.recognized) {
        toast.success(t('modelProvider.multimodalRecognized'))
      } else {
        toast.success(t('modelProvider.multimodalNotRecognized'))
      }
    } else {
      multimodalVerified.value = false
      toast.warning(t('modelProvider.multimodalNotSupported'))
      form.supportsMultimodal = false
    }
  } catch (error) {
    console.error('Failed to verify multimodal:', error)
    multimodalVerified.value = false
    toast.error(error.message || t('modelProvider.multimodalVerifyFailed'))
  } finally {
    verifyingMultimodal.value = false
  }
}

const submitForm = async () => {
  const data = {
    name: form.name,
    base_url: form.base_url,
    api_keys: form.api_keys_str.trim().split(/[\n,]+/).map(k => k.trim()).filter(k => k),
    model: form.model,
    max_tokens: form.maxTokens,
    temperature: form.temperature,
    top_p: form.topP,
    presence_penalty: form.presencePenalty,
    max_model_len: form.maxModelLen,
    supports_multimodal: form.supportsMultimodal
  }

  // 如果开启多模态，必须验证多模态；否则必须验证连接（新建时）
  if (!isEdit.value) {
    if (form.supportsMultimodal) {
      if (!multimodalVerified.value) {
        toast.error(t('modelProvider.verifyMultimodalFirst'))
        return
      }
    } else {
      if (!verified.value) {
        toast.error(t('modelProvider.verifyConnectionFirst'))
        return
      }
    }
  }

  try {
    if (isEdit.value) {
      await updateModelProvider(currentId.value, data)
    } else {
      await createModelProvider(data)
    }

    toast.success(t('common.success'))
    dialogOpen.value = false
    fetchProviders()
  } catch (error) {
    toast.error(error.message)
  }
}

onMounted(() => {
  fetchProviders()
})
</script>
