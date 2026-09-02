<script setup>
defineProps({
  threads: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
})

const emit = defineEmits(['select', 'create'])
</script>

<template>
  <aside class="thread-panel">
    <div class="thread-panel-head">
      <h2>会话</h2>
      <button class="btn ghost new-thread" type="button" @click="emit('create')">
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <path fill="currentColor" d="M8 2.5a.75.75 0 0 1 .75.75v4h4a.75.75 0 0 1 0 1.5h-4v4a.75.75 0 0 1-1.5 0v-4h-4a.75.75 0 0 1 0-1.5h4v-4A.75.75 0 0 1 8 2.5Z" />
        </svg>
        新对话
      </button>
    </div>
    <p v-if="!threads.length" class="empty">还没有会话</p>
    <div class="thread-list">
      <button
        v-for="item in threads"
        :key="item.thread_id"
        class="thread"
        type="button"
        :class="{ active: item.thread_id === activeId }"
        :aria-current="item.thread_id === activeId ? 'true' : undefined"
        @click="emit('select', item.thread_id)"
      >
        <span>{{ item.title || '未命名' }}</span>
        <small>{{ item.thread_id }}</small>
      </button>
    </div>
  </aside>
</template>
