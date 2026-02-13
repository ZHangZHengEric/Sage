<template>
  <div class="max-w-2xl mx-auto p-4 animate-in fade-in zoom-in-95 duration-300">
    <Card class="shadow-lg border-muted/60">
      <CardHeader class="space-y-2 text-center pb-8">
        <CardTitle class="text-2xl font-bold tracking-tight">{{ t('knowledgeBase.addKnowledgeBase') }}</CardTitle>
        <CardDescription class="text-base">{{ t('knowledgeBase.addKnowledgeBaseDesc') }}</CardDescription>
      </CardHeader>
      <CardContent>
        <form @submit.prevent="handleSubmit" class="space-y-6">
          <!-- 知识库名称 -->
          <div class="space-y-2">
            <Label for="kb-name" class="text-sm font-medium">
              {{ t('knowledgeBase.name') }} <span class="text-destructive">*</span>
            </Label>
            <Input
              id="kb-name"
              v-model="formData.name"
              :placeholder="t('knowledgeBase.namePlaceholder')"
              :class="{ 'border-destructive focus-visible:ring-destructive': errors.name }"
            />
            <span v-if="errors.name" class="text-xs text-destructive flex items-center gap-1">
              {{ errors.name }}
            </span>
          </div>

          <!-- 知识库类型 -->
          <div class="space-y-2">
            <Label for="kb-type" class="text-sm font-medium">
              {{ t('knowledgeBase.type') }} <span class="text-destructive">*</span>
            </Label>
            <div class="relative">
              <select
                id="kb-type"
                v-model="formData.type"
                class="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 appearance-none"
              >
                <option value="document">{{ t('knowledgeBase.documentType') }}</option>
                <option value="qa">{{ t('knowledgeBase.qaType') }}</option>
              </select>
              <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-muted-foreground">
                <ChevronDown class="h-4 w-4" />
              </div>
            </div>
            <div class="text-xs text-muted-foreground bg-muted/50 p-3 rounded-md border border-muted flex items-start gap-2">
              <Info class="h-4 w-4 shrink-0 text-primary mt-0.5" />
              <span>{{ getTypeDescription(formData.type) }}</span>
            </div>
          </div>

          <!-- 知识库描述 -->
          <div class="space-y-2">
            <Label for="kb-description" class="text-sm font-medium">
              {{ t('knowledgeBase.description') }}
            </Label>
            <Textarea
              id="kb-description"
              v-model="formData.description"
              :placeholder="t('knowledgeBase.descriptionPlaceholder')"
              class="min-h-[100px] resize-y"
              :class="{ 'border-destructive focus-visible:ring-destructive': errors.description }"
            />
            <span v-if="errors.description" class="text-xs text-destructive">{{ errors.description }}</span>
          </div>

          <!-- 表单按钮 -->
          <div class="flex justify-end gap-3 pt-6">
            <Button
              type="button"
              variant="outline"
              @click="handleCancel"
              :disabled="loading"
            >
              {{ t('common.cancel') }}
            </Button>
            <Button
              type="submit"
              :disabled="loading || !isFormValid"
            >
              <Loader v-if="loading" class="mr-2 h-4 w-4 animate-spin" />
              {{ loading ? t('common.creating') : t('common.create') }}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ChevronDown, Info, Loader } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { knowledgeBaseAPI } from '../api/knowledgeBase.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

// Composables
const { t } = useLanguage()

// Emits
const emit = defineEmits(['success', 'cancel'])

// State
const formData = ref({
  name: '',
  type: 'document',
  description: ''
})

const errors = ref({})
const loading = ref(false)

// Computed
const isFormValid = computed(() => {
  return formData.value.name.trim() && 
         formData.value.type && 
         Object.keys(errors.value).length === 0
})

// Methods
const validateForm = () => {
  errors.value = {}

  if (!formData.value.name.trim()) {
    errors.value.name = t('knowledgeBase.nameRequired')
  } else if (formData.value.name.trim().length < 2) {
    errors.value.name = t('knowledgeBase.nameTooShort')
  } else if (formData.value.name.trim().length > 50) {
    errors.value.name = t('knowledgeBase.nameTooLong')
  }

  if (!formData.value.type) {
    errors.value.type = t('knowledgeBase.typeRequired')
  }

  if (formData.value.description && formData.value.description.length > 200) {
    errors.value.description = t('knowledgeBase.descriptionTooLong')
  }

  return Object.keys(errors.value).length === 0
}

const handleSubmit = async () => {
  if (!validateForm()) {
    return
  }

  try {
    loading.value = true
    
    const data = {
      name: formData.value.name.trim(),
      type: formData.value.type,
      intro: formData.value.description.trim()
    }

    const response = await knowledgeBaseAPI.addKnowledgeBase(data)
    emit('success', response)
    resetForm()
  } catch (error) {
    console.error('Failed to add knowledge base:', error)
  } finally {
    loading.value = false
  }
}

const handleCancel = () => {
  emit('cancel')
}

const resetForm = () => {
  formData.value = {
    name: '',
    type: 'document',
    description: ''
  }
  errors.value = {}
}

const getTypeDescription = (type) => {
  switch (type) {
    case 'document':
      return t('knowledgeBase.documentTypeDesc')
    case 'qa':
      return t('knowledgeBase.qaTypeDesc')
    case 'code':
      return t('knowledgeBase.codeTypeDesc')
    default:
      return ''
  }
}

defineExpose({
  resetForm
})
</script>
