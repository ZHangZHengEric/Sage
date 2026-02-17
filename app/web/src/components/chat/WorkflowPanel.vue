<template>
  <div class="absolute top-0 right-0 w-[600px] h-full bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 border-l border-border shadow-2xl z-50 flex flex-col animate-in slide-in-from-right duration-300">
    <div class="flex items-center justify-between px-6 py-4 border-b border-border/60 bg-muted/5">
      <div class="flex items-center gap-3">
         <div class="p-2 rounded-lg bg-primary/10 text-primary">
            <Activity class="w-4 h-4" />
         </div>
         <div>
            <h3 class="text-base font-semibold leading-none tracking-tight">工作流追踪</h3>
            <p class="text-xs text-muted-foreground mt-1">可视化执行链路与耗时分析</p>
         </div>
      </div>
      <div class="flex items-center gap-2">
        <Button 
          variant="outline" 
          size="sm" 
          class="h-8 gap-2 text-xs font-medium hover:bg-primary/5 hover:text-primary transition-colors" 
          @click="openTraceDetails"
        >
          <Search class="w-3.5 h-3.5" />
          Jaeger 详情
        </Button>
        <Separator orientation="vertical" class="h-6 mx-1" />
        <Button 
          variant="ghost" 
          size="icon" 
          class="h-8 w-8 rounded-full hover:bg-destructive/10 hover:text-destructive transition-colors" 
          @click="$emit('close')"
        >
          <X class="w-4 h-4" />
        </Button>
      </div>
    </div>

    <div class="flex-1 overflow-hidden relative bg-muted/5" ref="containerRef">
      <!-- Loading State -->
      <div v-if="loading" class="flex flex-col items-center justify-center h-full space-y-4">
        <div class="relative w-12 h-12">
           <div class="absolute inset-0 rounded-full border-4 border-muted-foreground/20"></div>
           <div class="absolute inset-0 rounded-full border-4 border-primary border-t-transparent animate-spin"></div>
        </div>
        <p class="text-sm text-muted-foreground animate-pulse">正在加载链路数据...</p>
      </div>

      <!-- Error State -->
      <div v-else-if="error" class="flex flex-col items-center justify-center h-full text-destructive p-6 text-center space-y-2">
        <AlertCircle class="w-10 h-10 mb-2 opacity-80" />
        <p class="font-medium">加载失败</p>
        <p class="text-sm text-muted-foreground/80 max-w-xs">{{ error }}</p>
      </div>

      <!-- Empty State -->
      <div v-else-if="!treeData" class="flex flex-col items-center justify-center h-full text-muted-foreground space-y-3">
        <div class="w-16 h-16 rounded-2xl bg-muted/50 flex items-center justify-center mb-2">
           <Activity class="w-8 h-8 opacity-40" />
        </div>
        <p class="text-sm">暂无追踪数据</p>
      </div>

      <!-- Chart -->
      <EChartsRenderer 
        v-else 
        :option="chartOption" 
        :style="chartStyle" 
        @chartReady="onChartReady"
        class="w-full h-full"
      />
      
      <!-- Legend/Info Overlay -->
      <div v-if="treeData" class="absolute bottom-4 left-4 bg-background/80 backdrop-blur border border-border/50 p-2 rounded-lg shadow-sm text-[10px] text-muted-foreground flex flex-col gap-1.5 z-10 pointer-events-none">
         <div class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-[#10b981]"></span>
            <span>成功 (OK)</span>
         </div>
         <div class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-[#3b82f6]"></span>
            <span>服务端 (Server)</span>
         </div>
         <div class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-[#ef4444]"></span>
            <span>错误 (Error)</span>
         </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, computed, nextTick } from 'vue'
import { useThemeStore } from '@/stores/theme'
import EChartsRenderer from './EChartsRenderer.vue'
import { traceApi } from '@/api/trace'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { X, Search, Activity, AlertCircle } from 'lucide-vue-next'

const props = defineProps({
  sessionId: { type: String, required: true }
})

defineEmits(['close'])

const themeStore = useThemeStore()
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
    
    // Determine colors based on status
    const color = isError ? '#ef4444' : isServer ? '#3b82f6' : '#10b981'
    const borderColor = isError ? '#b91c1c' : isServer ? '#1d4ed8' : '#059669'
    const bgColor = isError ? '#fef2f2' : isServer ? '#eff6ff' : '#ecfdf5'

    spanMap[span.span_id] = {
      name: span.name || 'Unknown',
      value: span.duration_ms || 0,
      status: span.status_code,
      startTime: span.start_time,
      attributes: span.attributes || {},
      children: [],

      symbol: 'roundRect',
      symbolSize: [240, 70],
      
      // Node styling
      itemStyle: {
        color: themeStore.isDark ? '#1e293b' : '#ffffff',
        borderColor: color,
        borderWidth: 1,
        shadowBlur: 8,
        shadowColor: themeStore.isDark ? 'rgba(0,0,0,0.2)' : 'rgba(0,0,0,0.04)',
        shadowOffsetY: 3,
        borderRadius: 8
      },

      label: {
        show: true,
        position: 'inside',
        align: 'center',
        verticalAlign: 'middle',
        formatter: ({ name, data }) => {
          const statusIcon = data.status === 'ERROR' ? '❌' : ''
          const cost = `${data.value?.toFixed(1) || 0} ms`
          
          // Truncate name
          const maxLength = 18
          const displayName = name.length > maxLength ? name.slice(0, maxLength) + '...' : name
          
          return `{t|${displayName}}\n{d|${cost}}  {s|${statusIcon}}`
        },
        rich: {
          t: { 
            fontSize: 13, 
            fontWeight: 600, 
            color: themeStore.isDark ? '#f1f5f9' : '#0f172a', // slate-100 : slate-900
            lineHeight: 20,
            fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
          },
          d: { 
            fontSize: 11, 
            color: themeStore.isDark ? '#94a3b8' : '#64748b', // slate-400 : slate-500
            lineHeight: 16,
            padding: [4, 0, 0, 0],
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace'
          },
          s: {
            fontSize: 11,
            lineHeight: 16
          }
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

  if (roots.length === 0) return null
  
  // Create a root container node if multiple roots
  if (roots.length === 1) return roots[0]

  return {
    name: 'Session Root',
    symbol: 'roundRect',
    symbolSize: [160, 40],
    itemStyle: { 
        color: themeStore.isDark ? '#0f172a' : '#f8fafc', 
        borderColor: themeStore.isDark ? '#334155' : '#cbd5e1', 
        borderWidth: 1,
        shadowBlur: 2,
        shadowColor: 'rgba(0,0,0,0.05)'
    },
    label: {
      show: true,
      position: 'inside',
      color: themeStore.isDark ? '#94a3b8' : '#475569',
      fontWeight: 600,
      formatter: 'Session Root'
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
  const width = Math.max(600, maxDepth * 280) // Reduced spacing
  const height = Math.max(600, maxBreadth * 100) // Compact height

  return {
    width: `${width}px`,
    height: `${height}px`
  }
})

/* ---------------- chart option ---------------- */

const chartOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: {
    trigger: 'item',
    backgroundColor: themeStore.isDark ? 'rgba(15, 23, 42, 0.95)' : 'rgba(255, 255, 255, 0.95)',
    borderColor: themeStore.isDark ? '#334155' : '#e2e8f0',
    borderWidth: 1,
    padding: [12, 16],
    textStyle: {
      color: themeStore.isDark ? '#f1f5f9' : '#0f172a'
    },
    extraCssText: 'box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06); border-radius: 8px;',
    formatter: p => {
      const d = p.data
      const statusColor = d.status === 'ERROR' ? 'text-red-500' : 'text-green-500'
      const statusText = d.status || 'OK'
      const labelColor = themeStore.isDark ? 'text-slate-400' : 'text-slate-500'
      const labelColorDark = themeStore.isDark ? 'text-slate-300' : 'text-slate-600'
      
      return `
        <div class="font-sans">
          <div class="font-semibold text-sm mb-1">${d.name}</div>
          <div class="text-xs ${labelColor} mb-2 font-mono">${d.startTime || '-'}</div>
          <div class="flex items-center justify-between gap-4 text-xs">
            <span class="${labelColorDark}">Status:</span>
            <span class="font-medium ${statusColor}">${statusText}</span>
          </div>
          <div class="flex items-center justify-between gap-4 text-xs mt-1">
            <span class="${labelColorDark}">Duration:</span>
            <span class="font-medium font-mono">${d.value?.toFixed(2) || 0} ms</span>
          </div>
        </div>
      `
    }
  },
  series: [
    {
      type: 'tree',
      data: [treeData.value],

      orient: 'LR',
      top: '5%',
      left: '40px',
      bottom: '5%',
      right: '100px',

      roam: true,
      expandAndCollapse: true,
      initialTreeDepth: 10, // Show more levels by default

      nodePadding: 40,
      
      // Smooth curves
      lineStyle: {
        color: themeStore.isDark ? '#475569' : '#cbd5e1',
        width: 1.5,
        curveness: 0.5
      },
      
      // Improved interactivity
      emphasis: { 
        focus: 'ancestor',
        itemStyle: {
            shadowBlur: 10,
            shadowColor: 'rgba(0,0,0,0.1)'
        }
      },

      animationDuration: 400,
      animationDurationUpdate: 400
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


