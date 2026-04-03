<template>
  <div class="h-full flex flex-col p-6 space-y-6">
    <div class="flex items-center justify-between">
      <div class="space-y-1">
        <h2 class="text-lg font-medium">{{ t('modelProvider.title') }}</h2>
        <p class="text-sm text-muted-foreground">{{ t('modelProvider.description') }}</p>
      </div>
      <Button @click="handleCreate">
        <Plus class="mr-2 h-4 w-4" />
        {{ t('common.create') }}
      </Button>
    </div>

    <div v-if="providers && providers.length > 0" class="border rounded-xl bg-card shadow-sm overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{{ t('modelProvider.name') }}</TableHead>
            <TableHead>{{ t('modelProvider.baseUrl') }}</TableHead>
            <TableHead>{{ t('modelProvider.model') }}</TableHead>
            <TableHead class="w-[100px]">{{ t('common.actions') }}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="provider in providers" :key="provider.id">
            <TableCell class="font-medium">
               <div class="flex items-center gap-3">
                 <div class="h-9 w-9 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                   <Bot class="h-4 w-4" />
                 </div>
                 <div class="min-w-0">
                   <div class="flex items-center gap-2">
                     <span class="truncate">{{ provider.name }}</span>
                 <Badge v-if="provider.is_default" variant="secondary">{{ t('common.default') }}</Badge>
                   </div>
                   <p class="text-xs text-muted-foreground truncate">{{ provider.model }}</p>
                 </div>
               </div>
            </TableCell>
            <TableCell class="text-muted-foreground max-w-[260px] truncate" :title="provider.base_url">{{ provider.base_url }}</TableCell>
            <TableCell>
              <Badge variant="outline">{{ provider.model }}</Badge>
            </TableCell>
            <TableCell>
              <div class="flex items-center gap-2">
                <Button variant="ghost" size="icon" @click="handleEdit(provider)">
                  <Edit class="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" @click="handleDelete(provider)" :disabled="provider.is_default">
                  <Trash2 class="h-4 w-4 text-destructive" />
                </Button>
              </div>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>
    
    <div v-else class="flex flex-col items-center justify-center py-12 text-center border rounded-xl border-dashed bg-card">
      <div class="p-4 rounded-full bg-muted/50 mb-4">
        <Bot class="w-8 h-8 text-muted-foreground" />
      </div>
      <h3 class="text-lg font-semibold">{{ t('modelProvider.noProviders') || 'No Providers' }}</h3>
      <p class="text-sm text-muted-foreground mt-2 max-w-sm">
        {{ t('modelProvider.noProvidersDesc') || 'Get started by creating your first model provider.' }}
      </p>
      <Button class="mt-6" @click="handleCreate">
        <Plus class="mr-2 h-4 w-4" />
        {{ t('modelProvider.createTitle') }}
      </Button>
    </div>

    <!-- Dialog -->
    <Dialog :open="dialogOpen" @update:open="dialogOpen = $event">
      <DialogContent class="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{{ isEdit ? t('modelProvider.editTitle') : t('modelProvider.createTitle') }}</DialogTitle>
        </DialogHeader>
        <div class="grid gap-4 py-4">
          <div class="grid gap-2">
            <Label>{{ t('modelProvider.name') }} <span class="text-destructive">*</span></Label>
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
              
              <Input v-if="selectedProvider === 'Custom'" v-model="form.name" :placeholder="t('modelProvider.customNamePlaceholder')" />
            </div>
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
                <ArrowRight class="ml-1 w-3 h-3" />
              </Button>
            </div>
            <Input
              v-model="form.api_keys_str"
              :placeholder="t('modelProvider.apiKeyPlaceholder')"
              @update:model-value="handleApiKeyChange"
            />
          </div>
          <div class="grid gap-2">
             <div class="flex items-center justify-between">
               <Label>{{ t('modelProvider.model') }} <span class="text-destructive">*</span></Label>
               <Button
                 v-if="currentProvider?.model_list_url"
                 variant="link"
                 size="sm"
                 class="h-auto p-0 text-primary"
                 @click="openProviderModelList"
               >
                 {{ t('modelProvider.viewModelList') }}
                 <ArrowRight class="ml-1 w-3 h-3" />
               </Button>
             </div>
             <div v-if="currentProvider?.models?.length" class="flex gap-2">
               <div class="flex-1 relative">
                  <Input
                     v-model="form.model"
                     :placeholder="t('modelProvider.modelPlaceholder')"
                     class="pr-10"
                     @update:model-value="onKeyConfigChange"
                  />
                  <div class="absolute right-0 top-0 h-full">
                     <Select :model-value="''" @update:model-value="(val) => { form.model = val; onKeyConfigChange(); }">
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
             <Input v-else v-model="form.model" :placeholder="t('modelProvider.modelPlaceholder')" @update:model-value="onKeyConfigChange" />
             <p class="text-xs text-muted-foreground">{{ t('modelProvider.modelHint') }}</p>
          </div>
          
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

          <!-- 多模态支持 -->
          <div class="grid gap-3">
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
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
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

