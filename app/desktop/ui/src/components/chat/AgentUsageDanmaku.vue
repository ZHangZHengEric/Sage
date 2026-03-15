<template>
  <div class="agent-usage-danmaku h-full w-full overflow-hidden relative">
    <!-- 整块可悬停区域：弹幕关闭或能力面板打开时不拦截点击，让下方内容可点 -->
    <div
      class="danmaku-hover-zone absolute inset-0 z-20"
      :class="hoverZonePointerEvents"
      @mouseenter="trackHovered = true"
      @mouseleave="trackHovered = false"
    >
      <!-- 悬停时右上角关闭键：完全在轨道上方(轨道从 18px 起)，不占轨道；白底+阴影更显眼 -->
      <button
        v-show="trackHovered && !closed"
        type="button"
        class="danmaku-close-btn absolute top-0 right-2 z-30 w-[18px] h-[18px] min-w-[18px] min-h-[18px] rounded flex items-center justify-center bg-white text-neutral-600 hover:text-neutral-900 hover:bg-neutral-50 shadow border border-neutral-200 transition-colors"
        :aria-label="t('chat.abilities.close')"
        @click="handleClose"
      >
        <X class="w-3 h-3 shrink-0" stroke-width="2.5" />
      </button>
    </div>
    <div ref="layerRef" class="danmaku-layer absolute inset-0 pointer-events-none" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { X } from 'lucide-vue-next'

const props = defineProps({
  /** 能力面板打开时为 true，弹幕会自动关闭避免与面板交叉 */
  abilityPanelOpen: { type: Boolean, default: false },
  /** 当前为历史会话时为 true，弹幕不展示（与「你能做什么」逻辑一致） */
  hideForHistory: { type: Boolean, default: false },
  /** 用户点击过关闭键时为 true，由父组件持久化，切换页面再回来不重置弹幕 */
  closedByUser: { type: Boolean, default: false },
  /** 新会话时父组件递增此值，弹幕会重置并重新出现（仅在新对话页点击新会话时生效） */
  resetTrigger: { type: Number, default: 0 }
})
import { systemAPI } from '@/api/system.js'
import { useLanguage } from '@/utils/i18n.js'
import { storeToRefs } from 'pinia'
import { useLanguageStore } from '@/utils/i18n.js'

const { t } = useLanguage()
const languageStore = useLanguageStore()
const { language } = storeToRefs(languageStore)
const DAYS = [1, 3, 5, 7, 14, 30]
const LANE_COUNT = 3
const MAX_ON_SCREEN = 3
const DRIFT_DURATION_MIN = 42
const DRIFT_DURATION_MAX = 60
const LANE_HEIGHT = 28
// 下次出现时间：大区间随机，短则很快出下一条（多条同屏），长则稀疏（少条同屏），实现 B 站式「有时 1 条有时 2～3 条」
const SPAWN_DELAY_MIN_MS = 6 * 1000   // 6s
const SPAWN_DELAY_MAX_MS = 52 * 1000  // 52s（小于一条飘完时间，避免长期空屏）

const layerRef = ref(null)
const trackHovered = ref(false)
const closed = ref(false)
let danmakuItems = []
let spawnTimeoutId = null
let pendingSpawn = false
const laneOccupied = Array(LANE_COUNT).fill(false)

/** 弹幕关闭或能力面板/历史会话时不再拦截点击，让轨道区域下方内容可点 */
const hoverZonePointerEvents = computed(() =>
  (closed.value || props.abilityPanelOpen || props.hideForHistory) ? 'pointer-events-none' : 'pointer-events-auto'
)

function formatCount (n) {
  return Number(n).toLocaleString()
}

async function fetchAllUsage () {
  const promises = DAYS.map(d => systemAPI.getAgentUsageStats(d))
  const results = await Promise.allSettled(promises)
  const out = []
  results.forEach((res, i) => {
    if (res.status !== 'fulfilled' || !res.value?.usage) return
    const days = DAYS[i]
    const usage = res.value.usage
    Object.entries(usage).forEach(([action, count]) => {
      if (count > 0) out.push({ days, action, count })
    })
  })
  return out
}

function getFreeLanes () {
  const free = []
  for (let i = 0; i < LANE_COUNT; i++) {
    if (!laneOccupied[i]) free.push(i)
  }
  return free
}

function getRandomFreeLane () {
  const free = getFreeLanes()
  if (free.length === 0) return -1
  return free[Math.floor(Math.random() * free.length)]
}

