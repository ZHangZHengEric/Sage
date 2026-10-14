<script setup>
import { ref } from 'vue'
import { api } from '../api.js'
import AppIcon from './AppIcon.vue'
defineOptions({ name: 'WorkspaceFileTree' })
const props = defineProps({ item: Object, owner: Object, threadId: String, agentId: String, level: { type: Number, default: 0 }, downloading: String })
const emit = defineEmits(['download', 'preview'])
const expanded = ref(false), children = ref(null), busy = ref(false), error = ref('')
function size(bytes) { return bytes < 1024 ? `${bytes} B` : bytes < 1024 ** 2 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 ** 2).toFixed(1)} MB` }
async function toggle() {
  if (!props.item.is_directory) { emit('preview', props.item); return }
  expanded.value = !expanded.value
  if (!expanded.value || children.value || busy.value) return
  busy.value = true; error.value = ''
  try { children.value = await api.workspaceFiles(props.item.path, props.owner, props.threadId, props.agentId) }
  catch (exc) { error.value = exc.message }
  finally { busy.value = false }
}
</script>
<template>
  <div class="file-tree-item">
    <div class="file-tree-row" :style="{ paddingLeft: `${level * 16 + 8}px` }">
      <button class="file-name" :title="item.path" :aria-expanded="item.is_directory ? expanded : undefined" @click="toggle"><AppIcon :name="item.is_directory ? 'chevron' : 'file'" :class="{ expanded }" /><span>{{ item.name }}</span></button>
      <small v-if="!item.is_directory">{{ size(item.size) }}</small>
      <button class="icon-button" :aria-label="`下载 ${item.name}`" :disabled="Boolean(downloading)" @click="emit('download', item)"><AppIcon name="download" /></button>
    </div>
    <p v-if="error" class="file-error error" role="alert">{{ error }}</p>
    <template v-if="expanded"><p v-if="busy" class="file-error" role="status">加载中…</p><WorkspaceFileTree v-for="child in children || []" :key="child.path" :item="child" :owner="owner" :thread-id="threadId" :agent-id="agentId" :level="level + 1" :downloading="downloading" @download="emit('download', $event)" @preview="emit('preview', $event)" /></template>
  </div>
</template>
<style scoped>
.file-tree-row { display: flex; align-items: center; gap: 6px; padding: 4px 8px; border-radius: 6px; }
.file-tree-row:hover { background: var(--muted); }
.file-name { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1; padding: 4px 0; border: 0; background: transparent; color: var(--foreground); text-align: left; font-size: 13px; }
.file-name span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-name .app-icon { width: 14px; height: 14px; color: var(--muted-foreground); }
.file-name .expanded { transform: rotate(90deg); }
small { font-size: 10px; color: var(--muted-foreground); white-space: nowrap; }
.icon-button { width: 28px; height: 28px; }
.file-error { padding-left: 16px; font-size: 12px; }
</style>
