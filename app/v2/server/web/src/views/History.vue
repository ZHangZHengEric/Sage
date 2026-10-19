<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import PageToolbar from '../components/PageToolbar.vue'
import FormDrawer from '../components/FormDrawer.vue'
import AppIcon from '../components/AppIcon.vue'
import { api, isForeign } from '../api.js'
import { getUser, isAdmin } from '../auth.js'
import { saveDownload } from '../download.js'
import { conversationAgent, newestThreads } from '../conversations.js'

const threads = ref([]), agents = ref([]), search = ref(''), agentFilter = ref('')
const error = ref(''), loading = ref(true), downloading = ref(new Set())
const deleteTarget = ref(null), deleting = ref(false), deleteError = ref('')
const root = ref(null)
const userId = getUser()?.user_id
const agentName = item => conversationAgent(item, agents.value, userId)
const agentOptions = computed(() => [...new Set(threads.value.map(item => item.agent_id).filter(Boolean))]
  .map(id => ({ id, name: [...new Set(threads.value.filter(item => item.agent_id === id).map(agentName))].join(' / ') })))
const visible = computed(() => newestThreads(threads.value.filter(item => {
  if (agentFilter.value && item.agent_id !== agentFilter.value) return false
  return `${item.title || ''} ${agentName(item)}`.toLowerCase().includes(search.value.trim().toLowerCase())
})))
const filtered = computed(() => Boolean(search.value || agentFilter.value))
function clearFilters() { search.value = ''; agentFilter.value = '' }
function date(value) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ''
  const today = new Date(), yesterday = new Date(); yesterday.setDate(today.getDate() - 1)
  return [today.toDateString(), yesterday.toDateString()].includes(parsed.toDateString())
    ? parsed.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : parsed.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric', ...(parsed.getFullYear() !== today.getFullYear() ? { year: 'numeric' } : {}) })
}
async function load() {
  if (loading.value && threads.value.length) return
  loading.value = true; error.value = ''
  try { threads.value = await api.listThreads() }
  catch (exc) { error.value = exc.message }
  finally { loading.value = false }
}
async function download(item) {
  if (!isAdmin() || downloading.value.has(item.thread_id)) return
  closeMenus(true)
  error.value = ''
  downloading.value = new Set([...downloading.value, item.thread_id])
  try { saveDownload(await api.downloadSession(item.thread_id)) }
  catch (exc) { error.value = exc.message }
  finally { const next = new Set(downloading.value); next.delete(item.thread_id); downloading.value = next }
}
function requestDelete(item) {
  if (isForeign(item) || deleting.value) return
  closeMenus(true)
  deleteError.value = ''; deleteTarget.value = item
}
async function remove() {
  const item = deleteTarget.value
  if (!item || isForeign(item) || deleting.value) return
  deleting.value = true; deleteError.value = ''
  try {
    await api.deleteThread(item.thread_id)
    threads.value = threads.value.filter(row => row.thread_id !== item.thread_id)
    deleteTarget.value = null
  } catch (exc) { deleteError.value = exc.message }
  finally { deleting.value = false }
}
function closeMenus(restoreFocus = false, except = null) {
  for (const menu of root.value?.querySelectorAll('.history-actions[open]') || []) {
    if (menu === except) continue
    if (restoreFocus) menu.querySelector('summary')?.focus()
    menu.open = false
  }
}
function toggleMenu(event) { if (event.target.open) closeMenus(false, event.target) }
function outside(event) { if (!event.target.closest('.history-actions')) closeMenus() }
function escape(event) { if (event.key === 'Escape') closeMenus(true) }
onMounted(() => {
  void load()
  api.agentSummaries().then(items => { agents.value = items }).catch(() => {})
  document.addEventListener('pointerdown', outside)
  document.addEventListener('keydown', escape)
})
onUnmounted(() => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) })
</script>
<template>
  <section ref="root" class="conversation-history" aria-label="历史会话">
    <PageToolbar aria-label="会话操作">
      <label class="history-search"><AppIcon name="search" /><input v-model="search" placeholder="搜索标题或智能体" aria-label="搜索会话" /></label>
      <select v-model="agentFilter" aria-label="筛选智能体"><option value="">全部智能体</option><option v-for="item in agentOptions" :key="item.id" :value="item.id">{{ item.name }}</option></select>
      <template #actions><router-link class="btn history-new" :to="{ path: '/', query: { new: '1' } }"><AppIcon name="plus" />新建对话</router-link></template>
    </PageToolbar>
    <div v-if="error" class="history-feedback" role="alert"><span class="error">{{ error }}</span><button class="btn ghost" :disabled="loading" @click="load">重试</button></div>
    <div v-if="loading && !threads.length" class="history-skeleton" role="status" aria-label="正在加载会话"><div v-for="n in 5" :key="n"><i></i><span></span></div></div>
    <div v-else-if="!visible.length && !error" class="history-empty">
      <AppIcon :name="filtered ? 'search' : 'chat'" /><h2>{{ filtered ? '没有匹配的会话' : '还没有会话' }}</h2>
      <button v-if="filtered" class="btn secondary" @click="clearFilters">清除筛选</button>
      <router-link v-else class="btn" :to="{ path: '/', query: { new: '1' } }">新建对话</router-link>
    </div>
    <div v-else class="history-list">
        <article v-for="item in visible" :key="item.thread_id" class="history-row">
          <span class="history-symbol"><AppIcon name="chat" /></span>
          <router-link class="history-content" :to="{ path: '/', query: { thread: item.thread_id } }">
            <span class="history-title">{{ item.title || '未命名会话' }}</span>
            <span class="history-meta"><span>{{ agentName(item) }}</span><template v-if="isForeign(item)"><span>{{ item._owner.username }}</span><span class="history-readonly"><AppIcon name="lock" />只读</span></template></span>
          </router-link>
          <time :datetime="item.updated_at" :title="new Date(item.updated_at).toLocaleString('zh-CN')">{{ date(item.updated_at) }}</time>
          <details class="history-actions" @toggle="toggleMenu" @focusout="event => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false }">
            <summary :aria-label="`会话操作：${item.title || '未命名会话'}`"><AppIcon name="more" /></summary>
            <div class="history-popover">
              <router-link :to="{ path: '/', query: { thread: item.thread_id } }" @click="closeMenus()"><AppIcon :name="isForeign(item) ? 'eye' : 'chat'" />{{ isForeign(item) ? '查看会话' : '继续对话' }}</router-link>
              <button v-if="isAdmin()" :disabled="downloading.has(item.thread_id)" @click="download(item)"><AppIcon name="download" />{{ downloading.has(item.thread_id) ? '下载中…' : '下载诊断包' }}</button>
              <button v-if="!isForeign(item)" class="history-delete" @click="requestDelete(item)"><AppIcon name="trash" />删除会话</button>
            </div>
          </details>
        </article>
    </div>
    <FormDrawer :model-value="Boolean(deleteTarget)" title="删除会话" centered :busy="deleting" @update:model-value="value => { if (!value && !deleting) deleteTarget = null }">
      <p class="history-delete-copy">确定删除「{{ deleteTarget?.title || '未命名会话' }}」？删除后无法恢复。</p>
      <p v-if="deleteError" class="error" role="alert">{{ deleteError }}</p>
      <template #footer><div class="history-confirm"><button class="btn secondary" :disabled="deleting" @click="deleteTarget = null">取消</button><button class="btn danger" :disabled="deleting" @click="remove">{{ deleting ? '删除中…' : '删除会话' }}</button></div></template>
    </FormDrawer>
  </section>
