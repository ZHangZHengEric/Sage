<template>
  <div class="image-renderer h-full flex flex-col overflow-hidden">
    <!-- 整合头部 -->
    <div class="flex items-center justify-between px-3 py-2.5 bg-muted/30 border-b border-border flex-none h-12">
      <div class="flex items-center gap-2 min-w-0">
        <span class="font-medium text-sm" :class="roleColor">{{ roleLabel }}</span>
        <span class="text-muted-foreground/50">|</span>
        <span class="text-sm text-muted-foreground">{{ formatTime(item?.timestamp) }}</span>
        <span class="text-muted-foreground/50">|</span>
        <span class="text-xl">🖼️</span>
        <span class="text-sm font-medium truncate">{{ displayAlt }}</span>
        <Badge variant="secondary" class="text-xs">图片</Badge>
      </div>
    </div>

    <!-- 图片内容 -->
    <div class="flex-1 overflow-auto p-4 flex items-center justify-center bg-muted/10">
      <img
        :src="src"
        :alt="displayAlt"
        class="max-w-full max-h-full h-auto rounded-lg shadow-md cursor-pointer hover:shadow-lg transition-shadow"
        @click="isPreviewOpen = true"
      />
    </div>

    <!-- 图片预览对话框 -->
    <Dialog v-model:open="isPreviewOpen">
      <DialogContent class="max-w-[90vw] max-h-[90vh] p-0 bg-background/95">
        <img :src="src" :alt="displayAlt" class="w-full h-full object-contain" />
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent } from '@/components/ui/dialog'

const props = defineProps({
  item: {
    type: Object,
    required: true
  }
})

const isPreviewOpen = ref(false)

// 从 item 中提取图片信息
const src = computed(() => {
  return props.item.data?.src || props.item.data?.imageUrl || ''
})

const alt = computed(() => {
  return props.item.data?.alt || props.item.data?.name || ''
})

const displayAlt = computed(() => {
  return alt.value || '图片'
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
