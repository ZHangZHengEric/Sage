<template>
  <div class="timeline-container flex-none px-4 py-3 bg-muted/30 border-t border-border rounded-b-2xl">
    <!-- 按钮行 -->
    <div class="flex items-center gap-2 mb-2">
      <!-- 列表/单例显示切换按钮 -->
      <Button
        variant="ghost"
        size="icon"
        class="h-8 w-8"
        :class="{ 'bg-primary/10 text-primary': !isListView }"
        @click="toggleViewMode"
        :title="isListView ? t('workbench.singleView') : t('workbench.listView')"
      >
        <PanelsTopLeft v-if="isListView" class="w-4 h-4" />
        <PanelTop class="w-4 h-4" v-else />
      </Button>

      <div class="w-px h-4 bg-border mx-1"></div>

      <!-- 后退按钮 -->
      <Button
        variant="ghost"
        size="icon"
        class="h-8 w-8"
        @click="handleStepBackward"
        :title="t('workbench.stepBackward')"
      >
        <SkipBack class="w-4 h-4" />
      </Button>

      <!-- 进度条 -->
      <div class="flex-1 px-2">
        <Slider
          :model-value="[currentIndex]"
          :max="maxIndex"
          :min="0"
          :step="1"
          @update:model-value="handleSliderChange"
          class="w-full"
        />
      </div>

      <!-- 前进按钮 -->
      <Button
        variant="ghost"
        size="icon"
        class="h-8 w-8"
        @click="handleStepForward"
        :title="t('workbench.stepForward')"
      >
        <SkipForward class="w-4 h-4" />
      </Button>

      <!-- 实时按钮 - 只有选中/不选中两种状态 -->
      <Button
        variant="outline"
        size="sm"
        class="h-8 px-2 text-xs transition-colors duration-200"
        :class="isRealtime ? 'bg-green-500/10 text-green-600 border-green-500/30 hover:bg-green-500/20 hover:text-green-700' : 'text-muted-foreground hover:text-foreground'"
        @click="toggleRealtime"
      >
        <Radio :class="isRealtime ? 'w-3 h-3 mr-1 animate-pulse text-green-600' : 'w-3 h-3 mr-1'" />
        {{ t('workbench.realtime') }}
      </Button>
    </div>

    <!-- 时间戳行 -->
    <div class="flex justify-between text-[11px] text-muted-foreground px-1">
      <span class="w-16">{{ formatTime(startTime) }}</span>
      <span class="font-medium text-foreground flex-1 text-center">{{ formatTime(currentTime) }}</span>
      <span class="w-16 text-right">{{ formatTime(endTime) }}</span>
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
