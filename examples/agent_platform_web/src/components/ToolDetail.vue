<template>
  <div class="tool-detail-view">
    <div class="detail-header">
      <div class="detail-tool-info">
        <div class="detail-tool-icon"
          :style="{ background: `linear-gradient(135deg, ${getToolTypeColor(tool.type)} 0%, ${getToolTypeColor(tool.type)}80 100%)` }">
          <component :is="getToolIcon(tool.type)" :size="24" />
        </div>
        <div class="detail-tool-meta">
          <h1>{{ tool.name }}</h1>
          <span class="detail-tool-type" :style="{ background: getToolTypeColor(tool.type) }">
            {{ getToolTypeLabel(tool.type) }}
          </span>
        </div>
      </div>
      <button class="back-button" @click="$emit('back')">
        <ArrowLeft :size="20" />
        {{ t('tools.backToList') }}
      </button>
    </div>

    <div class="tool-detail-content">
      <div class="tool-section">
        <h3>
          <Database :size="20" />
          {{ t('toolDetail.description') }}
        </h3>
        <p>{{ tool.description || t('tools.noDescription') }}</p>
      </div>

      <div class="tool-section">
        <h3>
          <Code :size="20" />
          {{ t('toolDetail.basicInfo') }}
        </h3>
        <div class="info-grid">
          <div class="info-item">
            <span class="info-label">{{ t('toolDetail.toolName') }}</span>
            <span class="info-value">{{ tool.name }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">{{ t('toolDetail.toolType') }}</span>
            <span class="info-value">{{ getToolTypeLabel(tool.type) }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">{{ t('toolDetail.source') }}</span>
            <span class="info-value">{{ getToolSourceLabel(tool.source) }}</span>
          </div>
        </div>
      </div>

      <div class="tool-section">
        <h3>
          <Wrench :size="20" />
          {{ t('toolDetail.parameterDetails') }}
        </h3>
        <div v-if="formattedParams.length > 0" class="params-table-container">
          <table class="params-table">
            <thead>
              <tr>
                <th>{{ t('toolDetail.paramName') }}</th>
                <th>{{ t('toolDetail.paramType') }}</th>
                <th>{{ t('toolDetail.required') }}</th>
                <th>{{ t('toolDetail.paramDescription') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(param, index) in formattedParams" :key="index">
                <td class="param-name">{{ param.name }}</td>
                <td class="param-type">{{ param.type }}</td>
                <td class="param-required">
                  <span :class="param.required ? 'required-yes' : 'required-no'">
                    {{ param.required ? t('toolDetail.yes') : t('toolDetail.no') }}
                  </span>
                </td>
                <td class="param-description">{{ param.description }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="no-parameters">{{ t('toolDetail.noParameters') }}</p>
      </div>

      <div class="tool-section">
        <h3>
          <Globe :size="20" />
          {{ t('toolDetail.rawConfig') }}
        </h3>
        <pre class="config-display">{{ JSON.stringify(tool.parameters, null, 2) }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ArrowLeft, Database, Code, Wrench, Globe, Cpu } from 'lucide-vue-next'
import { useLanguage } from '../utils/language'

// Props
const props = defineProps({
  tool: {
    type: Object,
    required: true
  }
})

// Emits
defineEmits(['back'])

// Composables
const { t } = useLanguage()

// Computed
const formattedParams = computed(() => {
  if (!props.tool || !props.tool.parameters) {
    return []
  }
  return formatParameters(props.tool.parameters)
})

// Methods
const getToolTypeLabel = (type) => {
  const typeKey = `tools.type.${type}`
  return t(typeKey) !== typeKey ? t(typeKey) : type
}

const getToolSourceLabel = (source) => {
  // 直接映射中文source到翻译key
  const sourceMapping = {
    '基础工具': 'tools.source.basic',
    '内置工具': 'tools.source.builtin',
    '系统工具': 'tools.source.system'
  }

  const translationKey = sourceMapping[source]
  return translationKey ? t(translationKey) : source
}

const getToolIcon = (type) => {
  switch (type) {
    case 'basic':
      return Code
    case 'mcp':
      return Database
    case 'agent':
      return Cpu
    default:
      return Wrench
  }
}

const getToolTypeColor = (type) => {
  switch (type) {
    case 'basic':
      return '#4facfe'
    case 'mcp':
      return '#667eea'
    case 'agent':
      return '#ff6b6b'
    default:
      return '#4ade80'
  }
}

const formatParameters = (parameters) => {
  if (!parameters || typeof parameters !== 'object') {
    return []
  }

  return Object.entries(parameters).map(([key, value]) => {
    return {
      name: key,
      type: value.type || 'unknown',
      description: value.description || t('tools.noDescription'),
      required: value.required || false
    }
  })
}
</script>

<style scoped>
.tool-detail-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24px 0;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 24px;
}

.detail-tool-info {
  display: flex;
  align-items: center;
  gap: 16px;
}

.detail-tool-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.detail-tool-meta h1 {
  margin: 0 0 8px 0;
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.detail-tool-type {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
  color: white;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.back-button {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.back-button:hover {
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.tool-detail-content {
  flex: 1;
  overflow-y: auto;
  padding-right: 8px;
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
  color: var(--text-primary);
}

.tool-section p {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.6;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 16px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.info-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.info-value {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.no-parameters {
  color: var(--text-secondary);
  font-style: italic;
  text-align: center;
  padding: 32px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.params-table-container {
  overflow-x: auto;
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.params-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--bg-primary);
}

.params-table th {
  background: var(--bg-secondary);
  padding: 12px 16px;
  text-align: left;
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-color);
}

.params-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  font-size: 14px;
  vertical-align: top;
}

.params-table tbody tr:last-child td {
  border-bottom: none;
}

.params-table tbody tr:hover {
  background: var(--bg-hover);
}

.params-table .param-name {
  font-family: monospace;
  font-weight: 600;
  color: var(--text-primary);
}

.params-table .param-type {
  color: var(--text-secondary);
  line-height: 1.5;
  max-width: 300px;
  word-wrap: break-word;
}

.params-table .param-required .required-yes {
  color: #e74c3c;
  font-weight: 600;
}

.params-table .param-required .required-no {
  color: var(--text-secondary);
}

.params-table .param-description {
  color: var(--text-secondary);
  line-height: 1.5;
  max-width: 300px;
  word-wrap: break-word;
}

.config-display {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 16px;
  font-family: monospace;
  font-size: 12px;
  color: var(--text-primary);
  white-space: pre-wrap;
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
}
</style>