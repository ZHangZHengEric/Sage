<template>
  <div v-if="tokenUsage && tokenUsage.total_info" class="my-1 text-[10px] text-center">
    <!-- 简洁的一行显示 -->
    <div class="flex items-center justify-center gap-2 text-muted-foreground">
      <span class="text-xs">📊</span>
      <span>
        Token 使用: 输入 <span class="font-mono font-medium">{{ inputTokensFormatted }}</span>
        , 输出 <span class="font-mono font-medium">{{ outputTokensFormatted }}</span>
        , 总计 <span class="font-mono font-medium">{{ totalTokensFormatted }}</span>
      </span>
      <button
        v-if="hasStepInfo"
        class="text-primary hover:text-primary/80 transition-colors focus:outline-none hover:underline"
        @click="toggleDetails"
      >
        {{ showDetails ? '收起' : '更多' }}
      </button>
    </div>

    <!-- 展开的详细信息 -->
    <div v-if="showDetails" class="mt-2 rounded-md bg-muted/50 p-3 text-left animate-in fade-in slide-in-from-top-1 duration-200">
      <div class="space-y-1">
        <div class="flex justify-between">
          <span class="text-muted-foreground">输入 Token:</span>
          <span class="font-mono">{{ inputTokensFormatted }}</span>
        </div>
        <div class="flex justify-between">
          <span class="text-muted-foreground">输出 Token:</span>
          <span class="font-mono">{{ outputTokensFormatted }}</span>
        </div>
        <div class="flex justify-between font-medium border-t pt-1 mt-1 border-border/50">
          <span>总计:</span>
          <span class="font-mono">{{ totalTokensFormatted }}</span>
        </div>

        <!-- 显示分步骤详情 -->
        <div v-if="hasStepInfo" class="mt-3 pt-2 border-t border-border/50">
          <div class="mb-2 font-medium text-muted-foreground">分步骤统计:</div>
          <div
            v-for="(stepInfo, index) in perStepInfo"
            :key="index"
            class="mb-3 last:mb-0"
          >
            <div class="mb-1 font-medium text-foreground">{{ stepInfo.step_name }}:</div>
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-2 pl-2 text-muted-foreground bg-background/50 rounded p-2">
              <span class="flex justify-between sm:block">
                <span class="mr-2">输入:</span>
                <span class="font-mono">{{ formatTokens(stepInfo?.usage?.prompt_tokens) }}</span>
              </span>
              <span class="flex justify-between sm:block">
                <span class="mr-2">输出:</span>
                <span class="font-mono">{{ formatTokens(stepInfo?.usage?.completion_tokens) }}</span>
              </span>
              <span class="flex justify-between sm:block font-medium text-foreground">
                <span class="mr-2">小计:</span>
                <span class="font-mono">{{ formatTokens(stepInfo?.usage?.total_tokens) }}</span>
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
