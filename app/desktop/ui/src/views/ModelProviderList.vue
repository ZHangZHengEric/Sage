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
                 <Badge variant="outline" class="text-xs font-normal text-muted-foreground">
                    {{ getProviderName(provider) }}
                 </Badge>
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
                  <SelectValue placeholder="Select a provider" />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectLabel>Providers</SelectLabel>
                    <SelectItem v-for="provider in MODEL_PROVIDERS" :key="provider.name" :value="provider.name">
                      {{ provider.name }}
                    </SelectItem>
                    <SelectItem value="Custom">Custom Provider</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
              
              <Input v-if="selectedProvider === 'Custom'" v-model="form.name" placeholder="Custom Provider Name" />
            </div>
          </div>
          <div class="grid gap-2">
            <Label>{{ t('modelProvider.baseUrl') }} <span class="text-destructive">*</span></Label>
            <Input v-model="form.base_url" placeholder="https://api.openai.com/v1" />
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
            <Input v-model="form.api_keys_str" :placeholder="t('modelProvider.apiKeyPlaceholder')" />
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
                  />
                  <div class="absolute right-0 top-0 h-full">
                     <Select :model-value="''" @update:model-value="(val) => form.model = val">
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
        </div>
        <DialogFooter>
          <Button variant="outline" @click="dialogOpen = false">{{ t('common.cancel') }}</Button>
          <Button @click="submitForm">{{ t('common.save') }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { Plus, Edit, Trash2, Bot, ArrowRight } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { open } from '@tauri-apps/api/shell'
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
  maxModelLen: 64000
})

const selectedProvider = ref('')
const currentProvider = computed(() => MODEL_PROVIDERS.find(p => p.name === selectedProvider.value))

const handleProviderChange = (val) => {
  selectedProvider.value = val
  if (val === 'Custom') {
    form.name = ''
    form.base_url = ''
    form.model = ''
    return
  }
  const provider = MODEL_PROVIDERS.find(p => p.name === val)
  if (provider) {
    form.name = provider.name
    form.base_url = provider.base_url
    // form.model = provider.models[0] || ''
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
  isCustomModel.value = false
  form.base_url = ''
  form.api_keys_str = ''
  form.model = ''
  form.maxTokens = 8192
  form.temperature = 0.7
  form.topP = 0.95
  form.presencePenalty = 0
  form.maxModelLen = 64000
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
    
    dialogOpen.value = true
  } catch (error) {
    console.error('Failed to open edit dialog:', error)
    toast.error('Unable to open edit dialog')
  }
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

const submitForm = async () => {
  const data = {
    name: form.name,
    base_url: form.base_url,
    api_keys: form.api_keys_str.split(/[\n,]+/).map(k => k.trim()).filter(k => k),
    model: form.model,
    max_tokens: form.maxTokens,
    temperature: form.temperature,
    top_p: form.topP,
    presence_penalty: form.presencePenalty,
    max_model_len: form.maxModelLen
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
