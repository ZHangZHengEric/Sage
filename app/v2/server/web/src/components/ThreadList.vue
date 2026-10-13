<script setup>
defineProps({
  threads: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
})

const emit = defineEmits(['select', 'create'])

function updatedLabel(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(date)
}
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
        class="conversation-row"
        type="button"
        :class="{ active: item.thread_id === activeId }"
        :aria-current="item.thread_id === activeId ? 'true' : undefined"
        :title="[item.title || '未命名', item._owner?.username, item.agent_id, item.thread_id].filter(Boolean).join(' · ')"
        @click="emit('select', item.thread_id)"
      >
        <span class="conversation-title">{{ item.title || '未命名' }}</span>
        <span v-if="item._owner || updatedLabel(item.updated_at)" class="conversation-meta">
          <span v-if="item._owner" class="conversation-owner">
            <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true"><circle cx="8" cy="5" r="2.3" /><path d="M3.5 13v-1a4.5 4.5 0 0 1 9 0v1" /></svg>
            <span>{{ item._owner.username }}</span>
          </span>
          <time v-if="updatedLabel(item.updated_at)" :datetime="item.updated_at">{{ updatedLabel(item.updated_at) }}</time>
        </span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.thread-panel { padding: 18px 10px 12px; }
.thread-panel-head { padding: 0 8px; margin-bottom: 18px; }
.thread-panel h2 { color: var(--foreground); font-size: 0.875rem; }
.new-thread { border-color: transparent; background: transparent; padding: 5px 8px; }
.new-thread:hover { background: var(--muted); }
.thread-list { gap: 3px; }
.conversation-row {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 5px;
  width: 100%;
  min-width: 0;
  padding: 11px 12px;
  border: 1px solid transparent;
  border-radius: 9px;
  background: transparent;
  color: var(--foreground);
  text-align: left;
  transition: background 140ms ease, border-color 140ms ease;
}
.conversation-row:hover { background: color-mix(in oklab, var(--muted) 75%, transparent); }
.conversation-row.active { background: var(--background); border-color: var(--border); box-shadow: 0 1px 3px #00000005; }
.conversation-row.active::before { content: ''; position: absolute; left: -1px; top: 15px; bottom: 15px; width: 2px; border-radius: 2px; background: var(--foreground); }
.conversation-row:focus:not(:focus-visible) { outline: none; }
.conversation-row:focus-visible { outline: 2px solid var(--primary); outline-offset: -2px; }
.conversation-title { display: block; width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.875rem; font-weight: 450; line-height: 1.5; }
.active .conversation-title { font-weight: 600; }
.conversation-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-width: 0; color: var(--muted-foreground); font-size: 0.6875rem; line-height: 1.4; }
.conversation-owner { display: inline-flex; align-items: center; gap: 5px; min-width: 0; }
.conversation-owner svg { flex-shrink: 0; opacity: .75; }
.conversation-owner span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
time { flex-shrink: 0; margin-left: auto; font-variant-numeric: tabular-nums; }
@media (prefers-reduced-motion: reduce) { .conversation-row { transition: none; } }
</style>