const buildApiKeys = () => {
  const apiKey = form.api_keys_str.trim()
  return apiKey ? [apiKey] : []
}

const buildProviderPayload = () => ({
  name: form.name,
  base_url: form.base_url,
  api_keys: buildApiKeys(),
  model: form.model,
  max_tokens: form.maxTokens,
  temperature: form.temperature,
  top_p: form.topP,
  presence_penalty: form.presencePenalty,
  max_model_len: form.maxModelLen,
  supports_multimodal: form.supportsMultimodal
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
    verified.value = false
    multimodalVerified.value = false
    form.supportsMultimodal = false
    return
  }
  const provider = MODEL_PROVIDERS.find(p => p.name === val)
  if (provider) {
    form.name = provider.name
    form.base_url = provider.base_url
    // form.model = provider.models[0] || ''
  }
  verified.value = false
  multimodalVerified.value = false
  form.supportsMultimodal = false
}

const onKeyConfigChange = () => {
  // 当关键配置变化时，重置验证状态
  verified.value = false
  multimodalVerified.value = false
}

const handleApiKeyChange = (value) => {
  form.api_keys_str = `${value ?? ''}`.split(/\r?\n/, 1)[0]
  onKeyConfigChange()
}

const openProviderWebsite = () => {
  if (currentProvider.value?.website) {
    window.open(currentProvider.value.website, '_blank')
  }
}

const openProviderModelList = () => {
  if (currentProvider.value?.model_list_url) {
    window.open(currentProvider.value.model_list_url, '_blank')
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

const getProviderName = (provider) => {
  const match = MODEL_PROVIDERS.find(p => p.base_url === provider.base_url)
  return match ? match.name : 'Custom'
}

const handleCreate = () => {
  isEdit.value = false
  currentId.value = null
  form.name = ''
  selectedProvider.value = ''
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
  isEdit.value = true
  currentId.value = provider.id
  form.name = provider.name

  // Try to match provider
  const known = MODEL_PROVIDERS.find(p => p.base_url === provider.base_url)
  selectedProvider.value = known ? known.name : 'Custom'

  form.base_url = provider.base_url
  // api_keys are not returned in list usually for security?
  // But DTO has them. The backend router returns them.
  // Ideally we should mask them.
  // But for editing we need them.
  // The backend router returns full DTO.
  form.api_keys_str = `${provider.api_keys?.[0] || ''}`.trim()
  form.model = provider.model
  form.maxTokens = provider.max_tokens ?? 4096
  form.temperature = provider.temperature ?? 0.7
  form.topP = provider.top_p ?? 0.9
  form.presencePenalty = provider.presence_penalty ?? 0.0
  form.maxModelLen = provider.max_model_len ?? 32000
  form.supportsMultimodal = provider.supports_multimodal ?? false

  // 保存原始值用于比较
  originalValues.base_url = provider.base_url
  originalValues.api_keys_str = `${provider.api_keys?.[0] || ''}`.trim()
  originalValues.model = provider.model
  originalValues.supportsMultimodal = provider.supports_multimodal ?? false

  // 编辑模式初始状态设为已验证（如果没有变化）
  verified.value = true
  multimodalVerified.value = form.supportsMultimodal

  dialogOpen.value = true
}

const handleDelete = async (provider) => {
  if (confirm(t('common.confirmDelete'))) {
     try {
       await deleteModelProvider(provider.id)
       toast.success(t('common.deleteSuccess'))
       fetchProviders()
     } catch (error) {
       toast.error(error.message)
     }
  }
}

const handleVerify = async () => {
  const data = buildProviderPayload()

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
    const data = buildProviderPayload()
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
  const data = buildProviderPayload()

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