</template>
<style scoped>
.conversation-history { width: 100%; }
.history-search { display: flex; align-items: center; gap: 8px; height: var(--control-height); width: 258px; padding: 0 12px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--card); }
.history-search:focus-within { border-color: var(--accent); }
.history-search > svg { width: 16px; color: var(--muted-foreground); flex-shrink: 0; }
.history-search input { width: 100%; min-width: 0; border: 0; background: transparent; padding: 0; margin: 0; outline: 0; }
.conversation-history select { max-width: 180px; width: auto; margin: 0; height: var(--control-height); font-size: var(--control-font); }
.history-new { display: inline-flex; gap: 7px; align-items: center; text-decoration: none; white-space: nowrap; }
.history-list { border-top: 1px solid var(--border); padding-bottom: 145px; }
.history-row { display: flex; align-items: center; gap: 15px; min-height: 82px; position: relative; padding: 14px 15px; border: 1px solid transparent; border-bottom-color: var(--border); border-radius: var(--radius); }
.history-row:hover, .history-row:focus-within { border-color: var(--border); background: var(--card); }
.history-symbol { display: grid; place-items: center; width: 38px; height: 38px; border: 1px solid var(--border); background: var(--card); color: var(--muted-foreground); border-radius: 11px; flex-shrink: 0; }
.history-symbol svg { width: 18px; }
.history-content { min-width: 0; flex: 1; text-decoration: none; display: flex; flex-direction: column; gap: 7px; }
.history-title { font-size: 14px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-meta { display: flex; align-items: center; gap: 12px; color: var(--muted-foreground); font-size: 11px; }
.history-meta > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-readonly { display: inline-flex; align-items: center; gap: 3px; flex-shrink: 0; }
.history-readonly svg { width: 12px; height: 12px; }
time { font-size: 11px; color: var(--muted-foreground); white-space: nowrap; }
.history-actions { position: relative; flex-shrink: 0; }
.history-actions summary { display: flex; align-items: center; justify-content: center; width: 36px; height: 36px; padding: 0; border: 0; border-radius: var(--radius); background: transparent; color: var(--foreground); cursor: pointer; list-style: none; }
.history-actions summary::-webkit-details-marker { display: none; }
.history-actions summary:hover, .history-actions[open] summary { background: var(--muted); }
.history-actions summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.history-actions svg { width: 15px; height: 15px; }
.history-actions summary svg { width: 22px; height: 22px; }
.history-actions[open] { z-index: 2; }
.history-popover { position: absolute; right: 0; top: calc(100% + 5px); z-index: 5; width: 168px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--card); padding: 5px; box-shadow: var(--shadow-popover); }
.history-popover a, .history-popover button { width: 100%; display: flex; align-items: center; gap: 8px; padding: 10px; border: 0; border-radius: 5px; text-decoration: none; background: transparent; color: var(--foreground); font: inherit; font-size: 12px; text-align: left; }
.history-popover :is(a, button):hover { background: var(--muted); }
.history-popover .history-delete { color: var(--destructive); }
.history-confirm .danger { background: var(--destructive); border-color: var(--destructive); color: var(--destructive-foreground); }
.history-feedback, .history-confirm { display: flex; align-items: center; justify-content: flex-end; gap: 10px; }
.history-feedback { justify-content: space-between; margin-bottom: 16px; }
.history-empty { padding: 100px 20px; text-align: center; }
.history-empty > svg { width: 32px; height: 32px; color: var(--muted-foreground); }
.history-empty h2 { font-size: 16px; font-weight: 500; margin: 18px 0 24px; }
.history-delete-copy { margin: 0; overflow-wrap: anywhere; }
.history-skeleton > div { display: flex; gap: 16px; align-items: center; height: 82px; border-bottom: 1px solid var(--border); }
.history-skeleton i, .history-skeleton span { display: block; height: 38px; width: 38px; border-radius: 8px; background: var(--muted); }
.history-skeleton span { height: 16px; width: 55%; }
@media (prefers-reduced-motion: no-preference) { .history-row { transition: background var(--duration-fast) var(--ease-standard), border-color var(--duration-fast) var(--ease-standard), opacity var(--duration-fast) var(--ease-standard); } }
@media (max-width: 760px) {
  .history-search { width: 100%; }
  .history-row { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; gap: 9px 10px; padding: 14px 5px; }
  .history-symbol { width: 34px; height: 34px; }
  .history-title { font-size: 13px; }
  .history-meta { gap: 7px; }
  .history-row { grid-template-columns: 34px minmax(0, 1fr) auto; }
  .history-row time { grid-column: 2; grid-row: 2; }
  .history-actions { grid-column: 3; grid-row: 1 / 3; }
  .history-actions summary { width: 40px; height: 40px; }
  .history-popover :is(a, button) { min-height: 42px; }
}
</style>
