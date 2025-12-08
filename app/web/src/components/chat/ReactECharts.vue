<template>
  <div ref="chartRef" :style="chartStyle" class="echarts-container"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  option: {
    type: Object,
    required: true
  },
  style: {
    type: Object,
    default: () => ({ height: '400px', width: '100%' })
  },
  theme: {
    type: String,
    default: 'default'
  },
  notMerge: {
    type: Boolean,
    default: false
  },
  lazyUpdate: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['chartReady', 'chartClick', 'chartDoubleClick'])

const chartRef = ref(null)
let chartInstance = null

const chartStyle = computed(() => ({
  width: '100%',
  height: '400px',
  ...props.style
}))

// 初始化图表
const initChart = async () => {
  if (!chartRef.value) return
  
  try {
    // 销毁已存在的实例
    if (chartInstance) {
      chartInstance.dispose()
      chartInstance = null
    }
    
    // 创建新实例
    chartInstance = echarts.init(chartRef.value, props.theme)
    
    // 设置配置项
    chartInstance.setOption(props.option, props.notMerge, props.lazyUpdate)
    
    // 绑定事件
    chartInstance.on('click', (params) => {
      emit('chartClick', params)
    })
    
    chartInstance.on('dblclick', (params) => {
      emit('chartDoubleClick', params)
    })
    
    // 触发就绪事件
    emit('chartReady', chartInstance)
    
    // 监听窗口大小变化
    window.addEventListener('resize', handleResize)
  } catch (error) {
    console.error('ECharts初始化失败:', error)
  }
}

// 处理窗口大小变化
const handleResize = () => {
  if (chartInstance) {
    chartInstance.resize()
  }
}

// 更新图表配置
const updateChart = () => {
  if (chartInstance && props.option) {
    try {
      chartInstance.setOption(props.option, props.notMerge, props.lazyUpdate)
    } catch (error) {
      console.error('ECharts更新失败:', error)
    }
  }
}

// 监听配置变化
watch(
  () => props.option,
  () => {
    updateChart()
  },
  { deep: true }
)

// 监听主题变化
watch(
  () => props.theme,
  () => {
    initChart()
  }
)

onMounted(async () => {
  await nextTick()
  initChart()
})

onUnmounted(() => {
  if (chartInstance) {
    window.removeEventListener('resize', handleResize)
    chartInstance.dispose()
    chartInstance = null
  }
})

// 暴露方法给父组件
defineExpose({
  getChart: () => chartInstance,
  resize: () => {
    if (chartInstance) {
      chartInstance.resize()
    }
  },
  dispose: () => {
    if (chartInstance) {
      chartInstance.dispose()
      chartInstance = null
    }
  }
})
</script>

<style scoped>
.echarts-container {
  position: relative;
  overflow: hidden;
}
</style>