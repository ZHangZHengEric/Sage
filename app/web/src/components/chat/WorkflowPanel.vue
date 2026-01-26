<template>
  <div class="workflow-drawer">
    <div class="drawer-header">
      <h3>工作流追踪</h3>
      <div class="header-right">
        <button class="action-btn" @click="openTraceDetails">🔍 查看详情</button>
        <button class="close-btn" @click="$emit('close')">×</button>
      </div>
    </div>

    <div class="drawer-content" ref="containerRef">
      <div v-if="loading" class="loading">Loading trace data...</div>
      <div v-else-if="error" class="error">{{ error }}</div>
      <div v-else-if="!treeData" class="no-data">No trace data</div>

      <ReactECharts 
        v-else 
        :option="chartOption" 
        :style="chartStyle" 
        @chartReady="onChartReady"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, watch, computed, nextTick } from 'vue'
import ReactECharts from './ReactECharts.vue'
import { traceApi } from '@/api/trace'

const props = defineProps({
  sessionId: { type: String, required: true }
})

defineEmits(['close'])

const loading = ref(false)
const error = ref(null)
const traces = ref([])

/* ---------------- tree data ---------------- */

const treeData = computed(() => {
  if (!Array.isArray(traces.value) || traces.value.length === 0) return null

  const spanMap = {}

  // 1. build nodes
  traces.value.forEach(span => {
    if (!span?.span_id) return

    const isError = span.status_code === 'ERROR'
    const isServer = span.kind === 'SERVER' || span.kind === 'SpanKind.SERVER'

    spanMap[span.span_id] = {
      name: span.name || 'Unknown',
      value: span.duration_ms || 0,
      status: span.status_code,
      startTime: span.start_time,
      children: [],

      symbol: 'roundRect',
      symbolSize: [180, 64],

      itemStyle: {
        color: isError ? '#F56C6C' : isServer ? '#409EFF' : '#67C23A'
      },

      label: {
        show: true,
        position: 'inside',
        align: 'center',
        verticalAlign: 'middle',
        formatter: ({ name, data }) => {
          const status = data.status === 'ERROR' ? '❌ ERROR' : '✔ OK'
          const cost = `${data.value?.toFixed(1) || 0} ms`
          
          // Truncate name if too long (approx 20 chars for 180px width)
          const maxLength = 20
          const displayName = name.length > maxLength ? name.slice(0, maxLength) + '...' : name
          
          return `{t|${displayName}}\n{s|${status}}\n{d|${cost}}`
        },
        rich: {
          t: { fontSize: 12, fontWeight: 600, color: '#fff', lineHeight: 18 },
          s: { fontSize: 11, color: '#fff', lineHeight: 16 },
          d: { fontSize: 10, color: '#eee', lineHeight: 14 }
        }
      }
    }
  })

  // 2. link hierarchy
  const roots = []
  traces.value.forEach(span => {
    if (!span?.span_id) return
    const node = spanMap[span.span_id]

    if (span.parent_span_id && spanMap[span.parent_span_id]) {
      spanMap[span.parent_span_id].children.push(node)
    } else {
      roots.push(node)
    }
  })

  if (roots.length === 1) return roots[0]

  return {
    name: '会话',
    symbol: 'roundRect',
    symbolSize: [160, 50],
    itemStyle: { color: '#909399' },
    label: {
      show: true,
      position: 'inside',
      color: '#fff',
      fontWeight: 600
    },
    children: roots
  }
})

/* ---------------- chart dimension ---------------- */

const chartStyle = computed(() => {
  if (!treeData.value) return { width: '100%', height: '100%' }

  let maxDepth = 0
  let maxBreadth = 0
  
  // traverse to find depth and breadth
  const traverse = (node, depth) => {
    maxDepth = Math.max(maxDepth, depth)
    if (!node.children || node.children.length === 0) {
      maxBreadth += 1
    } else {
      node.children.forEach(child => traverse(child, depth + 1))
    }
  }

  traverse(treeData.value, 1)

  // LR layout: depth -> width, breadth -> height
  const width = Math.max(600, maxDepth * 300) // 300px per level
  const height = Math.max(600, maxBreadth * 150) // 150px per leaf

  return {
    width: `${width}px`,
    height: `${height}px`
  }
})

/* ---------------- chart option ---------------- */

const chartOption = computed(() => ({
  tooltip: {
    trigger: 'item',
    formatter: p => {
      const d = p.data
      return `
        <b>${d.name}</b><br/>
        Status: ${d.status || 'OK'}<br/>
        Duration: ${d.value?.toFixed(2) || 0} ms<br/>
        Start: ${d.startTime || '-'}
      `
    }
  },
  series: [
    {
      type: 'tree',
      data: [treeData.value],

      orient: 'LR',                // ⭐ 横向布局
      top: '50px',
      left: '50px',
      bottom: '50px',
      right: '50px',

      roam: true,
      expandAndCollapse: true,
      initialTreeDepth: 6,

      // edgeLength: node => 120 + node.depth * 30, // ⭐ 拉开父子 (Tree series usually ignores this, relying on layout size)
      nodePadding: 80,                           // ⭐ 拉开同级

      emphasis: { focus: 'descendant' },

      lineStyle: {
        color: '#ccc',
        width: 1.5,
        curveness: 0.3
      },

      animationDuration: 500,
      animationDurationUpdate: 700
    }
  ]
}))

/* ---------------- data fetch ---------------- */

const fetchTraces = async () => {
  if (!props.sessionId) return
  loading.value = true
  error.value = null
  try {
    traces.value = await traceApi.getSessionTraces(props.sessionId)
  } catch (e) {
    error.value = e?.message || 'Load failed'
  } finally {
    loading.value = false
  }
}

watch(() => props.sessionId, fetchTraces, { immediate: true })

/* ---------------- jaeger jump ---------------- */

const openTraceDetails = () => {
  const baseUrl = import.meta.env.VITE_SAGE_TRACE_JAEGER_URL
  if (!baseUrl || !traces.value.length) return
  const traceId = traces.value[0]?.trace_id
  if (traceId) window.open(`${baseUrl}/trace/${traceId}`, '_blank')
}

/* ---------------- scroll control ---------------- */

const containerRef = ref(null)

const centerView = () => {
  nextTick(() => {
    if (!containerRef.value) return
    const { scrollHeight, clientHeight } = containerRef.value
    // Vertical center
    if (scrollHeight > clientHeight) {
      containerRef.value.scrollTop = (scrollHeight - clientHeight) / 2
    }
    // Horizontal start (left)
    containerRef.value.scrollLeft = 0
  })
}

const onChartReady = () => {
  centerView()
}

watch(treeData, () => {
  centerView()
})
</script>

<style scoped>
.workflow-drawer {
  position: absolute;
  top: 0;
  right: 0;
  width: 600px;
  height: 100%;
  background: #fff;
  box-shadow: -2px 0 8px rgba(0, 0, 0, .15);
  display: flex;
  flex-direction: column;
}

.drawer-header {
  padding: 14px 18px;
  border-bottom: 1px solid #eee;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-right {
  display: flex;
  gap: 12px;
}

.action-btn {
  padding: 6px 12px;
  border: 1px solid #dcdfe6;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
}

.close-btn {
  font-size: 22px;
  border: none;
  background: none;
  cursor: pointer;
}

.drawer-content {
  flex: 1;
  overflow: auto;
}

.loading,
.error,
.no-data {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.error {
  color: #f56c6c;
}
</style>
