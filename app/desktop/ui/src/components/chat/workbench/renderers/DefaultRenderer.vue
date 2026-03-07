<template>
  <div class="default-renderer h-full flex flex-col overflow-hidden">
    <!-- 整合头部 -->
    <div class="flex items-center justify-between px-3 py-2.5 bg-muted/30 border-b border-border flex-none h-12">
      <div class="flex items-center gap-2 min-w-0">
        <span class="font-medium text-sm" :class="roleColor">{{ roleLabel }}</span>
        <span class="text-muted-foreground/50">|</span>
        <span class="text-sm text-muted-foreground">{{ formatTime(item?.timestamp) }}</span>
        <span class="text-muted-foreground/50">|</span>
        <span class="text-xl">📦</span>
        <span class="text-sm font-medium">数据</span>
        <Badge variant="secondary" class="text-xs">{{ item?.type || 'unknown' }}</Badge>
      </div>
    </div>

    <!-- 内容区域 -->
    <div class="flex-1 overflow-y-auto p-4">
      <pre class="bg-muted p-3 rounded-lg overflow-x-auto text-xs text-muted-foreground">{{ formattedData }}</pre>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'

const props = defineProps({
  item: {
    type: Object,
    required: true
  }
})

// 格式化数据
const formattedData = computed(() => {
  try {
    return JSON.stringify(props.item?.data, null, 2)
  } catch {
    return String(props.item?.data)
  }
})

// ItemHeader 相关信息
const roleLabel = computed(() => {
  const roleMap = {
    'assistant': 'AI',
    'user': '用户',
    'system': '系统',
    'tool': '工具'
  }
  return roleMap[props.item?.role] || 'AI'
})

const roleColor = computed(() => {
  const colorMap = {
    'assistant': 'text-primary',
    'user': 'text-muted-foreground',
    'system': 'text-orange-500',
    'tool': 'text-blue-500'
  }
  return colorMap[props.item?.role] || 'text-primary'
})

const formatTime = (timestamp) => {
  if (!timestamp) return ''

  let dateVal = timestamp
  const num = Number(timestamp)

  if (!isNaN(num)) {
    if (num < 10000000000) {
      dateVal = num * 1000
    } else {
      dateVal = num
    }
  }

  const date = new Date(dateVal)
  if (isNaN(date.getTime())) return ''

  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')

  return `${hours}:${minutes}:${seconds}`
}
</script>
