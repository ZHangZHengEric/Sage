<template>
  <div 
    class="resizable-panel relative mt-2 mr-2 mb-4 ml-0 flex h-full flex-col overflow-visible"
    :style="panelStyle"
  >
    <!-- 调整大小的拖拽条 -->
    <div 
      v-if="!isCompactViewport"
      class="resize-handle absolute inset-y-0 left-0 z-50 flex w-4 cursor-ew-resize items-center justify-start pl-0.5"
      :class="{ 'is-resizing': isResizing }"
      @mousedown="startResize"
    >
      <div class="h-[calc(100%-20px)] w-1.5 rounded-full bg-border/45 shadow-[0_0_0_1px_rgba(255,255,255,0.04)] transition-colors duration-150 hover:bg-border/80" />
    </div>

    <div class="panel-surface flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-background shadow-xl">
      <!-- 头部 -->
      <div class="flex items-center justify-between border-b border-border bg-muted/50 px-4 py-3 flex-none">
        <div class="flex items-center gap-2">
          <slot name="icon"></slot>
          <h3 class="font-semibold text-sm">{{ title }}</h3>
          <span v-if="badge" class="text-xs text-muted-foreground">({{ badge }})</span>
        </div>
        <Button 
          variant="ghost" 
          size="sm"
          @click="$emit('close')"
          class="h-8 w-8 p-0"
        >
          <X class="w-4 h-4" />
        </Button>
      </div>

      <!-- 内容区域 -->
      <div class="flex-1 overflow-hidden">
        <slot></slot>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { X } from 'lucide-vue-next'

const props = defineProps({
  title: {
    type: String,
    required: true
  },
  badge: {
    type: [String, Number],
    default: null
  },
  size: {
    type: String,
    default: 'medium',
    validator: (value) => ['large', 'medium'].includes(value)
  }
})

defineEmits(['close'])

const VIEWPORT_COMPACT_BREAKPOINT = 1280
const SIDEBAR_WIDTH = 170

// 获取右侧区域宽度（聊天区域）
const getRightAreaWidth = () => {
  const windowWidth = window.innerWidth
  return Math.max(windowWidth - SIDEBAR_WIDTH, windowWidth * 0.7)
}

const getCompactState = () => window.innerWidth <= VIEWPORT_COMPACT_BREAKPOINT

// 计算最大宽度（右侧区域的70%）
const getMaxWidth = (rightAreaWidth, compact) => {
  const ratio = compact ? 0.58 : 0.7
  return Math.max(Math.round(rightAreaWidth * ratio), compact ? 240 : 280)
}

// 根据窗口宽度计算默认宽度
const getDefaultWidth = (rightAreaWidth, compact) => {
  if (props.size === 'large') {
    return Math.round(rightAreaWidth * (compact ? 0.48 : 0.56))
  }
  return Math.round(rightAreaWidth * (compact ? 0.38 : 0.42))
}

// 面板宽度
const panelWidth = ref(400)
const minWidth = ref(280)
const maxWidth = ref(600)
const isCompactViewport = ref(false)

const panelStyle = computed(() => ({
  width: `${panelWidth.value}px`,
  minWidth: `${minWidth.value}px`
}))

const syncPanelMetrics = ({ resetWidth = false } = {}) => {
  const rightAreaWidth = getRightAreaWidth()
  const compact = getCompactState()
  const nextMinWidth = rightAreaWidth < 360 ? 240 : 280
  const nextMaxWidth = Math.max(getMaxWidth(rightAreaWidth, compact), nextMinWidth)
  const nextDefaultWidth = Math.min(
    Math.max(getDefaultWidth(rightAreaWidth, compact), nextMinWidth),
    nextMaxWidth
  )

  isCompactViewport.value = compact
  minWidth.value = nextMinWidth
  maxWidth.value = nextMaxWidth

  if (resetWidth) {
    panelWidth.value = nextDefaultWidth
    return
  }

  panelWidth.value = Math.min(Math.max(panelWidth.value, nextMinWidth), nextMaxWidth)
}

onMounted(() => {
  syncPanelMetrics({ resetWidth: true })
  window.addEventListener('resize', syncPanelMetrics)
})

onUnmounted(() => {
  window.removeEventListener('resize', syncPanelMetrics)
})

// 调整大小
const isResizing = ref(false)

const startResize = (e) => {
  e.preventDefault()
  isResizing.value = true
  const startX = e.clientX
  const startWidth = panelWidth.value
  const currentMaxWidth = maxWidth.value
  const currentMinWidth = minWidth.value
  const previousUserSelect = document.body.style.userSelect
  const previousCursor = document.body.style.cursor

  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'ew-resize'
  
  const handleMouseMove = (e) => {
    if (!isResizing.value) return
    const delta = startX - e.clientX
    const newWidth = Math.max(currentMinWidth, Math.min(currentMaxWidth, startWidth + delta))
    panelWidth.value = newWidth
  }
  
  const handleMouseUp = () => {
    isResizing.value = false
    document.body.style.userSelect = previousUserSelect
    document.body.style.cursor = previousCursor
    document.removeEventListener('mousemove', handleMouseMove)
    document.removeEventListener('mouseup', handleMouseUp)
  }
  
  document.addEventListener('mousemove', handleMouseMove)
  document.addEventListener('mouseup', handleMouseUp)
}
</script>

<style scoped>
.resizable-panel {
  animation: slideIn 0.2s ease;
}

.panel-surface {
  width: 100%;
  height: 100%;
}

.resize-handle.is-resizing > div {
  background: hsl(var(--border));
}

@keyframes slideIn {
  from {
    transform: translateX(100%);
    opacity: 0;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}
</style>
