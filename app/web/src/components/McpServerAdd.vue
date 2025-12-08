<template>
  <div class="add-mcp-view">
    <div class="tool-detail-content">
      <form @submit.prevent="handleSubmit" class="add-mcp-form">
        <div class="tool-section">
          <h3>
            <Database :size="20" />
            {{ t('tools.basicInfo') }}
          </h3>

          <div class="form-group">
            <label for="name">{{ t('tools.serverName') }}</label>
            <input 
              id="name" 
              v-model="form.name" 
              type="text" 
              :placeholder="t('tools.enterServerName')" 
              required
              class="form-input" 
            />
          </div>
        </div>

        <div class="tool-section">
          <h3>
            <Code :size="20" />
            {{ t('tools.protocolConfig') }}
          </h3>

          <div class="form-group">
            <label for="protocol">{{ t('tools.protocol') }}</label>
            <select id="protocol" v-model="form.protocol" required class="form-select">
              <option value="stdio">stdio</option>
              <option value="sse">SSE</option>
              <option value="streamable_http">Streamable HTTP</option>
            </select>
          </div>

          <!-- stdio 协议配置 -->
          <div v-if="form.protocol === 'stdio'">
            <div class="form-group">
              <label for="command">{{ t('tools.command') }}</label>
              <input 
                id="command" 
                v-model="form.command" 
                type="text" 
                :placeholder="t('tools.enterCommand')"
                required 
                class="form-input" 
              />
            </div>

            <div class="form-group">
              <label for="args">{{ t('tools.arguments') }}</label>
              <input 
                id="args" 
                v-model="form.args" 
                type="text" 
                :placeholder="t('tools.enterArguments')"
                class="form-input" 
              />
            </div>
          </div>

          <!-- SSE 协议配置 -->
          <div v-if="form.protocol === 'sse'">
            <div class="form-group">
              <label for="sse_url">{{ t('tools.sseUrl') }}</label>
              <input 
                id="sse_url" 
                v-model="form.sse_url" 
                type="url" 
                :placeholder="t('tools.enterSseUrl')" 
                required
                class="form-input" 
              />
            </div>
          </div>

          <!-- Streamable HTTP 协议配置 -->
          <div v-if="form.protocol === 'streamable_http'">
            <div class="form-group">
              <label for="streamable_http_url">{{ t('tools.streamingHttpUrl') }}</label>
              <input 
                id="streamable_http_url" 
                v-model="form.streamable_http_url" 
                type="url"
                :placeholder="t('tools.enterStreamingHttpUrl')" 
                required 
                class="form-input" 
              />
            </div>
          </div>
        </div>

        <div class="tool-section">
          <h3>
            <Globe :size="20" />
            {{ t('tools.additionalInfo') }}
          </h3>

          <div class="form-group">
            <label for="description">{{ t('tools.description') }}</label>
            <textarea 
              id="description" 
              v-model="form.description" 
              :placeholder="t('tools.enterDescription')"
              rows="4" 
              class="form-textarea"
            ></textarea>
          </div>
        </div>

        <div class="form-actions">
          <button type="button" class="btn-secondary" @click="$emit('cancel')">
            {{ t('tools.cancel') }}
          </button>
          <button type="submit" class="btn-primary" :disabled="loading">
            <Loader2 v-if="loading" :size="16" class="animate-spin" />
            {{ loading ? t('tools.adding') : t('tools.add') }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { Database, Code, Globe, Loader2 } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'

// Props
const props = defineProps({
  loading: {
    type: Boolean,
    default: false
  }
})

// Emits
const emit = defineEmits(['submit', 'cancel'])

// Composables
const { t } = useLanguage()

// State
const form = reactive({
  name: '',
  protocol: 'sse',
  command: '',
  args: '',
  sse_url: '',
  streamable_http_url: '',
  description: ''
})

// Methods
const handleSubmit = () => {
  const payload = {
    name: form.name,
    protocol: form.protocol,
    description: form.description
  }

  // 根据协议类型添加相应字段
  if (form.protocol === 'stdio') {
    payload.command = form.command
    if (form.args) {
      payload.args = Array.isArray(form.args)
        ? form.args
        : form.args.split(' ').filter(arg => arg.trim())
    }
  } else if (form.protocol === 'sse') {
    payload.sse_url = form.sse_url
  } else if (form.protocol === 'streamable_http') {
    payload.streamable_http_url = form.streamable_http_url
  }

  emit('submit', payload)
}

// 重置表单的方法
const resetForm = () => {
  form.name = ''
  form.protocol = 'sse'
  form.command = ''
  form.args = ''
  form.sse_url = ''
  form.streamable_http_url = ''
  form.description = ''
}

// 暴露重置方法给父组件
defineExpose({
  resetForm
})
</script>

<style scoped>
.add-mcp-view {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  padding-bottom: 40px;
  overflow-y: auto;
  max-height: calc(100vh - 50px);
}

.tool-detail-content {
  width: 100%;
  max-width: 600px;
  margin: 0 auto;
}

.add-mcp-form {
  width: 100%;
  max-width: 800px;
  margin: 0 auto;
}

.tool-section {
  margin-bottom: 32px;
}

.tool-section h3 {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0 0 16px 0;
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  max-width: 500px;
  margin: 0 auto 16px;
}

.form-group label {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
  text-align: center;
}

.form-input,
.form-select,
.form-textarea {
  padding: 12px 16px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  color: #1f2937;
  background: #ffffff;
  transition: all 0.2s ease;
  text-align: center;
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
  min-height: 100px;
  text-align: left;
}

.form-actions {
  display: flex;
  gap: 16px;
  justify-content: center;
  margin: 32px auto 0;
  padding-top: 24px;
  border-top: 1px solid #e5e7eb;
}

.btn-secondary {
  padding: 12px 24px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
  color: #1f2937;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-secondary:hover {
  border-color: #667eea;
  color: #667eea;
}

.btn-primary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  border: none;
  border-radius: 8px;
  background: #667eea;
  color: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-primary:hover:not(:disabled) {
  background: #5a6fd8;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.animate-spin {
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