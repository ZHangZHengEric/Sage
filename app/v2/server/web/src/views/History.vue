<script setup>
import PageToolbar from '../components/PageToolbar.vue'
import { computed, onMounted, ref } from 'vue'
import { api, isForeign } from '../api.js'
import AppIcon from '../components/AppIcon.vue'
import { isAdmin } from '../auth.js'
import { saveDownload } from '../download.js'
const downloading = ref(new Set())
async function download(item) {
  downloading.value = new Set([...downloading.value, item.thread_id]); error.value = ''
  try { saveDownload(await api.downloadSession(item.thread_id)) }
  catch (exc) { error.value = exc.message }
  finally { const next = new Set(downloading.value); next.delete(item.thread_id); downloading.value = next }
}
const threads = ref([]), search = ref(''), error = ref(''), loading = ref(true)
const visible = computed(() => threads.value.filter(item => `${item.title || ''} ${item._owner?.username || ''}`.toLowerCase().includes(search.value.toLowerCase())))
function date(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN') }
async function remove(item) {
  if (isForeign(item) || !window.confirm(`删除会话「${item.title || '未命名'}」？`)) return
  try { await api.deleteThread(item.thread_id); threads.value = threads.value.filter(row => row.thread_id !== item.thread_id) }
  catch (exc) { error.value = exc.message }
}
onMounted(async () => {
  try { threads.value = await api.listThreads() } catch (exc) { error.value = exc.message }
  finally { loading.value = false }
})
</script>
<template>
  <section aria-label="历史会话">
    <PageToolbar aria-label="会话操作"><template #actions><input v-model="search" class="search-input" placeholder="搜索会话" aria-label="搜索会话" /><router-link class="btn new-chat-link" :to="{ path: '/', query: { new: '1' } }"><AppIcon name="plus" />新建对话</router-link></template></PageToolbar>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="loading" class="page-loading" role="status">加载中…</p>
    <p v-else-if="!visible.length" class="empty">{{ search ? '没有匹配的会话' : '还没有会话' }}</p>
    <div v-else class="history-list">
      <article v-for="item in visible" :key="item.thread_id" class="history-row">
        <AppIcon name="chat" />
        <router-link class="history-title" :to="{ path: '/', query: { thread: item.thread_id } }">{{ item.title || '未命名' }}</router-link>
        <span v-if="item._owner" class="tag">{{ item._owner.username }}</span>
        <time :datetime="item.updated_at">{{ date(item.updated_at) }}</time>
        <button v-if="isAdmin()" class="btn ghost" :disabled="downloading.has(item.thread_id)" @click="download(item)"><AppIcon name="download" /> {{ downloading.has(item.thread_id) ? '下载中…' : '下载诊断包' }}</button>
        <button v-if="!isForeign(item)" class="btn ghost" @click="remove(item)">删除</button>
      </article>
    </div>
  </section>
</template>
<style scoped>
.new-chat-link { display: inline-flex; align-items: center; gap: 6px; text-decoration: none; }
.history-list { border: 1px solid var(--border); border-radius: 16px; overflow: hidden; }
.history-row { display: flex; align-items: center; gap: 12px; padding: 16px; border-bottom: 1px solid var(--border); }
.history-row:last-child { border-bottom: 0; }
.history-row:hover { background: var(--muted); }
.history-title { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; text-decoration: none; }
time { color: var(--muted-foreground); font-size: 12px; }
@media (max-width: 640px) { .history-row { flex-wrap: wrap; gap: 8px; } .history-title { flex-basis: calc(100% - 32px); } time { margin-right: auto; } }
</style>
