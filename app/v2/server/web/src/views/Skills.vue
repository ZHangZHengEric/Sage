<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, isForeign } from '../api.js'
import SkillBrowser from '../components/SkillBrowser.vue'
import FormDrawer from '../components/FormDrawer.vue'
import AppIcon from '../components/AppIcon.vue'
import FieldHelp from '../components/FieldHelp.vue'
import { formatBytes, resourceHelp } from '../resource-presentation.js'

const drawerOpen = ref(false)
const displayMode = ref('cards'), search = ref(''), loading = ref(true), scope = ref('all')
const visibleSkills = computed(() => skills.value.filter(item =>
  (!filterAgentId.value || boundIds.value.has(item.skill_id)) &&
  (scope.value === 'all' || (scope.value === 'mine' ? !isForeign(item) : isForeign(item))) &&
  `${item.name} ${item.description || ''}`.toLowerCase().includes(search.value.toLowerCase())))

const skills = ref([])
const agents = ref([])
const filterAgentId = ref('')
const boundIds = ref(new Set())
const error = ref('')
const pending = ref(false)
const files = ref([])
const results = ref([])
const dragging = ref(false)
const picker = ref(null)

async function load() {
  loading.value = true; error.value = ''
  try { await refresh() } catch (exc) { error.value = exc.message } finally { loading.value = false }
}
async function refresh() {
  const [nextSkills, nextAgents] = await Promise.all([api.listSkills(), api.agentSummaries(false)])
  skills.value = nextSkills
  agents.value = nextAgents
  if (filterAgentId.value && !agents.value.some((item) => item.id === filterAgentId.value)) filterAgentId.value = ''
  await changeAgent()
}

async function changeAgent() {
  const selected = filterAgentId.value
  boundIds.value = new Set()
  if (!selected) return
  try {
    const items = await api.listAgentSkills(selected)
    if (filterAgentId.value === selected) boundIds.value = new Set(items.map(item => item.skill_id))
  } catch (exc) { error.value = exc.message }
}

function isZip(file) {
  return Boolean(file?.name?.toLowerCase().endsWith('.zip'))
}

function addFiles(list) {
  if (pending.value) return
  const incoming = Array.from(list || [])
  const rejected = incoming.filter((item) => !isZip(item))
  const accepted = incoming.filter(isZip)
  const seen = new Set(files.value.map((item) => `${item.name}:${item.size}`))
  for (const item of accepted) {
    const key = `${item.name}:${item.size}`
    if (seen.has(key)) continue
    seen.add(key)
    files.value.push(item)
  }
  results.value = rejected.map((item) => ({
    filename: item.name,
    success: false,
    message: '仅支持 ZIP 文件',
  }))
  error.value = accepted.length ? '' : rejected[0] ? '仅支持 ZIP 文件' : error.value
}

function onPick(event) {
  addFiles(event.target.files)
  event.target.value = ''
}

function onDrop(event) {
  dragging.value = false
  addFiles(event.dataTransfer?.files)
}

function removeFile(index) {
  if (!pending.value) files.value.splice(index, 1)
}

async function upload() {
  if (!files.value.length || pending.value) return
  error.value = ''
  pending.value = true
  try {
    const submitted = [...files.value]
    const payload = await api.uploadSkills(submitted)
    results.value = payload.results || []
    files.value = submitted.filter((_, index) => !results.value[index]?.success)
    if (payload.failed_count) {
      error.value = `${payload.success_count} 个成功，${payload.failed_count} 个失败`
    }
    await refresh()
  } catch (exc) {
    error.value = exc.message
  } finally {
    pending.value = false
  }
}

onMounted(load)
function startNew() {
  if (pending.value) return
  error.value = ''; files.value = []; results.value = []
  drawerOpen.value = true
}
</script>

