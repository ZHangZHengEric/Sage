<template>
  <div class="three-option-switch">
    <div class="switch-label-container">
      <span class="switch-label">{{ label }}</span>
      <small v-if="description" class="switch-description">{{ description }}</small>
    </div>
    <div class="option-buttons">
      <button
        type="button"
        :class="['option-button', { active: currentOption === 'off' }]"
        @click="handleOptionChange('off')"
        :disabled="disabled"
      >
        {{ t('common.off') }}
      </button>
      <button
        type="button"
        :class="['option-button', { active: currentOption === 'auto' }]"
        @click="handleOptionChange('auto')"
        :disabled="disabled"
      >
        {{ t('common.auto') }}
      </button>
      <button
        type="button"
        :class="['option-button', { active: currentOption === 'on' }]"
        @click="handleOptionChange('on')"
        :disabled="disabled"
      >
        {{ t('common.on') }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useLanguage } from '../../utils/language.js'

// Props
const props = defineProps({
  value: {
    type: [Boolean, null],
    default: null
  },
  disabled: {
    type: Boolean,
    default: false
  },
  label: {
    type: String,
    required: true
  },
  description: {
    type: String,
    default: ''
  }
})

// Emits
const emit = defineEmits(['change'])

// Composables
const { t } = useLanguage()

// Computed
const currentOption = computed(() => {
  return getOptionFromValue(props.value)
})

// Methods
const getOptionFromValue = (val) => {
  if (val === null || val === undefined) return 'auto'
  return val ? 'on' : 'off'
}

const getValueFromOption = (option) => {
  switch (option) {
    case 'on': return true
    case 'off': return false
    case 'auto': return null
    default: return null
  }
}

const handleOptionChange = (option) => {
  if (props.disabled) return
  const newValue = getValueFromOption(option)
  emit('change', newValue)
}
</script>

<style scoped>
.three-option-switch {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}

.switch-label-container {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.switch-label {
  font-size: 14px;
  font-weight: 600;
  color: #2c3e50;
  margin: 0;
  letter-spacing: 0.3px;
}

.switch-description {
  font-size: 12px;
  color: #7f8c8d;
  margin: 0;
  line-height: 1.5;
  font-style: italic;
}

.option-buttons {
  display: flex;
  border: 2px solid #e8ecef;
  border-radius: 12px;
  overflow: hidden;
  background: #f8f9fa;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  position: relative;
}

.option-button {
  flex: 1;
  padding: 8px 12px;
  border: none;
  background: transparent;
  color: #6c757d;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  z-index: 1;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.option-button:hover:not(:disabled) {
  color: #495057;
  transform: translateY(-1px);
}

.option-button.active {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
  transform: translateY(-2px);
}

.option-button.active:hover {
  box-shadow: 0 6px 16px rgba(102, 126, 234, 0.5);
  transform: translateY(-3px);
}

.option-button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
  background: #e9ecef;
  color: #adb5bd;
}

.option-button:disabled.active {
  background: linear-gradient(135deg, #95a5a6 0%, #7f8c8d 100%);
  color: #fff;
  box-shadow: none;
  transform: none;
}

/* 深色主题支持 */
@media (prefers-color-scheme: dark) {
  .switch-label {
    color: #f8f9fa;
  }
  
  .switch-description {
    color: #adb5bd;
  }
  
  .option-buttons {
    border-color: #495057;
    background: #2c3e50;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  }
  
  .option-button {
    color: #adb5bd;
  }
  
  .option-button:hover:not(:disabled) {
    color: #f8f9fa;
  }
  
  .option-button:disabled {
    background: #495057;
    color: #6c757d;
  }
}



/* 高对比度模式 */
@media (prefers-contrast: high) {
  .option-buttons {
    border-width: 3px;
  }
  
  .option-button {
    font-weight: 600;
  }
  
  .option-button.active {
    background: #000;
    color: #fff;
  }
}

/* 减少动画模式 */
@media (prefers-reduced-motion: reduce) {
  .option-button {
    transition: none;
  }
  
  .option-button:hover:not(:disabled) {
    transform: none;
  }
  
  .option-button.active {
    transform: none;
  }
  
  .option-button.active:hover {
    transform: none;
  }
}
</style>