<template>
  <div class="knowledge-base-add">
    <div class="add-header">
      <h2>{{ t('knowledgeBase.addKnowledgeBase') }}</h2>
      <p class="add-description">{{ t('knowledgeBase.addKnowledgeBaseDesc') }}</p>
    </div>

    <form @submit.prevent="handleSubmit" class="add-form">
      <!-- 知识库名称 -->
      <div class="form-group">
        <label class="form-label" for="kb-name">
          {{ t('knowledgeBase.name') }}
          <span class="required">*</span>
        </label>
        <input
          id="kb-name"
          v-model="formData.name"
          type="text"
          class="form-input"
          :placeholder="t('knowledgeBase.namePlaceholder')"
          required
        />
        <div v-if="errors.name" class="error-message">{{ errors.name }}</div>
      </div>

      <!-- 知识库类型 -->
      <div class="form-group">
        <label class="form-label" for="kb-type">
          {{ t('knowledgeBase.type') }}
          <span class="required">*</span>
        </label>
        <select
          id="kb-type"
          v-model="formData.type"
          class="form-select"
          required
        >
          <option value="document">{{ t('knowledgeBase.documentType') }}</option>
        </select>
        <div class="type-description">
          {{ getTypeDescription(formData.type) }}
        </div>
        <div v-if="errors.type" class="error-message">{{ errors.type }}</div>
      </div>

      <!-- 知识库描述 -->
      <div class="form-group">
        <label class="form-label" for="kb-description">
          {{ t('knowledgeBase.description') }}
        </label>
        <textarea
          id="kb-description"
          v-model="formData.description"
          class="form-textarea"
          :placeholder="t('knowledgeBase.descriptionPlaceholder')"
          rows="3"
        ></textarea>
        <div v-if="errors.description" class="error-message">{{ errors.description }}</div>
      </div>

      <!-- 表单按钮 -->
      <div class="form-actions">
        <button
          type="button"
          class="btn-secondary"
          @click="handleCancel"
          :disabled="loading"
        >
          {{ t('common.cancel') }}
        </button>
        <button
          type="submit"
          class="btn-primary"
          :disabled="loading || !isFormValid"
        >
          <div v-if="loading" class="loading-spinner"></div>
          {{ loading ? t('common.creating') : t('common.create') }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, computed, defineEmits, defineExpose } from 'vue'
import { useLanguage } from '../utils/i18n.js'
import { knowledgeBaseAPI } from '../api/knowledgeBase.js'

// Composables
const { t } = useLanguage()

// Props
const props = defineProps({})

// Emits
const emit = defineEmits(['success', 'cancel'])

// State
const formData = ref({
  name: '',
  type: 'document', // 默认文档知识库
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

  // 验证名称
  if (!formData.value.name.trim()) {
    errors.value.name = t('knowledgeBase.nameRequired')
  } else if (formData.value.name.trim().length < 2) {
    errors.value.name = t('knowledgeBase.nameTooShort')
  } else if (formData.value.name.trim().length > 50) {
    errors.value.name = t('knowledgeBase.nameTooLong')
  }

  // 验证类型
  if (!formData.value.type) {
    errors.value.type = t('knowledgeBase.typeRequired')
  }

  // 验证描述长度
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

    if (response && response.success) {
      emit('success', response.data)
      resetForm()
    }
  } catch (error) {
    console.error('Failed to add knowledge base:', error)
    // 可以在这里添加错误提示
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

// Expose methods
defineExpose({
  resetForm
})
</script>

<style scoped>
.knowledge-base-add {
  padding: 2rem;
  max-width: 600px;
  margin: 0 auto;
  background: white;
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.add-header {
  margin-bottom: 2rem;
  text-align: center;
}

.add-header h2 {
  margin: 0 0 0.5rem 0;
  font-size: 24px;
  font-weight: 600;
  color: #333333;
}

.add-description {
  margin: 0;
  font-size: 14px;
  color: rgba(0, 0, 0, 0.7);
  line-height: 1.5;
}

.add-form {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-label {
  font-size: 14px;
  font-weight: 600;
  color: #333333;
  display: flex;
  align-items: center;
  gap: 4px;
}

.required {
  color: #ef4444;
  font-size: 12px;
}

.form-input,
.form-select,
.form-textarea {
  padding: 12px 16px;
  border: 1px solid rgba(0, 0, 0, 0.2);
  border-radius: 8px;
  font-size: 14px;
  transition: all 0.2s ease;
  background: white;
}

.form-input:focus,
.form-select:focus,
.form-textarea:focus {
  outline: none;
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

.form-textarea {
  resize: vertical;
  min-height: 80px;
  font-family: inherit;
}

.type-description {
  font-size: 12px;
  color: rgba(0, 0, 0, 0.6);
  line-height: 1.4;
  margin-top: 4px;
  padding: 8px 12px;
  background: rgba(102, 126, 234, 0.05);
  border-radius: 6px;
  border-left: 3px solid #667eea;
}

.error-message {
  font-size: 12px;
  color: #ef4444;
  margin-top: 4px;
}

.form-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid rgba(0, 0, 0, 0.1);
}

.btn-secondary,
.btn-primary {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 100px;
  justify-content: center;
}

.btn-secondary {
  background: rgba(0, 0, 0, 0.05);
  color: #333333;
  border: 1px solid rgba(0, 0, 0, 0.2);
}

.btn-secondary:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.1);
}

.btn-primary {
  background: #667eea;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #5a6fd8;
}

.btn-secondary:disabled,
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.loading-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid transparent;
  border-top: 2px solid currentColor;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* 响应式设计 */
@media (max-width: 768px) {
  .knowledge-base-add {
    padding: 1.5rem;
    margin: 1rem;
  }

  .form-actions {
    flex-direction: column;
  }

  .btn-secondary,
  .btn-primary {
    width: 100%;
  }
}
</style>