<template>
  <div v-if="isOpen" class="modal-overlay">
    <div class="agent-creation-modal">
      <div class="modal-header">
        <h3>{{ t('agentCreation.title') }}</h3>
        <button class="close-btn" @click="handleClose" :disabled="isGenerating">
          <X :size="20" />
        </button>
      </div>

      <div class="modal-content">
        <div v-if="!selectedType" class="creation-options">
          <div class="option-card" @click="handleCreateBlank">
            <div class="option-icon">
              <FileText :size="32" />
            </div>
            <h4>{{ t('agentCreation.blankConfig') }}</h4>
            <p>{{ t('agentCreation.blankConfigDesc') }}</p>
          </div>

          <div class="option-card" @click="handleTypeSelect('smart')">
            <div class="option-icon">
              <Sparkles :size="32" />
            </div>
            <h4>{{ t('agentCreation.smartConfig') }}</h4>
            <p>{{ t('agentCreation.smartConfigDesc') }}</p>
          </div>
        </div>


        <div v-if="selectedType === 'smart'" class="smart-config-section">
          <div class="section-icon">
            <Sparkles :size="24" />
          </div>
          <h4>{{ t('agentCreation.smartConfig') }}</h4>
          <p>请描述您希望创建的Agent功能，我们将自动生成配置</p>
          
          <div class="description-input">
            <label>Agent描述</label>
            <textarea
              v-model="description"
              :placeholder="t('agentCreation.descriptionPlaceholder')"
              :rows="4"
              :disabled="isGenerating"
            />
          </div>

          <div class="action-buttons">
            <button 
              class="btn btn-ghost" 
              @click="selectedType = ''"
              :disabled="isGenerating"
            >
              返回
            </button>
            <button 
              class="btn btn-primary" 
              @click="handleCreateSmart"
              :disabled="!description.trim() || isGenerating"
            >
              <template v-if="isGenerating">
                <Loader :size="16" class="spinning" />
                {{ t('agentCreation.generating') }}
              </template>
              <template v-else>
                <Sparkles :size="16" />
                {{ t('agentCreation.generate') }}
              </template>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { X, Bot, Sparkles, FileText, Loader } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { useLanguage } from '../utils/language.js'

// Props
const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false
  }
})

// Emits
const emit = defineEmits(['close', 'create-blank', 'create-smart'])

// Composables
const { t } = useLanguage()

// State
const selectedType = ref('')
const description = ref('')
const isGenerating = ref(false)

// Methods
const handleTypeSelect = (type) => {
  selectedType.value = type
  if (type === 'blank') {
    description.value = ''
  }
}

const handleCreateBlank = () => {
  emit('create-blank')
  handleClose()
}

const handleCreateSmart = async () => {
  if (!description.value.trim()) {
    ElMessage.error(t('agentCreation.error'))
    return
  }

  isGenerating.value = true
  try {
    await emit('create-smart', description.value.trim())
    handleClose()
  } catch (error) {
    console.error('Smart creation failed:', error)
    ElMessage.error(t('agentCreation.error'))
  } finally {
    isGenerating.value = false
  }
}

const handleClose = () => {
  selectedType.value = ''
  description.value = ''
  isGenerating.value = false
  emit('close')
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.agent-creation-modal {
  background: var(--bg-primary);
  border-radius: 16px;
    background: rgb(250, 248, 248);

  box-shadow: 0 25px 50px rgba(0, 0, 0, 0.25), 0 0 0 1px rgba(255, 255, 255, 0.1);
  max-width: 600px;
  width: 100%;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transform: scale(1);
  transition: all 0.3s ease;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24px 24px 0 24px;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 16px;
  margin-bottom: 24px;
}

.modal-header h3 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

.close-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 8px;
  border-radius: 8px;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.close-btn:hover:not(:disabled) {
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.close-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.modal-content {
  padding: 12px 24px 24px 24px;
  overflow-y: auto;
}

.creation-options {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.option-card {
  background: var(--bg-secondary);
  border: 2px solid var(--border-color);
  border-radius: 12px;
  padding: 24px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.option-card:hover {
  border-color: var(--primary-color);
  background: var(--primary-color-alpha);
  transform: translateY(-2px);
}

.option-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  background: var(--primary-color-alpha);
  border-radius: 16px;
  margin: 0 auto 16px auto;
  color: var(--primary-color);
}

.option-card h4 {
  margin: 0 0 8px 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.option-card p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.5;
}

.blank-config-section,
.smart-config-section {
  text-align: center;
}

.section-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  background: var(--primary-color-alpha);
  border-radius: 16px;
  margin: 0 auto 20px auto;
  color: var(--primary-color);
}

.blank-config-section h4,
.smart-config-section h4 {
  margin: 0 0 12px 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

.blank-config-section p,
.smart-config-section p {
  margin: 0 0 24px 0;
  color: var(--text-secondary);
  font-size: 16px;
  line-height: 1.5;
}

.description-input {
  text-align: left;
  margin-bottom: 24px;
}

.description-input label {
  display: block;
  margin-bottom: 8px;
  font-weight: 500;
  color: var(--text-primary);
  font-size: 14px;
}

.description-input textarea {
  width: 100%;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 14px;
  font-family: inherit;
  background: var(--bg-primary);
  color: var(--text-primary);
  resize: vertical;
  min-height: 100px;
  transition: border-color 0.2s ease;
}

.description-input textarea:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px var(--primary-color-alpha);
}

.description-input textarea:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.action-buttons {
  display: flex;
  gap: 12px;
  justify-content: center;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  text-decoration: none;
  min-width: 120px;
  justify-content: center;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-ghost {
  background: var(--bg-secondary);
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}

.btn-ghost:hover:not(:disabled) {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border-color: var(--text-secondary);
}

.btn-primary {
  background: var(--primary-color);
  color: rgb(22, 21, 21);
}

.btn-primary:hover:not(:disabled) {
  background: var(--primary-color-hover);
  transform: translateY(-1px);
}

.spinning {
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


</style>