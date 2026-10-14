<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, isForeign } from '../api.js'
import ResourceDetails from '../components/ResourceDetails.vue'
import FormDrawer from '../components/FormDrawer.vue'
import AppIcon from '../components/AppIcon.vue'

const drawerOpen = ref(false)
const displayMode = ref('cards'), search = ref(''), loading = ref(true)
const visibleSkills = computed(() => skills.value.filter(item =>
  `${item.name} ${item.description || ''}`.toLowerCase().includes(search.value.toLowerCase())))

const skills = ref([])
const agents = ref([])
const agentId = ref(localStorage.getItem('sage.server_v2.agent') || '')
const bound = ref([])
const error = ref('')
const pending = ref(false)
const files = ref([])
const results = ref([])
const dragging = ref(false)
const picker = ref(null)

const boundNames = computed(() => new Set(bound.value.map((item) => item.name)))
const currentAgent = computed(
  () => agents.value.find((item) => item.id === agentId.value)?.name || agentId.value
)

async function refresh() {
  const [nextSkills, nextAgents] = await Promise.all([api.listSkills(), api.listAgents(false)])
  skills.value = nextSkills
  agents.value = nextAgents
  if (!agents.value.some((item) => item.id === agentId.value)) {
    agentId.value = agents.value[0]?.id || ''
  }
  bound.value = agentId.value ? await api.listAgentSkills(agentId.value) : []
}

function changeAgent() {
  localStorage.setItem('sage.server_v2.agent', agentId.value)
  refresh()
}

function isZip(file) {
  return Boolean(file?.name?.toLowerCase().endsWith('.zip'))
}

function addFiles(list) {
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
  files.value.splice(index, 1)
}

async function upload() {
  if (!files.value.length || pending.value) return
  error.value = ''
  pending.value = true
  try {
    const payload = await api.uploadSkills(files.value)
    results.value = payload.results || []
    files.value = []
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

async function remove(id) {
  await api.deleteSkill(id)
  await refresh()
}

async function toggleBind(item) {
  if (!agentId.value || isForeign(item)) return
  const names = bound.value.map((skill) => skill.name)
  const next = names.includes(item.name)
    ? names.filter((name) => name !== item.name)
    : [...names, item.name]
  await api.bindAgentSkills(agentId.value, next)
  await refresh()
}

onMounted(async () => {
  try {
    await refresh()
  } catch (exc) {
    error.value = exc.message
  } finally { loading.value = false }
})
function startNew() {
  error.value = ''; files.value = []; results.value = []
  drawerOpen.value = true
}
</script>

<template>
  <section>
    <header class="page-head">
      <h1>技能</h1>
      <div class="page-actions"><div class="view-switch" aria-label="显示方式"><button :aria-pressed="displayMode === 'cards'" @click="displayMode = 'cards'"><AppIcon name="grid" />卡片</button><button :aria-pressed="displayMode === 'rows'" @click="displayMode = 'rows'"><AppIcon name="list" />列表</button></div><input v-model="search" class="search-input" placeholder="搜索技能" aria-label="搜索技能" /><button class="btn cta" :disabled="pending" @click="startNew"><AppIcon name="plus" /> 导入技能</button></div>
    </header>
    <div class="skill-filters">
      <label class="skill-agent"><span>关联到智能体</span><select v-model="agentId" @change="changeAgent"><option v-for="item in agents" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
    </div>
    <p v-if="error && !drawerOpen" class="error" role="alert">{{ error }}</p>
    <p v-if="loading" class="page-loading" role="status">加载中…</p>
    <p v-else-if="!visibleSkills.length" class="empty">{{ search ? '没有匹配的技能' : '暂无技能' }}</p>
    <div v-else :class="displayMode === 'cards' ? 'resource-grid' : 'skill-rows'">
      <article v-for="item in visibleSkills" :key="`${item._owner?.user_id || ''}:${item.skill_id}`" class="resource-card skill-card">
        <div class="resource-card-head"><span class="resource-icon"><AppIcon name="skill" /></span><h2>{{ item.name }}</h2><span v-if="item._owner" class="tag">{{ item._owner.username }}</span></div>
        <p>{{ item.description }}</p>
        <div class="resource-card-foot">
          <label class="skill-binding"><input type="checkbox" :disabled="!agentId || isForeign(item)" :checked="!isForeign(item) && boundNames.has(item.name)" @change="toggleBind(item)" />关联 {{ currentAgent }}</label>
          <div class="row"><ResourceDetails :item="item" kind="skills" /><button v-if="!isForeign(item)" class="btn ghost" @click="remove(item.skill_id)">删除</button></div>
        </div>
      </article>
    </div>
    <FormDrawer v-model="drawerOpen" title="上传技能" :busy="pending">
    <div class="panel">
      <input
        ref="picker"
        class="sr-only"
        type="file"
        accept=".zip,application/zip"
        multiple
        @change="onPick"
      />
      <button
        class="dropzone"
        type="button"
        :class="{ active: dragging }"
        @click="picker?.click()"
        @dragenter.prevent="dragging = true"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <strong>批量选择 ZIP 技能包</strong>
        <span>可一次选多个，或拖到这里。每个 ZIP 需包含 SKILL.md。</span>
      </button>
      <ul v-if="files.length" class="file-list">
        <li v-for="(item, index) in files" :key="`${item.name}-${index}`">
          <span>{{ item.name }}</span>
          <button class="btn ghost" type="button" @click="removeFile(index)">移除</button>
        </li>
      </ul>
      <ul v-if="results.length" class="file-list">
        <li v-for="item in results" :key="item.filename" :class="{ fail: !item.success }">
          <span>{{ item.filename }}</span>
          <small :class="item.success ? 'muted' : 'error'">{{ item.message }}</small>
        </li>
      </ul>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="btn cta" type="button" :disabled="pending || !files.length" @click="upload">
        {{ pending ? '正在上传…' : '上传技能包' }}
      </button>
    </div>
    </FormDrawer>
  </section>
</template>

<style scoped>
.skill-filters { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
.skill-agent { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted-foreground); }
.skill-agent select { max-width: 180px; padding: 6px 10px; }
.skill-binding { display: flex; gap: 6px; align-items: center; }
.skill-rows { display: flex; flex-direction: column; gap: 8px; }
.skill-rows .skill-card { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(160px, 2fr) minmax(200px, 1fr); gap: 16px; align-items: center; padding: 14px 20px; }
.skill-rows .resource-card-foot { border: 0; padding: 0; margin: 0; }
.skill-card .row { margin: 0; }
@media (max-width: 900px) { .skill-rows .skill-card { display: flex; align-items: stretch; } }
</style>
