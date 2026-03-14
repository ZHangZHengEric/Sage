<template>
  <div class="h-full flex flex-col p-6 space-y-6">
    <div class="flex items-center justify-between">
      <div class="flex-1"></div>
      <Button @click="handleCreate">
        <Plus class="mr-2 h-4 w-4" />
        {{ t('common.create') }}
      </Button>
    </div>

    <div v-if="providers && providers.length > 0" class="border rounded-md">
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
               <div class="flex items-center gap-2">
                 {{ provider.name }}
                 <Badge v-if="provider.is_default" variant="secondary">{{ t('common.default') }}</Badge>
               </div>
            </TableCell>
            <TableCell>{{ provider.base_url }}</TableCell>
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
    
    <div v-else class="flex flex-col items-center justify-center py-12 text-center border rounded-md border-dashed">
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
            <Input v-model="form.api_keys_str" :placeholder="t('modelProvider.apiKeyPlaceholder')" @update:model-value="onKeyConfigChange" />
          </div>
          <div class="grid gap-2">
             <Label>{{ t('modelProvider.model') }} <span class="text-destructive">*</span></Label>
             <Input v-model="form.model" :placeholder="t('modelProvider.modelPlaceholder')" @update:model-value="onKeyConfigChange" />
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
                <Label for="multimodal" class="cursor-pointer">多模态（图像输入）</Label>
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
                {{ multimodalVerified ? '已验证' : '验证多模态' }}
              </Button>
            </div>
            <p v-if="form.supportsMultimodal && !multimodalVerified" class="text-xs text-amber-600">
              请验证多模态支持以确保功能正常
            </p>
            <p v-if="multimodalVerified" class="text-xs text-green-600">
              多模态验证通过
            </p>
          </div>
        </div>
        <DialogFooter class="flex sm:justify-between items-center w-full">
          <Button type="button" variant="secondary" @click="handleVerify" :disabled="verifying">
            <Loader v-if="verifying" class="mr-2 h-4 w-4 animate-spin" />
            {{ t('common.verify') || '验证' }}
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
     toast.error(t('common.fillRequired') || '请填写必填项')
     return
  }

  verifying.value = true
  try {
    await modelProviderAPI.verifyModelProvider(data)
    verified.value = true
    toast.success(t('common.verifySuccess') || '验证成功')
  } catch (error) {
    verified.value = false
    toast.error(error.message || '验证失败')
  } finally {
    verifying.value = false
  }
}

const handleVerifyMultimodal = async () => {
  if (!form.model) {
    toast.error('请先填写模型名称')
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
        toast.success('多模态验证成功，模型正确识别了图片内容')
      } else {
        toast.success('多模态验证成功，但模型未能正确识别图片内容')
      }
    } else {
      multimodalVerified.value = false
      toast.warning('该模型不支持多模态')
      form.supportsMultimodal = false
    }
  } catch (error) {
    console.error('Failed to verify multimodal:', error)
    multimodalVerified.value = false
    toast.error(error.message || '多模态验证失败')
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
        toast.error('请先验证多模态支持')
        return
      }
    } else {
      if (!verified.value) {
        toast.error('请先验证连接')
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
