<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { api } from '../api.js'
import { saveDownload } from '../download.js'
import AppIcon from './AppIcon.vue'
import WorkspaceFileTree from './WorkspaceFileTree.vue'
import FormDrawer from './FormDrawer.vue'
const props = defineProps({ owner: Object })
defineEmits(['close'])
const files = ref([]), busy = ref(false), error = ref(''), downloading = ref(''), revision = ref(0)
const previewOpen = ref(false), previewName = ref(''), previewText = ref(''), previewImage = ref(''), previewBusy = ref(false)
let disposed = false, previewRevision = 0
async function refresh() {
  busy.value = true; error.value = ''
  try { files.value = await api.workspaceFiles('', props.owner); revision.value++ }
  catch (exc) { error.value = exc.message }
  finally { busy.value = false }
}
async function download(item = { path: '', name: 'workspace' }) {
  if (downloading.value) return
  downloading.value = item.name; error.value = ''
  try { saveDownload(await api.workspaceDownload(item.path, props.owner)) }
  catch (exc) { error.value = exc.message }
  finally { downloading.value = '' }
}
async function preview(item) {
  if (item.size > 2 * 1024 * 1024) { await download(item); return }
  const current = ++previewRevision
  previewOpen.value = true; previewBusy.value = true; previewName.value = item.name; previewText.value = ''
  if (previewImage.value) URL.revokeObjectURL(previewImage.value)
  previewImage.value = ''
  try {
    const { blob } = await api.workspaceDownload(item.path, props.owner)
    if (disposed || current !== previewRevision) return
    const imageType = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif' }[item.name.split('.').pop().toLowerCase()]
    if (imageType) previewImage.value = URL.createObjectURL(new Blob([blob], { type: imageType }))
    else if (/\.(txt|md|json|jsonl|js|ts|jsx|tsx|py|html|css|yaml|yml|toml|xml|csv|log|sh|sql|vue)$/i.test(item.name)) {
      const text = await blob.text()
      if (!disposed && current === previewRevision) previewText.value = text
    }
    else previewText.value = '此文件不支持预览，请下载后查看。'
  } catch (exc) { error.value = exc.message; previewOpen.value = false }
  finally { if (current === previewRevision) previewBusy.value = false }
}
onMounted(refresh)
onBeforeUnmount(() => { disposed = true; previewRevision++; if (previewImage.value) URL.revokeObjectURL(previewImage.value) })
</script>
<template>
  <aside class="workspace-panel" aria-label="工作空间">
    <header><h2><AppIcon name="folder" />工作空间</h2><button class="icon-button" aria-label="刷新工作空间" :disabled="busy" @click="refresh"><AppIcon name="refresh" /></button><button class="icon-button" aria-label="下载工作空间" :disabled="Boolean(downloading)" @click="download()"><AppIcon name="download" /></button><button class="icon-button" aria-label="关闭工作空间" @click="$emit('close')"><AppIcon name="close" /></button></header>
    <p v-if="error" class="error panel-message" role="alert">{{ error }}</p><p v-if="downloading" class="panel-message" role="status">正在下载 {{ downloading }}…</p>
    <div class="workspace-files"><p v-if="busy" class="empty" role="status">加载中…</p><p v-else-if="!files.length" class="empty">工作空间暂无文件</p><div v-else :key="revision"><WorkspaceFileTree v-for="item in files" :key="item.path" :item="item" :owner="owner" :downloading="downloading" @download="download" @preview="preview" /></div></div>
    <FormDrawer v-model="previewOpen" :title="previewName"><p v-if="previewBusy" role="status">加载中…</p><img v-else-if="previewImage" class="file-preview-image" :src="previewImage" :alt="previewName" /><pre v-else class="file-preview-text">{{ previewText }}</pre></FormDrawer>
  </aside>
</template>
<style scoped>
.workspace-panel { display: flex; flex-direction: column; width: 360px; min-width: 0; border-left: 1px solid var(--border); background: var(--background); overflow: hidden; }
.workspace-panel header { display: flex; align-items: center; gap: 4px; padding: 12px; border-bottom: 1px solid var(--border); min-height: 60px; }
h2 { display: flex; align-items: center; gap: 8px; font-size: 14px; margin: 0 auto 0 0; }
.workspace-files { flex: 1; min-height: 0; overflow: auto; padding: 12px 8px; }
.panel-message { padding: 8px 12px; font-size: 12px; }
.file-preview-image { max-width: 100%; height: auto; }
.file-preview-text { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 13px; }
@media (max-width: 900px) { .workspace-panel { position: absolute; inset: 0 0 0 auto; width: min(420px, 100%); z-index: 20; box-shadow: -6px 0 20px #0001; } }
</style>
