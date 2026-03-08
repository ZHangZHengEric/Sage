<template>
  <div 
    class="resizable-panel h-full bg-background border border-border flex flex-col relative rounded-2xl overflow-hidden shadow-xl m-2 mb-4"
    :style="{ 
      width: panelWidth + 'px',
      minWidth: panelWidth + 'px'
    }"
  >
    <!-- 调整大小的拖拽条 -->
    <div 
      class="resize-handle absolute left-0 top-0 w-2 h-full cursor-ew-resize hover:bg-primary/50 transition-colors z-50 rounded-l-2xl"
      @mousedown="startResize"
    ></div>
    
    <!-- 头部 -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/50 flex-none">
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
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
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

// 获取右侧区域宽度（聊天区域）
const getRightAreaWidth = () => {
  // 右侧区域是 flex-1，占父容器剩余空间
  // 父容器是窗口减去左侧 sidebar（约 240px）
  const windowWidth = window.innerWidth
  const sidebarWidth = 240 // 左侧 sidebar 宽度
  return Math.max(windowWidth - sidebarWidth, windowWidth * 0.7)
}

// 计算最大宽度（右侧区域的70%）
const getMaxWidth = () => {
  const rightAreaWidth = getRightAreaWidth()
  return Math.round(rightAreaWidth * 0.7) // 最大占右侧区域的70%
}

// 根据窗口宽度计算默认宽度
const getDefaultWidth = () => {
  const rightAreaWidth = getRightAreaWidth()
  if (props.size === 'large') {
    return Math.round(rightAreaWidth * 0.6) // 60% 右侧区域
  }
  return Math.round(rightAreaWidth * 0.4) // 40% 右侧区域
}

// 面板宽度
const panelWidth = ref(400)
const minWidth = 280
const maxWidth = ref(600)

onMounted(() => {
  maxWidth.value = getMaxWidth()
  panelWidth.value = Math.min(getDefaultWidth(), maxWidth.value)
})

// 调整大小
const isResizing = ref(false)

const startResize = (e) => {
  isResizing.value = true
  const startX = e.clientX
  const startWidth = panelWidth.value
  const currentMaxWidth = getMaxWidth()
  
  const handleMouseMove = (e) => {
    if (!isResizing.value) return
    const delta = startX - e.clientX
    const newWidth = Math.max(minWidth, Math.min(currentMaxWidth, startWidth + delta))
    panelWidth.value = newWidth
  }
  
  const handleMouseUp = () => {
    isResizing.value = false
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
