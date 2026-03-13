<template>
  <div class="rounded-xl border border-border/70 bg-background/80 shadow-sm backdrop-blur-sm">
    <button
      type="button"
      class="w-full flex items-start justify-between px-4 py-3 gap-3"
      @click="toggleExpanded"
      :aria-expanded="expanded"
    >
      <div class="text-left">
        <div class="text-sm font-semibold text-foreground">Agent 行动统计</div>
        <button
          type="button"
          class="text-xs text-muted-foreground hover:text-foreground transition"
          @click.stop="cycleDays"
        >
          最近 {{ days }} 天
        </button>
      </div>
      <div class="flex items-center gap-2 text-xs text-muted-foreground">
        <span v-if="loading">加载中...</span>
        <span v-else-if="error">加载失败</span>
        <span v-else>{{ summaryText }}</span>
        <span class="text-muted-foreground/70">{{ expanded ? '收起' : '展开' }}</span>
      </div>
    </button>

    <div v-if="expanded" class="px-4 pb-4">
      <div v-if="loading" class="py-3 text-xs text-muted-foreground">正在获取统计数据...</div>
      <div v-else-if="error" class="py-3 text-xs text-destructive">统计数据获取失败，请稍后重试</div>
      <div v-else-if="items.length === 0" class="py-3 text-xs text-muted-foreground">暂无工具调用记录</div>
      <div v-else class="space-y-2">
        <div
          v-for="item in items"
          :key="item.key"
          class="flex items-center gap-3"
        >
          <div class="w-28 text-xs text-foreground/80 truncate">{{ item.label }}</div>
          <div class="flex-1">
            <div class="h-2 rounded-full bg-muted/60 overflow-hidden">
              <div
                class="h-2 rounded-full bg-foreground/70"
                :style="{ width: `${item.ratio}%` }"
              />
            </div>
          </div>
          <div class="w-10 text-right text-xs font-semibold text-foreground tabular-nums">
            {{ item.value }}
          </div>
        </div>
        <div class="pt-2 text-[11px] text-muted-foreground/80">统计来源：本地会话记录</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { systemAPI } from '@/api/system.js'

const props = defineProps({
  days: {
    type: Number,
    default: 7
  },
  topN: {
    type: Number,
    default: 5
  }
})

const emit = defineEmits(['update:days'])

const expanded = ref(true)
const loading = ref(false)
const error = ref(false)
const rawUsage = ref({})
const localDays = ref(props.days)
const dayOptions = [3, 7, 14, 30]

const labelMap = {
  todo_write: '任务写入',
  load_skill: '能力加载',
  execute_shell_command: '命令执行',
  execute_python_code: '脚本执行',
  file_write: '文件操作'
}

const loadStats = async () => {
  loading.value = true
  error.value = false
  try {
    const res = await systemAPI.getAgentUsageStats({ days: props.days })
    rawUsage.value = res?.usage || {}
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

const items = computed(() => {
  const entries = Object.entries(rawUsage.value || {})
    .filter(([, value]) => Number(value) > 0)
    .map(([key, value]) => ({
      key,
      label: labelMap[key] || key,
      value: Number(value)
    }))
    .sort((a, b) => b.value - a.value)

  const max = entries[0]?.value || 1
  const limited = entries.slice(0, Math.max(1, props.topN))
  return limited.map((item) => ({
    ...item,
    ratio: Math.max(8, Math.round((item.value / max) * 100))
  }))
})

const summaryText = computed(() => {
  if (items.value.length === 0) return '暂无记录'
  const top = items.value.slice(0, 2)
  return top.map((item) => `${item.label} ${item.value}`).join(' · ')
})

const toggleExpanded = () => {
  expanded.value = !expanded.value
}

const handleDaysChange = () => {
  emit('update:days', localDays.value)
}

const cycleDays = () => {
  const current = localDays.value
  const index = dayOptions.indexOf(current)
  const nextIndex = index === -1 ? 0 : (index + 1) % dayOptions.length
  localDays.value = dayOptions[nextIndex]
  handleDaysChange()
}

watch(
  () => props.days,
  (value) => {
    if (value === localDays.value) return
    localDays.value = value
    loadStats()
  }
)

onMounted(loadStats)
</script>