function getOnScreenCount () {
  return laneOccupied.filter(Boolean).length
}

/** 后端返回的 action 为 snake_case，locale key 与文件内约定一致用驼峰 */
function snakeToCamel (s) {
  return s.replace(/_([a-z])/g, (_, c) => c.toUpperCase())
}

function getActionText (action) {
  const toolsKey = 'tools.' + snakeToCamel(action)
  let actionText = t(toolsKey)
  if (actionText === toolsKey) actionText = action
  return actionText
}

function buildDanmakuParts (days, action, count) {
  const dayUnit = days === 1 ? 'day' : 'days'
  const timeText = t('danmaku.timeDays', { n: days, unit: dayUnit })
  const actionText = getActionText(action)
  const countUnit = count === 1 ? 'use' : 'uses'
  const suffix = t('danmaku.countSuffix', { unit: countUnit })
  return {
    timeText,
    actionText,
    countText: `${formatCount(count)}${suffix}`
  }
}

function updateAllDanmakuText () {
  if (!layerRef.value) return
  const items = layerRef.value.querySelectorAll('.danmaku-item')
  items.forEach((el) => {
    const days = el.dataset.days
    const action = el.dataset.action
    const count = el.dataset.count
    if (days != null && action != null && count != null) {
      const parts = buildDanmakuParts(Number(days), action, Number(count))
      const segments = el.querySelectorAll('.danmaku-segment')
      if (segments.length >= 3) {
        segments[0].textContent = parts.timeText
        segments[1].textContent = parts.actionText
        segments[2].textContent = parts.countText
      }
    }
  })
}

function spawnOne () {
  if (!layerRef.value || danmakuItems.length === 0) return
  if (getOnScreenCount() >= MAX_ON_SCREEN) return
  const laneIndex = getRandomFreeLane()
  if (laneIndex < 0) return

  const item = danmakuItems[Math.floor(Math.random() * danmakuItems.length)]
  const parts = buildDanmakuParts(item.days, item.action, item.count)

  const el = document.createElement('div')
  el.className = 'danmaku-item danmaku-group'

  const timeSpan = document.createElement('span')
  timeSpan.className = 'danmaku-segment'
  timeSpan.textContent = parts.timeText

  const actionSpan = document.createElement('span')
  actionSpan.className = 'danmaku-segment danmaku-segment-action'
  actionSpan.textContent = parts.actionText

  const countSpan = document.createElement('span')
  countSpan.className = 'danmaku-segment'
  countSpan.textContent = parts.countText

  el.appendChild(timeSpan)
  el.appendChild(actionSpan)
  el.appendChild(countSpan)
  el.dataset.lane = String(laneIndex)
  el.dataset.days = String(item.days)
  el.dataset.action = item.action
  el.dataset.count = String(item.count)

  const top = 18 + laneIndex * LANE_HEIGHT
  el.style.top = `${top}px`
  el.style.left = '100%'

  const duration = DRIFT_DURATION_MIN + Math.random() * (DRIFT_DURATION_MAX - DRIFT_DURATION_MIN)
  el.style.animation = `danmaku-drift ${duration}s linear forwards`

  laneOccupied[laneIndex] = true
  layerRef.value.appendChild(el)

  el.addEventListener('animationend', () => {
    el.remove()
    const l = parseInt(el.dataset.lane, 10)
    if (l >= 0 && l < LANE_COUNT) laneOccupied[l] = false
    if (pendingSpawn && danmakuItems.length > 0) {
      pendingSpawn = false
      trySpawn(true)
    }
  })
}

/** 摇一个「多久后出下一条」的随机数；区间大则有时密集（2～3 条同屏）、有时稀疏（1 条或 0 条） */
function rollNextDelayMs () {
  return (
    SPAWN_DELAY_MIN_MS +
    Math.random() * (SPAWN_DELAY_MAX_MS - SPAWN_DELAY_MIN_MS)
  )
}

/**
 * 到点尝试出一条。
 * 逻辑：时间到了直接出；若屏幕已满 3 条则标记等待，等有一条消失后（animationend）再直接出。
 * @param {boolean} andScheduleNext - 出完后是否摇下一次（第 2 条不摇，第 3 条出完才摇第 4 条，之后每次出完都摇）
 */
function trySpawn (andScheduleNext = true) {
  if (getOnScreenCount() < MAX_ON_SCREEN) {
    spawnOne()
    if (andScheduleNext) scheduleNext()
  } else {
    pendingSpawn = true
  }
}

