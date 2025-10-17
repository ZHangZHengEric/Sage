<template>
  <div class="config-panel">
  
    <div class="config-content">

      <!-- 深度思考 -->
      <div class="config-section">
        <ThreeOptionSwitch
          :value="config.deepThinking"
          @change="(value) => handleConfigChange({ deepThinking: value })"
          :label="t('config.deepThinking')"
          :description="t('config.deepThinkingDesc')"
        />
      </div>

      <!-- 多智能体协作 -->
      <div class="config-section">
        <ThreeOptionSwitch
          :value="config.multiAgent"
          @change="(value) => handleConfigChange({ multiAgent: value })"
          :label="t('config.multiAgent')"
          :description="t('config.multiAgentDesc')"
        />
      </div>

      <!-- 更多建议 -->
      <div class="config-section">
        <label class="config-checkbox">
          <input
            type="checkbox"
            :checked="config.moreSuggest"
            @change="handleConfigToggle('moreSuggest')"
          />
          <span class="checkmark"></span>
          {{ t('config.moreSuggest') }}
        </label>
        <small class="config-description">
          {{ t('config.moreSuggestDesc') }}
        </small>
      </div>

      <!-- 最大循环次数 -->
      <div class="config-section">
        <label class="config-label">{{ t('config.maxLoopCount') }}</label>
        <input
          type="number"
          min="1"
          max="50"
          :value="config.maxLoopCount"
          @input="handleMaxLoopCountChange"
          class="config-input"
        />
        <small class="config-description">
          {{ t('config.maxLoopCountDesc') }}
        </small>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useLanguage } from '../../utils/language.js'
import ThreeOptionSwitch from './ThreeOptionSwitch.vue'

// Props
const props = defineProps({
  config: {
    type: Object,
    required: true
  },
  agents: {
    type: Array,
    default: () => []
  },
  selectedAgent: {
    type: Object,
    default: null
  }
})

// Emits
const emit = defineEmits(['configChange', 'agentSelect'])

// Composables
const { t } = useLanguage()

// Methods
const handleConfigChange = (changes) => {
  emit('configChange', changes)
}

const handleConfigToggle = (key) => {
  const newValue = !props.config[key]
  console.log(`配置开关变更: ${key} = ${newValue}`)
  handleConfigChange({ [key]: newValue })
}

const handleMaxLoopCountChange = (e) => {
  const value = parseInt(e.target.value, 10)
  if (!isNaN(value) && value > 0) {
    handleConfigChange({ maxLoopCount: value })
  }
}

const handleAgentChange = (e) => {
  const agent = props.agents.find(a => a.id === e.target.value)
  emit('agentSelect', agent)
}
</script>

<style scoped>
/* ConfigPanel 组件样式 */
.config-panel {
  width: 35%;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 0;
  padding: 20px 24px;
  backdrop-filter: blur(10px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-left: 1px solid rgba(255, 255, 255, 0.1);
  border-top: none;
  border-right: none;
  border-bottom: none;
}

.panel-header {
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.panel-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.9);
}

.config-content {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.config-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.config-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
  font-weight: 500;
  margin-bottom: 2px;
}

.config-checkbox {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.8);
  user-select: none;
}

.config-checkbox input[type="checkbox"] {
  appearance: none;
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-radius: 3px;
  background: transparent;
  cursor: pointer;
  position: relative;
  transition: all 0.2s;
}

.config-checkbox input[type="checkbox"]:checked {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-color: #667eea;
}

.config-checkbox input[type="checkbox"]:checked::after {
  content: '✓';
  position: absolute;
  top: -2px;
  left: 1px;
  color: white;
  font-size: 12px;
  font-weight: bold;
}

.checkmark {
  /* 保留原有的checkmark样式兼容性 */
}

.agent-select {
  min-width: 120px;
  padding: 6px 8px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  color: rgba(255, 255, 255, 0.9);
  font-size: 12px;
  backdrop-filter: blur(10px);
  transition: all 0.2s;
}

.agent-select:focus {
  outline: none;
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.2);
}

.agent-select option {
  background: #2a2a2a;
  color: rgba(255, 255, 255, 0.9);
}

.config-input {
  padding: 6px 8px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  color: rgba(255, 255, 255, 0.9);
  font-size: 12px;
  backdrop-filter: blur(10px);
  transition: all 0.2s;
  width: 60px;
}

.config-input:focus {
  outline: none;
  border-color: #667eea;
  box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.2);
}

.config-description {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
  margin-top: 2px;
  line-height: 1.3;
}


</style>