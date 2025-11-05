<template>
  <div v-if="tokenUsage && tokenUsage.total_info" class="token-usage">
    <!-- 简洁的一行显示 -->
    <div class="token-usage-compact">
      <span class="token-usage-icon">📊</span>
      <span class="token-usage-summary">
        Token 使用: 输入 <span class="token-value input-tokens">{{ inputTokensFormatted }}</span>
        , 输出 <span class="token-value output-tokens">{{ outputTokensFormatted }}</span>
        , 总计 <span class="token-value total-tokens">{{ totalTokensFormatted }}</span>
      </span>
      <button
        v-if="hasStepInfo"
        class="toggle-details-btn-compact"
        @click="toggleDetails"
      >
        {{ showDetails ? '收起' : '更多' }}
      </button>
    </div>

    <!-- 展开的详细信息 -->
    <div v-if="showDetails" class="token-usage-details">
      <div class="token-usage-content">
        <div class="token-item">
          <span class="token-label">输入 Token:</span>
          <span class="token-value input-tokens">{{ inputTokensFormatted }}</span>
        </div>
        <div class="token-item">
          <span class="token-label">输出 Token:</span>
          <span class="token-value output-tokens">{{ outputTokensFormatted }}</span>
        </div>
        <div class="token-item total">
          <span class="token-label">总计:</span>
          <span class="token-value total-tokens">{{ totalTokensFormatted }}</span>
        </div>

        <!-- 显示分步骤详情 -->
        <div v-if="hasStepInfo" class="step-details">
          <div class="step-details-title">分步骤统计:</div>
          <div
            v-for="(stepInfo, index) in perStepInfo"
            :key="index"
            class="step-item"
          >
            <div class="step-name">{{ stepInfo.step_name }}:</div>
            <div class="step-tokens">
              <span class="step-token-item">
                输入: {{ formatTokens(stepInfo?.usage?.prompt_tokens) }}
              </span>
              <span class="step-token-item">
                输出: {{ formatTokens(stepInfo?.usage?.completion_tokens) }}
              </span>
              <span class="step-token-item total">
                小计: {{ formatTokens(stepInfo?.usage?.total_tokens) }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  tokenUsage: {
    type: Object,
    required: true
  }
})

const showDetails = ref(false)

const totalInfo = computed(() => props.tokenUsage?.total_info || {})
const perStepInfo = computed(() => props.tokenUsage?.per_step_info || [])

const inputTokens = computed(() => totalInfo.value?.prompt_tokens || 0)
const outputTokens = computed(() => totalInfo.value?.completion_tokens || 0)
const totalTokens = computed(() => totalInfo.value?.total_tokens || (inputTokens.value + outputTokens.value))

const formatTokens = (n) => Number(n || 0).toLocaleString()

const inputTokensFormatted = computed(() => formatTokens(inputTokens.value))
const outputTokensFormatted = computed(() => formatTokens(outputTokens.value))
const totalTokensFormatted = computed(() => formatTokens(totalTokens.value))

const hasStepInfo = computed(() => Array.isArray(perStepInfo.value) && perStepInfo.value.length > 0)

const toggleDetails = () => {
  showDetails.value = !showDetails.value
}
</script>

<style scoped>
.token-usage {
  margin: 4px 0;
  font-size: 10px;
  text-align: center;
}

/* 简洁的一行显示 */
.token-usage-compact {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 3px 6px;
  background: rgba(0, 123, 255, 0.05);
  border: 1px solid rgba(0, 123, 255, 0.1);
  border-radius: 4px;
  font-size: 9px;
  color: #495057;
}

.token-usage-icon {
  font-size: 10px;
}

.token-usage-summary {
  flex: 1;
  color: #6c757d;
  text-align: center;
}

.toggle-details-btn-compact {
  background: #007bff;
  color: white;
  border: none;
  border-radius: 3px;
  padding: 2px 4px;
  font-size: 8px;
  cursor: pointer;
  transition: background-color 0.2s;
  white-space: nowrap;
}

.toggle-details-btn-compact:hover {
  background: #0056b3;
}

/* 展开的详细信息 */
.token-usage-details {
  background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
  border: 1px solid #dee2e6;
  border-radius: 6px;
  padding: 8px 12px;
  margin-top: 6px;
  font-size: 11px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  text-align: center;
}

.token-usage-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.token-usage-title {
  font-weight: 600;
  color: #495057;
  font-size: 12px;
}

.toggle-details-btn {
  background: #007bff;
  color: white;
  border: none;
  border-radius: 4px;
  padding: 3px 6px;
  font-size: 9px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.toggle-details-btn:hover {
  background: #0056b3;
}

.token-usage-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.token-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 0;
}

.token-item.total {
  border-top: 1px solid #dee2e6;
  padding-top: 6px;
  margin-top: 4px;
  font-weight: 600;
}

.token-label {
  color: #6c757d;
  font-weight: 500;
}

.token-value {
  font-weight: 600;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
}

.input-tokens {
  color: #28a745;
}

.output-tokens {
  color: #007bff;
}

.total-tokens {
  color: #495057;
  font-size: 12px;
}

/* 分步骤详情样式 */
.step-details {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px solid #dee2e6;
}

.step-details-title {
  font-weight: 600;
  color: #495057;
  margin-bottom: 6px;
  font-size: 11px;
}

.step-item {
  margin-bottom: 6px;
  padding: 4px 6px;
  background: rgba(255, 255, 255, 0.5);
  border-radius: 4px;
  border-left: 3px solid #007bff;
}

.step-name {
  font-weight: 500;
  color: #495057;
  margin-bottom: 3px;
  font-size: 10px;
}

.step-tokens {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
}

.step-token-item {
  font-size: 9px;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  color: #6c757d;
}

.step-token-item.total {
  font-weight: 600;
  color: #495057;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .token-usage {
    padding: 10px 12px;
    font-size: 12px;
  }
  
  .token-usage-title {
    font-size: 13px;
  }
  
  .total-tokens {
    font-size: 13px;
  }
  
  .step-tokens {
    flex-direction: column;
    gap: 2px;
  }
  
  .toggle-details-btn {
    font-size: 10px;
    padding: 3px 6px;
  }
}
</style>