/** 摇下一次出现时间；第三条出现后会调这里，为第四条摇时间；到点 trySpawn，若已满 3 条则等消失后直接出 */
function scheduleNext () {
  if (spawnTimeoutId != null || danmakuItems.length === 0) return
  const delay = rollNextDelayMs()
  spawnTimeoutId = setTimeout(() => {
    spawnTimeoutId = null
    trySpawn(true)
  }, delay)
}

function startSpawning () {
  // 只先出一条，后续全部由随机延迟驱动，这样同屏 1/2/3 条会自然随机出现
  spawnOne()
  scheduleNext()
}

function stopSpawning () {
  if (spawnTimeoutId != null) {
    clearTimeout(spawnTimeoutId)
    spawnTimeoutId = null
  }
  pendingSpawn = false
}

function clearAllDanmaku () {
  if (!layerRef.value) return
  const items = layerRef.value.querySelectorAll('.danmaku-item')
  items.forEach((el) => {
    const l = parseInt(el.dataset.lane, 10)
    if (l >= 0 && l < LANE_COUNT) laneOccupied[l] = false
    el.remove()
  })
}

const emit = defineEmits(['close'])

function handleClose () {
  closed.value = true
  stopSpawning()
  clearAllDanmaku()
  emit('close')
}

/** 点击「你能做什么」打开能力面板时，自动关闭弹幕避免交叉 */
watch(() => props.abilityPanelOpen, (open) => {
  if (open) {
    closed.value = true
    stopSpawning()
    clearAllDanmaku()
  }
})

/** 进入历史会话时弹幕不展示（与「你能做什么」逻辑一致） */
watch(() => props.hideForHistory, (hide) => {
  if (hide) {
    closed.value = true
    stopSpawning()
    clearAllDanmaku()
  }
})

/** 仅在新对话页点击新会话时父组件递增 resetTrigger，弹幕重置并重新出现 */
watch(() => props.resetTrigger, (trigger) => {
  if (trigger > 0) {
    closed.value = false
    if (danmakuItems.length > 0) startSpawning()
  }
})

watch(language, () => {
  updateAllDanmakuText()
})

onMounted(async () => {
  try {
    danmakuItems = await fetchAllUsage()
    // 若父组件标记为用户已关闭、或当前是历史会话页，不自动开始弹幕（历史会话不展示弹幕）
    if (props.closedByUser || props.hideForHistory) {
      closed.value = true
    } else if (danmakuItems.length > 0) {
      startSpawning()
    }
  } catch (e) {
    console.warn('[AgentUsageDanmaku] fetch usage failed', e)
  }
})

onUnmounted(() => {
  stopSpawning()
})
</script>

<style>
/* 弹幕动画与样式：写在静态 style 中随构建打包，避免生产环境 CSP 拦截运行时注入的 <style> */
@keyframes danmaku-drift {
  from { transform: translate3d(0, 0, 0); }
  to { transform: translate3d(calc(-100vw - 100%), 0, 0); }
}
.agent-usage-danmaku .danmaku-item {
  position: absolute;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.7);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.12);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  will-change: transform;
  backface-visibility: hidden;
}
.agent-usage-danmaku .danmaku-segment {
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(255, 255, 255, 0.7);
  font-size: 12px;
  font-weight: 600;
  color: #0f172a;
  line-height: 1;
}
.agent-usage-danmaku .danmaku-segment-action {
  background: rgba(59, 130, 246, 0.14);
  border-color: rgba(59, 130, 246, 0.28);
  color: #1e40af;
}
.dark .agent-usage-danmaku .danmaku-item {
  background: rgba(15, 23, 42, 0.72);
  border-color: rgba(148, 163, 184, 0.5);
  box-shadow: 0 14px 30px rgba(2, 6, 23, 0.55);
}
.dark .agent-usage-danmaku .danmaku-segment {
  background: rgba(15, 23, 42, 0.85);
  border-color: rgba(148, 163, 184, 0.55);
  color: #f1f5f9;
  text-shadow: 0 1px 2px rgba(2, 6, 23, 0.6);
}
.dark .agent-usage-danmaku .danmaku-segment-action {
  background: rgba(59, 130, 246, 0.28);
  border-color: rgba(59, 130, 246, 0.45);
  color: #dbeafe;
}
.agent-usage-danmaku .danmaku-layer {
  contain: layout style paint;
  transform: translateZ(0);
}
</style>
