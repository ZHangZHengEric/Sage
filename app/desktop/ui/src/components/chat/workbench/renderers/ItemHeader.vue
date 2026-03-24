<template>
  <div class="flex items-center justify-between px-4 py-3 bg-muted/30 border-b border-border flex-none">
    <div class="flex items-center gap-2">
      <span class="font-medium text-sm" :class="roleColor">{{ roleLabel }}</span>
      <span class="text-muted-foreground/50">|</span>
      <span class="text-sm text-muted-foreground">{{ formatTime(item.timestamp) }}</span>
      <span v-if="item.type" class="text-muted-foreground/50">|</span>
      <Badge v-if="item.type" variant="secondary" class="text-xs capitalize">
        {{ item.type }}
      </Badge>
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

const roleLabel = computed(() => {
  const roleMap = {
    'assistant': 'AI',
    'user': '用户',
    'system': '系统',
    'tool': '工具'
  }
  return roleMap[props.item.role] || props.item.role
})

const roleColor = computed(() => {
  const colorMap = {
    'assistant': 'text-primary',
    'user': 'text-muted-foreground',
    'system': 'text-orange-500',
    'tool': 'text-blue-500'
  }
  return colorMap[props.item.role] || 'text-muted-foreground'
})

const formatTime = (timestamp) => {
  if (!timestamp) return ''

  let dateVal = timestamp
  const num = Number(timestamp)

  // 如果是数字且看起来像秒级时间戳（小于100亿，对应年份2286年之前）
  // Python后端常返回秒级浮点数时间戳，如 1769963248.061118
  if (!isNaN(num)) {
    if (num < 10000000000) {
      dateVal = num * 1000
    } else {
      dateVal = num
    }
  }

  const date = new Date(dateVal)
  // 检查日期是否有效
  if (isNaN(date.getTime())) return ''

  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')

  return `${hours}:${minutes}:${seconds}`
}
</script>