<template>
  <section class="resource-page">
    <header class="page-head rs-page-head"><div class="rs-heading"><h1>技能</h1><span v-if="!loading" class="rs-count">{{ skills.length }}</span></div><button class="btn cta" type="button" :disabled="pending" @click="startNew"><AppIcon name="plus" />导入技能</button></header>
    <div class="rs-toolbar"><div class="rs-filters" aria-label="技能范围"><button v-for="[value, label] in [['all', '全部技能'], ['mine', '我的技能'], ['foreign', '其他用户']]" :key="value" type="button" :aria-pressed="scope === value" @click="scope = value">{{ label }}</button></div><div class="rs-toolbar-actions"><select v-model="filterAgentId" aria-label="按智能体筛选技能" @change="changeAgent"><option value="">全部智能体</option><option v-for="item in agents" :key="item.id" :value="item.id">{{ item.name }}</option></select><label class="rs-search"><AppIcon name="search" /><input v-model="search" type="search" placeholder="搜索技能" aria-label="搜索技能" /></label><div class="view-switch" aria-label="显示方式"><button type="button" :aria-pressed="displayMode === 'cards'" aria-label="卡片显示" @click="displayMode = 'cards'"><AppIcon name="grid" /></button><button type="button" :aria-pressed="displayMode === 'rows'" aria-label="列表显示" @click="displayMode = 'rows'"><AppIcon name="list" /></button></div></div></div>
    <p v-if="error && !drawerOpen && skills.length" class="error" role="alert">{{ error }}</p>
    <div v-if="loading" class="rs-grid" aria-busy="true" aria-label="正在加载技能"><div v-for="n in 3" :key="n" class="rs-skeleton"><i></i><i></i><i></i></div></div>
    <div v-else-if="error && !skills.length" class="rs-empty" role="alert"><span class="rs-icon"><AppIcon name="link" /></span><h2>暂时无法加载技能</h2><p>{{ error }}</p><button class="btn cta" type="button" @click="load">重新加载</button></div>
    <div v-else-if="!visibleSkills.length" class="rs-empty"><span class="rs-icon"><AppIcon :name="search || filterAgentId || scope !== 'all' ? 'search' : 'skill'" /></span><h2>{{ search || scope !== 'all' ? '没有找到匹配的技能' : filterAgentId ? '该智能体未关联技能' : '导入你的第一个技能' }}</h2><button v-if="search || filterAgentId || scope !== 'all'" class="btn ghost" type="button" @click="search = ''; scope = 'all'; filterAgentId = ''; changeAgent()">清除筛选</button><button v-else class="btn cta" type="button" @click="startNew">导入技能</button></div>
    <div v-else :class="displayMode === 'cards' ? 'rs-grid' : 'rs-rows'"><article v-for="item in visibleSkills" :key="`${item._owner?.user_id || ''}:${item.skill_id}`" class="rs-card"><header class="rs-card-head"><span class="rs-icon"><AppIcon name="skill" /></span><div><h2>{{ item.name }}</h2><div class="rs-technical">{{ item._owner?.username || '我的技能' }}<span v-if="isForeign(item)"> · 只读</span></div></div></header><p class="rs-description">{{ item.description || '暂无说明' }}</p><div class="rs-tags"><span class="rs-badge neutral">修订 {{ item.revision ?? '—' }}</span><span v-if="isForeign(item)" class="rs-badge readonly">只读</span></div><footer class="rs-card-footer"><span>{{ item.file_count ?? '—' }} 个文件 · {{ formatBytes(item.total_bytes) }}</span><SkillBrowser :item="item" @removed="load" /></footer></article></div>
    <FormDrawer v-model="drawerOpen" title="导入技能" centered panel-class="resource-dialog import-dialog" :busy="pending">
      <input ref="picker" class="sr-only" type="file" accept=".zip,application/zip" multiple :disabled="pending" @change="onPick" />
      <button class="rs-dropzone" type="button" :disabled="pending" :class="{ active: dragging }" @click="picker?.click()" @dragenter.prevent="dragging = true" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="onDrop"><AppIcon name="folder" /><strong>选择或拖入 ZIP 技能包</strong><span>支持批量导入，每个技能包需包含 SKILL.md</span></button>
      <ul v-if="files.length" class="rs-file-list"><li v-for="(item, index) in files" :key="`${item.name}-${item.size}`"><span><AppIcon name="file" />{{ item.name }}<small>{{ formatBytes(item.size) }}</small></span><button class="btn ghost" type="button" :disabled="pending" @click="removeFile(index)">移除</button></li></ul>
      <ul v-if="results.length" class="rs-file-list" aria-label="导入结果"><li v-for="(item, index) in results" :key="`${item.filename}:${index}`"><span>{{ item.filename }}</span><small :class="item.success ? 'rs-success' : 'error'">{{ item.message }}</small></li></ul>
      <template #footer><p v-if="error" class="error rs-footer-error" role="alert">{{ error }}</p><div class="rs-dialog-footer"><span class="rs-label rs-small muted">导入后在智能体中选择<FieldHelp label="技能授权" :text="resourceHelp.bind" /></span><button class="btn cta" type="button" :disabled="pending || !files.length" @click="upload">{{ pending ? '正在导入…' : `导入${files.length ? ` ${files.length} 个` : ''}技能包` }}</button></div></template>
    </FormDrawer>
  </section>
</template>
<style src="../resource-surfaces.css"></style>
