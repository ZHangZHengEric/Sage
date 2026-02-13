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
                <Button variant="ghost" size="icon" @click="handleEdit(provider)" :disabled="provider.is_default">
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
            <Label>{{ t('modelProvider.name') }}</Label>
            <Input v-model="form.name" />
          </div>
          <div class="grid gap-2">
            <Label>{{ t('modelProvider.baseUrl') }}</Label>
            <!-- Suggestions for mainstream providers -->
            <Input v-model="form.base_url" placeholder="https://api.openai.com/v1" />
            <div class="flex gap-2 text-xs flex-wrap">
                <span class="cursor-pointer text-blue-500 hover:underline" @click="form.base_url='https://api.openai.com/v1'">OpenAI</span>
                <span class="cursor-pointer text-blue-500 hover:underline" @click="form.base_url='https://api.deepseek.com'">DeepSeek</span>
                <span class="cursor-pointer text-blue-500 hover:underline" @click="form.base_url='https://dashscope.aliyuncs.com/compatible-mode/v1'">Aliyun</span>
                <span class="cursor-pointer text-blue-500 hover:underline" @click="form.base_url='https://ark.cn-beijing.volces.com/api/v3'">ByteDance</span>
            </div>
          </div>
          <div class="grid gap-2">
            <Label>{{ t('modelProvider.apiKey') }}</Label>
            <Textarea v-model="form.api_keys_str" :placeholder="t('modelProvider.apiKeyPlaceholder')" />
          </div>
          <div class="grid gap-2">
             <Label>{{ t('modelProvider.model') }}</Label>
             <Input v-model="form.model" :placeholder="t('modelProvider.modelPlaceholder')" />
             <p class="text-xs text-muted-foreground">{{ t('modelProvider.modelHint') }}</p>
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
import { ref, reactive, onMounted } from 'vue'
import { Plus, Edit, Trash2, Bot } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
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
  model: ''
})

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
  form.base_url = ''
  form.api_keys_str = ''
  form.model = ''
  dialogOpen.value = true
}

const handleEdit = (provider) => {
  isEdit.value = true
  currentId.value = provider.id
  form.name = provider.name
  form.base_url = provider.base_url
  // api_keys are not returned in list usually for security?
  // But DTO has them. The backend router returns them.
  // Ideally we should mask them.
  // But for editing we need them.
  // The backend router returns full DTO.
  form.api_keys_str = (provider.api_keys || []).join('\n')
  form.model = provider.model
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

const submitForm = async () => {
  const data = {
    name: form.name,
    base_url: form.base_url,
    api_keys: form.api_keys_str.split(/[\n,]+/).map(k => k.trim()).filter(k => k),
    model: form.model
  }
  
  try {
    if (isEdit.value) {
      await updateModelProvider(currentId.value, data)
    } else {
      await createModelProvider(data)
    }
    
    toast.success(t('common.saveSuccess'))
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
