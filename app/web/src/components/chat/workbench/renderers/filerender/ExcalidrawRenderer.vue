<template>
  <div class="excalidraw-container" :class="{ 'dark-theme': theme === 'dark' }" ref="containerRef">
    <!-- 悬浮工具栏 - 右上角 -->
    <div class="floating-toolbar">
      <button @click="zoomOut" class="tool-btn" title="缩小">−</button>
      <span class="zoom-text">{{ Math.round(scale * 100) }}%</span>
      <button @click="zoomIn" class="tool-btn" title="放大">+</button>
      <button @click="resetView" class="tool-btn" title="重置">⟲</button>
    </div>

    <!-- SVG 画布 -->
    <div
      class="canvas-wrapper"
      @mousedown="startDrag"
      @mousemove="onDrag"
      @mouseup="endDrag"
      @mouseleave="endDrag"
      @wheel="onWheel"
    >
      <div
        v-if="svgContent"
        class="svg-content"
        v-html="svgContent"
        :style="transformStyle"
      ></div>
      <div v-else class="loading">加载中...</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { exportToSvg } from '@excalidraw/excalidraw'

const props = defineProps({
  data: {
    type: Object,
    default: () => null
  },
  theme: {
    type: String,
    default: 'light'
  }
})

const containerRef = ref(null)
const svgContent = ref('')
const scale = ref(1)
const translateX = ref(0)
const translateY = ref(0)
const isDragging = ref(false)
const lastX = ref(0)
const lastY = ref(0)

const transformStyle = computed(() => ({
  transform: `translate(${translateX.value}px, ${translateY.value}px) scale(${scale.value})`,
  transformOrigin: 'center center'
}))

const renderSvg = async () => {
  if (!props.data || !props.data.elements) {
    svgContent.value = ''
    return
  }

  try {
    const elements = props.data.elements || []

    // 根据主题设置背景色
    const isDark = props.theme === 'dark'
    const bgColor = isDark ? '#1e1e1e' : '#ffffff'

    const svg = await exportToSvg({
      elements: elements,
      appState: {
        theme: props.theme,
        viewBackgroundColor: bgColor,
        exportBackground: true,
        exportWithDarkMode: isDark,
        exportScale: 1
      },
      files: props.data.files || {}
    })

    // 获取 SVG 字符串并注入背景色
    let svgString = svg.outerHTML

    // 确保 SVG 有正确的背景色
    if (svgString.includes('<svg')) {
      svgString = svgString.replace(
        /<svg([^>]*)>/,
        `<svg$1 style="background-color: ${bgColor};">`
      )
    }

    svgContent.value = svgString

    // 重置视图
    resetView()

    console.log('[ExcalidrawRenderer] SVG exported, length:', svgString.length)
  } catch (error) {
    console.error('[ExcalidrawRenderer] Export failed:', error)
    svgContent.value = ''
  }
}

// 缩放功能
const zoomIn = () => {
  scale.value = Math.min(scale.value * 1.2, 5)
}

const zoomOut = () => {
  scale.value = Math.max(scale.value / 1.2, 0.1)
}

const resetView = () => {
  scale.value = 1
  translateX.value = 0
  translateY.value = 0
}

// 鼠标滚轮缩放
const onWheel = (e) => {
  e.preventDefault()
  const delta = e.deltaY > 0 ? 0.9 : 1.1
  scale.value = Math.max(0.1, Math.min(5, scale.value * delta))
}

// 拖动功能
const startDrag = (e) => {
  isDragging.value = true
  lastX.value = e.clientX
  lastY.value = e.clientY
}

const onDrag = (e) => {
  if (!isDragging.value) return
  const dx = e.clientX - lastX.value
  const dy = e.clientY - lastY.value
  translateX.value += dx
  translateY.value += dy
  lastX.value = e.clientX
  lastY.value = e.clientY
}

const endDrag = () => {
  isDragging.value = false
}

onMounted(() => {
  renderSvg()
})

watch(() => props.data, () => {
  renderSvg()
}, { deep: true })

watch(() => props.theme, () => {
  renderSvg()
})
</script>

<style scoped>
.excalidraw-container {
  width: 100%;
  height: 100%;
  position: relative;
  background: #ffffff;
}

.excalidraw-container.dark-theme {
  background: #1e1e1e;
}

/* 悬浮工具栏 - 右上角 */
.floating-toolbar {
  position: absolute;
  top: 8px;
  right: 8px;
  left: auto;
  transform: none;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid #e0e0e0;
  border-radius: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  z-index: 100;
}

.dark-theme .floating-toolbar {
  background: rgba(45, 45, 45, 0.95);
  border-color: #555;
}

.tool-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: #333;
  border-radius: 14px;
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.dark-theme .tool-btn {
  color: #fff;
}

.tool-btn:hover {
  background: rgba(0, 0, 0, 0.1);
}

.dark-theme .tool-btn:hover {
  background: rgba(255, 255, 255, 0.1);
}

.zoom-text {
  font-size: 12px;
  color: #666;
  min-width: 40px;
  text-align: center;
  user-select: none;
}

.dark-theme .zoom-text {
  color: #ccc;
}

.canvas-wrapper {
  width: 100%;
  height: 100%;
  overflow: hidden;
  position: relative;
  cursor: grab;
}

.canvas-wrapper:active {
  cursor: grabbing;
}

.svg-content {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.1s ease-out;
}

.svg-content :deep(svg) {
  max-width: 95%;
  max-height: 95%;
  width: auto;
  height: auto;
}

.loading {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  color: #666;
  font-size: 14px;
}

.dark-theme .loading {
  color: #999;
}
</style>
