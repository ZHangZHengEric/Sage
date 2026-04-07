<template>
  <div class="timeline-container flex-none border-t border-border/60 bg-background/45 px-3 py-2">
    <div class="flex items-center gap-2">
      <!-- 列表/单例显示切换按钮 -->
      <Button
        variant="ghost"
        size="icon"
        class="h-7 w-7 rounded-full text-muted-foreground hover:bg-muted/35 hover:text-foreground"
        :class="{ 'bg-primary/10 text-primary': !isListView }"
        @click="toggleViewMode"
        :title="isListView ? t('workbench.singleView') : t('workbench.listView')"
      >
        <PanelsTopLeft v-if="isListView" class="w-4 h-4" />
        <PanelTop class="w-4 h-4" v-else />
      </Button>

      <div class="h-4 w-px bg-border/70"></div>

      <!-- 后退按钮 -->
      <Button
        variant="ghost"
        size="icon"
        class="h-7 w-7 rounded-full text-muted-foreground hover:bg-muted/35 hover:text-foreground"
        @click="handleStepBackward"
        :title="t('workbench.stepBackward')"
      >
        <SkipBack class="w-4 h-4" />
      </Button>

      <!-- 进度条与时间信息 -->
      <div class="flex min-w-0 flex-1 items-center gap-2">
        <span class="hidden w-12 shrink-0 text-[10px] text-muted-foreground/80 sm:block">
          {{ formatTime(startTime) }}
        </span>

        <div class="relative min-w-0 flex-1">
          <Slider
            :model-value="[currentIndex]"
            :max="maxIndex"
            :min="0"
            :step="1"
            @update:model-value="handleSliderChange"
            class="w-full"
          />
        </div>

        <span class="hidden w-12 shrink-0 text-right text-[10px] text-muted-foreground/80 sm:block">
          {{ formatTime(endTime) }}
        </span>
      </div>

      <!-- 前进按钮 -->
      <Button
        variant="ghost"
        size="icon"
        class="h-7 w-7 rounded-full text-muted-foreground hover:bg-muted/35 hover:text-foreground"
        @click="handleStepForward"
        :title="t('workbench.stepForward')"
      >
        <SkipForward class="w-4 h-4" />
      </Button>

      <div class="h-4 w-px bg-border/70"></div>

      <div class="rounded-full bg-muted/24 px-2 py-1 text-[10px] font-medium text-foreground">
        {{ formatTime(currentTime) }}
      </div>

      <!-- 实时按钮 - 只有选中/不选中两种状态 -->
      <Button
        variant="outline"
        size="sm"
        class="h-7 rounded-full px-2.5 text-[10px] transition-colors duration-200"
        :class="isRealtime ? 'bg-green-500/10 text-green-600 border-green-500/30 hover:bg-green-500/20 hover:text-green-700' : 'text-muted-foreground hover:text-foreground'"
        @click="toggleRealtime"
      >
        <Radio :class="isRealtime ? 'w-3 h-3 mr-1 animate-pulse text-green-600' : 'w-3 h-3 mr-1'" />
        {{ t('workbench.realtime') }}
      </Button>
    </div>
  </div>
</template>

<script setup>
import { computed, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { SkipBack, SkipForward, Radio, PanelsTopLeft, PanelTop } from 'lucide-vue-next'
import { useLanguage } from '../../../utils/i18n.js'

const props = defineProps({
  items: {
    type: Array,
    default: () => []
  },
  currentIndex: {
    type: Number,
    default: 0
  },
  isRealtime: {
    type: Boolean,
    default: true
  },
  isListView: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:currentIndex', 'update:isRealtime', 'update:isListView', 'step'])

const { t } = useLanguage()

const maxIndex = computed(() => Math.max(0, props.items.length - 1))

const startTime = computed(() => {
  if (props.items.length === 0) return null
  return props.items[0]?.timestamp
})

const endTime = computed(() => {
  if (props.items.length === 0) return null
  return props.items[props.items.length - 1]?.timestamp
})

const currentTime = computed(() => {
  if (props.items.length === 0) return null
  return props.items[props.currentIndex]?.timestamp
})

const formatTime = (timestamp) => {
  if (!timestamp) return '--:--'

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
  if (isNaN(date.getTime())) return '--:--'

  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')

  return `${hours}:${minutes}:${seconds}`
}

const handleSliderChange = (value) => {
  // 拖拽时间轴时，自动取消实时模式
  if (props.isRealtime) {
    emit('update:isRealtime', false)
  }
  const newIndex = value[0]
  emit('update:currentIndex', newIndex)
  emit('step', newIndex)
}

const handleStepBackward = () => {
  if (props.isRealtime) {
    // 在实时模式下点击后退，先退出实时模式
    emit('update:isRealtime', false)
  }
  const newIndex = Math.max(0, props.currentIndex - 1)
  emit('update:currentIndex', newIndex)
  emit('step', newIndex)
}

const handleStepForward = () => {
  if (props.isRealtime) {
    // 在实时模式下点击前进，先退出实时模式
    emit('update:isRealtime', false)
  }
  const newIndex = Math.min(maxIndex.value, props.currentIndex + 1)
  emit('update:currentIndex', newIndex)
  emit('step', newIndex)
}

const toggleRealtime = () => {
  const newRealtime = !props.isRealtime
  emit('update:isRealtime', newRealtime)
  if (newRealtime) {
    // 开启实时模式时，跳转到最新
    emit('update:currentIndex', maxIndex.value)
  }
}

const toggleViewMode = () => {
  emit('update:isListView', !props.isListView)
}

// 当有新项目添加时，如果在实时模式，自动跳转到最后
watch(() => props.items.length, (newLength, oldLength) => {
  if (props.isRealtime && newLength > oldLength) {
    emit('update:currentIndex', newLength - 1)
  }
})


</script>
