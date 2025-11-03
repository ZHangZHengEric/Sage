<template>
  <form @submit="handleSubmit" class="message-form">
      <div class="input-wrapper">
        <textarea
          ref="textareaRef"
          v-model="inputValue"
          @keydown="handleKeyDown"
          :placeholder="t('messageInput.placeholder')"
          class="message-textarea"
          :disabled="isLoading"
          rows="1"
        />
        <div class="button-group">
          <button
            v-if="isLoading"
            type="button"
            @click="handleStop"
            class="stop-button"
            :title="t('messageInput.stopTitle')"
          >
            ⏹️ {{ t('messageInput.stop') }}
          </button>
          <button
            v-else
            type="submit"
            :disabled="!inputValue.trim()"
            class="send-button"
            :title="t('messageInput.sendTitle')"
          >
            📤 {{ t('messageInput.send') }}
          </button>
        </div>
      </div>
    </form>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { useLanguage } from '../../utils/i18n.js'

const props = defineProps({
  isLoading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['sendMessage', 'stopGeneration'])

const { t } = useLanguage()

const inputValue = ref('')
const textareaRef = ref(null)

// 自动调整文本区域高度
const adjustTextareaHeight = async () => {
  await nextTick()
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto'
    textareaRef.value.style.height = `${textareaRef.value.scrollHeight}px`
  }
}

// 监听输入值变化，自动调整高度
watch(inputValue, () => {
  adjustTextareaHeight()
})

// 处理表单提交
const handleSubmit = (e) => {
  e.preventDefault()
  if (inputValue.value.trim() && !props.isLoading) {
    emit('sendMessage', inputValue.value.trim())
    inputValue.value = ''
  }
}

// 处理键盘事件
const handleKeyDown = (e) => {
  // 检查是否在输入法组合状态中，如果是则不处理回车键
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    handleSubmit(e)
  }
}

// 处理停止生成
const handleStop = () => {
  emit('stopGeneration')
}
</script>

<style scoped>

.message-form {
  max-width: 800px;
  margin: 0 auto;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  background: #f8f9fa;
  border: 2px solid #e1e5e9;
  border-radius: 24px;
  padding: 12px 16px;
  transition: all 0.2s ease;
}

.input-wrapper:focus-within {
  border-color: #4facfe;
  box-shadow: 0 0 0 3px rgba(79, 172, 254, 0.1);
}

.message-textarea {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  resize: none;
  font-size: 16px;
  line-height: 1.5;
  color: #333;
  font-family: inherit;
  min-height: 24px;
  max-height: 200px;
  overflow-y: auto;
}

.message-textarea::placeholder {
  color: #999;
}

.message-textarea:disabled {
  color: #999;
  cursor: not-allowed;
}

.button-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.send-button,
.stop-button {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  border-radius: 16px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.send-button {
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  color: white;
}

.send-button:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(79, 172, 254, 0.3);
}

.send-button:disabled {
  background: #e1e5e9;
  color: #999;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.stop-button {
  background: linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%);
  color: white;
}

.stop-button:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(255, 107, 107, 0.3);
}

/* 滚动条样式 */
.message-textarea::-webkit-scrollbar {
  width: 6px;
}

.message-textarea::-webkit-scrollbar-track {
  background: transparent;
}

.message-textarea::-webkit-scrollbar-thumb {
  background: #ccc;
  border-radius: 3px;
}

.message-textarea::-webkit-scrollbar-thumb:hover {
  background: #999;
}

/* 深色模式支持 */
@media (prefers-color-scheme: dark) {
  .message-input-container {
    background: #1a1a1a;
    border-top-color: #333;
  }
  
  .input-wrapper {
    background: #2d2d2d;
    border-color: #444;
  }
  
  .input-wrapper:focus-within {
    border-color: #4facfe;
  }
  
  .message-textarea {
    color: #fff;
  }
  
  .message-textarea::placeholder {
    color: #888;
  }
}
</style>