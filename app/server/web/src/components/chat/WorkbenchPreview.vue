<template>
  <ResizablePanel
    :title="t('workbench.title')"
    :badge="workbenchStore.totalItems"
    size="large"
    @close="$emit('close')"
  >
    <template #icon>
      <Monitor class="w-5 h-5 text-primary" />
    </template>

    <!-- 工作台内容区域 -->
    <div class="h-full flex flex-col">
      <!-- 预览列表 - 占满剩余空间 -->
      <div class="flex-1 overflow-y-auto min-h-0">
        <div v-if="isLoading && workbenchStore.totalItems === 0" class="flex flex-col items-center justify-center h-full text-muted-foreground p-8">
          <Monitor class="w-12 h-12 mb-3 opacity-50 animate-pulse" />
          <p class="text-sm">{{ t('workbench.loading') }}</p>
        </div>
        <div v-else-if="workbenchStore.totalItems === 0" class="flex flex-col items-center justify-center h-full text-muted-foreground p-8">
          <Monitor class="w-12 h-12 mb-3 opacity-50" />
          <p class="text-sm">{{ t('workbench.emptyTitle') }}</p>
          <p class="text-xs mt-1">{{ t('workbench.emptyDesc') }}</p>
        </div>

        <div v-else-if="workbenchStore.isListView" class="workbench-items h-full">
          <!-- 列表模式：显示所有项目 -->
          <div
            v-for="(item, index) in filteredItemsList"
            :key="item?.id || index"
            class="workbench-item-wrapper border-b border-border last:border-b-0"
          >
            <WorkbenchItemRenderer
              v-if="item"
              :item="item"
              class="h-full"
              @quote-path="$emit('quotePath', $event)"
            />
          </div>
        </div>

        <div v-else class="workbench-single-item h-full">
          <!-- 单例模式：只显示当前选中的项目，占满整个区域 -->
          <WorkbenchItemRenderer
            v-if="currentItemData"
            :item="currentItemData"
            class="h-full"
            @quote-path="$emit('quotePath', $event)"
          />
          <div v-else class="h-full flex items-center justify-center text-muted-foreground">
            <p class="text-sm">{{ t('workbench.noSelection') }}</p>
          </div>
        </div>
      </div>

      <!-- 时间轴控制 - 固定在底部 -->
      <WorkbenchTimeline
        v-if="workbenchStore.totalItems > 0"
        v-model:current-index="workbenchStore.currentIndex"
        v-model:is-realtime="workbenchStore.isRealtime"
        v-model:is-list-view="workbenchStore.isListView"
        :items="filteredItemsList"
        @step="onStep"
      />
    </div>
  </ResizablePanel>
</template>

<script setup>
import { watch, computed, onUnmounted, ref } from 'vue'
import { Monitor } from 'lucide-vue-next'
import ResizablePanel from './ResizablePanel.vue'
import WorkbenchTimeline from './workbench/WorkbenchTimeline.vue'
import WorkbenchItemRenderer from './workbench/WorkbenchItemRenderer.vue'
import { useLanguage } from '../../utils/i18n.js'
import { useWorkbenchStore } from '../../stores/workbench.js'

const props = defineProps({
  messages: {
    type: Array,
    default: () => []
  },
  sessionId: {
    type: String,
    default: null
  },
  isLoading: {
    type: Boolean,
    default: false
  }
})

defineEmits(['close', 'quotePath'])

const { t } = useLanguage()
const workbenchStore = useWorkbenchStore()
const isDestroyed = ref(false)

const filteredItemsList = computed(() => {
  if (isDestroyed.value) return []
  return (workbenchStore.filteredItems || []).filter(item => item && item.type)
})

const currentItemData = computed(() => {
  if (isDestroyed.value) return null
  return workbenchStore.currentItem
})

// 计算当前会话ID（从 messages 中提取）
const currentSessionId = computed(() => {
  if (props.sessionId) return props.sessionId
  // 从 messages 中提取 session_id
  const msgWithSession = props.messages.find(m => m.session_id)
  return msgWithSession?.session_id || null
})

// 监听会话变化，更新工作台的 sessionId
watch(() => currentSessionId.value, (newSessionId) => {
  console.log('[WorkbenchPreview] Session changed:', newSessionId)
  if (newSessionId && !isDestroyed.value) {
    workbenchStore.setSessionId(newSessionId)
  }
}, { immediate: true })

onUnmounted(() => {
  isDestroyed.value = true
})

const onStep = (index) => {
  console.log('Workbench: Step to', index)
}
</script>

<style scoped>
.workbench-items {
  animation: fadeIn 0.3s ease;
}

.workbench-item-wrapper {
  min-height: 200px;
  height: 100%;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
</style>
