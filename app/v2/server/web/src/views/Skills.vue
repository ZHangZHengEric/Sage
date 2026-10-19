<script setup>
import PageToolbar from '../components/PageToolbar.vue'
import { computed, onMounted, ref, watch } from 'vue'
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
  (scope.value === 'all' || !isForeign(item)) &&
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
const importMode = ref('local')
const remoteInputs = ref({ zip_url: '', skills_cli: '' })
const remotePreview = ref(null)
const selectedPaths = ref([])
const overwritePaths = ref([])
const remoteSource = computed(() => ({ kind: importMode.value, value: (remoteInputs.value[importMode.value] || '').trim() }))
let importRequest = 0
watch([importMode, () => remoteInputs.value.zip_url, () => remoteInputs.value.skills_cli], () => {
  importRequest += 1
  remotePreview.value = null; selectedPaths.value = []; overwritePaths.value = []
  results.value = []; error.value = ''
}, { flush: 'sync' })

async function previewRemote() {
  if (pending.value || importMode.value === 'local' || !remoteSource.value.value) return
  const request = ++importRequest
  const source = { ...remoteSource.value }
  pending.value = true; error.value = ''; results.value = []; remotePreview.value = null
  try {
    const preview = await api.previewSkillImport(source)
    if (request !== importRequest) return
    remotePreview.value = { ...preview, source }
    selectedPaths.value = preview.candidates.filter(item => item.status !== 'conflict').map(item => item.path)
    overwritePaths.value = []
  } catch (exc) {
    if (request === importRequest) error.value = exc.message
  } finally { pending.value = false }
}

async function importRemote() {
  if (pending.value || !remotePreview.value || !selectedPaths.value.length) return
  const preview = remotePreview.value
  pending.value = true; error.value = ''; results.value = []
  try {
    const payload = await api.importSkills({
      ...preview.source, revision: preview.revision,
      items: preview.candidates.filter(item => selectedPaths.value.includes(item.path)).map(item => ({
        path: item.path, package_sha256: item.package_sha256,
        expected_version_id: item.expected_version_id, overwrite: overwritePaths.value.includes(item.path),
      })),
    })
    results.value = payload.results || []
    const succeeded = new Set(results.value.filter(item => item.success).map(item => item.filename))
    selectedPaths.value = selectedPaths.value.filter(path => !succeeded.has(path))
    overwritePaths.value = overwritePaths.value.filter(path => !succeeded.has(path))
    remotePreview.value.candidates = preview.candidates.filter(item => !succeeded.has(item.path))
    if (payload.failed_count) error.value = `${payload.success_count} 个成功，${payload.failed_count} 个失败`
    await refresh()
  } catch (exc) { error.value = exc.message } finally { pending.value = false }
}

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
  importRequest += 1
  importMode.value = 'local'; remoteInputs.value = { zip_url: '', skills_cli: '' }
  remotePreview.value = null; selectedPaths.value = []; overwritePaths.value = []
  error.value = ''; files.value = []; results.value = []
  drawerOpen.value = true
}
</script>

<template>
  <section class="resource-page" aria-label="技能">
    <PageToolbar aria-label="技能操作"><div class="rs-filters" aria-label="技能范围"><button v-for="[value, label] in [['all', '全部技能'], ['mine', '我的技能']]" :key="value" type="button" :aria-pressed="scope === value" @click="scope = value">{{ label }}</button></div><template #actions><div class="rs-toolbar-actions"><select v-model="filterAgentId" aria-label="按智能体筛选技能" @change="changeAgent"><option value="">全部智能体</option><option v-for="item in agents" :key="item.id" :value="item.id">{{ item.name }}</option></select><label class="rs-search"><AppIcon name="search" /><input v-model="search" type="search" placeholder="搜索技能" aria-label="搜索技能" /></label><div class="view-switch" aria-label="显示方式"><button type="button" :aria-pressed="displayMode === 'cards'" aria-label="卡片显示" @click="displayMode = 'cards'"><AppIcon name="grid" /></button><button type="button" :aria-pressed="displayMode === 'rows'" aria-label="列表显示" @click="displayMode = 'rows'"><AppIcon name="list" /></button></div></div><button class="btn cta" type="button" :disabled="pending" @click="startNew"><AppIcon name="plus" />导入技能</button></template></PageToolbar>
    <p v-if="error && !drawerOpen && skills.length" class="error" role="alert">{{ error }}</p>
    <div v-if="loading" class="rs-grid" aria-busy="true" aria-label="正在加载技能"><div v-for="n in 3" :key="n" class="rs-skeleton"><i></i><i></i><i></i></div></div>
    <div v-else-if="error && !skills.length" class="rs-empty" role="alert"><span class="rs-icon"><AppIcon name="link" /></span><h2>暂时无法加载技能</h2><p>{{ error }}</p><button class="btn cta" type="button" @click="load">重新加载</button></div>
    <div v-else-if="!visibleSkills.length" class="rs-empty"><span class="rs-icon"><AppIcon :name="search || filterAgentId || scope !== 'all' ? 'search' : 'skill'" /></span><h2>{{ search || scope !== 'all' ? '没有找到匹配的技能' : filterAgentId ? '该智能体未关联技能' : '导入你的第一个技能' }}</h2><button v-if="search || filterAgentId || scope !== 'all'" class="btn ghost" type="button" @click="search = ''; scope = 'all'; filterAgentId = ''; changeAgent()">清除筛选</button><button v-else class="btn cta" type="button" @click="startNew">导入技能</button></div>
    <div v-else :class="displayMode === 'cards' ? 'rs-grid' : 'rs-rows'"><article v-for="item in visibleSkills" :key="`${item._owner?.user_id || ''}:${item.skill_id}`" class="rs-card"><header class="rs-card-head"><span class="rs-icon"><AppIcon name="skill" /></span><div><h2>{{ item.name }}</h2><div class="rs-technical">{{ item._owner?.username || '我的技能' }}<span v-if="isForeign(item)"> · 只读</span></div></div></header><p class="rs-description">{{ item.description || '暂无说明' }}</p><div class="rs-tags"><span class="rs-badge neutral">修订 {{ item.revision ?? '—' }}</span><span v-if="isForeign(item)" class="rs-badge readonly">只读</span></div><footer class="rs-card-footer"><span>{{ item.file_count ?? '—' }} 个文件 · {{ formatBytes(item.total_bytes) }}</span><SkillBrowser :item="item" @removed="load" /></footer></article></div>
    <FormDrawer v-model="drawerOpen" title="导入技能" centered panel-class="resource-dialog import-dialog" :busy="pending">
      <div class="rs-detail-tabs" aria-label="技能导入方式"><button v-for="[value, label] in [['local', '本地文件'], ['zip_url', '在线 ZIP'], ['skills_cli', 'Skills CLI']]" :key="value" type="button" :aria-pressed="importMode === value" :disabled="pending" @click="importMode = value">{{ label }}</button></div>
      <template v-if="importMode === 'local'">
      <input ref="picker" class="sr-only" type="file" accept=".zip,application/zip" multiple :disabled="pending" @change="onPick" />
      <button class="rs-dropzone" type="button" :disabled="pending" :class="{ active: dragging }" @click="picker?.click()" @dragenter.prevent="dragging = true" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="onDrop"><AppIcon name="folder" /><strong>选择或拖入 ZIP 技能包</strong><span>支持批量导入，每个技能包需包含 SKILL.md</span></button>
      <ul v-if="files.length" class="rs-file-list"><li v-for="(item, index) in files" :key="`${item.name}-${item.size}`"><span><AppIcon name="file" />{{ item.name }}<small>{{ formatBytes(item.size) }}</small></span><button class="btn ghost" type="button" :disabled="pending" @click="removeFile(index)">移除</button></li></ul>
      </template>
      <template v-else>
        <div class="field rs-import-source">
          <label class="rs-label" :for="`skill-import-${importMode}`">{{ importMode === 'zip_url' ? 'ZIP 下载地址' : '安装命令' }}<FieldHelp :label="importMode === 'zip_url' ? '在线 ZIP' : 'Skills CLI'" :text="importMode === 'zip_url' ? '填写可直接下载 ZIP 的公开 HTTPS 地址，最多 32 MiB。支持一个包包含多个技能。' : '粘贴 npx skills add 命令，支持公开 GitHub 仓库、目录和 --skill 参数。安装位置由 Sage 管理，需要服务器具备 Node.js 22.20 以上及 npx。'" /></label>
          <input v-if="importMode === 'zip_url'" id="skill-import-zip_url" v-model="remoteInputs.zip_url" type="url" placeholder="https://example.com/skills.zip" :disabled="pending" autocomplete="off" @keydown.enter.prevent="previewRemote" />
          <textarea v-else id="skill-import-skills_cli" v-model="remoteInputs.skills_cli" rows="3" placeholder="npx skills add vercel-labs/agent-skills --skill web-design-guidelines" :disabled="pending" spellcheck="false" />
          <button class="btn ghost" type="button" :disabled="pending || !remoteSource.value" @click="previewRemote">{{ pending && !remotePreview ? '正在解析…' : remotePreview ? '重新解析' : '解析技能' }}</button>
        </div>
        <ul v-if="remotePreview?.candidates.length" class="rs-import-candidates" aria-label="可导入技能">
          <li v-for="item in remotePreview.candidates" :key="item.path">
            <label class="rs-import-choice"><input v-model="selectedPaths" type="checkbox" :value="item.path" :disabled="pending" /><span><strong>{{ item.name }}</strong><small>{{ item.description }}</small><small>{{ item.file_count }} 个文件 · {{ formatBytes(item.total_bytes) }} · {{ item.status === 'new' ? '新增' : item.status === 'unchanged' ? '内容相同' : '同名冲突' }}</small><code>{{ item.path }}</code></span></label>
            <label v-if="item.status === 'conflict'" class="rs-import-overwrite"><input v-model="overwritePaths" type="checkbox" :value="item.path" :disabled="pending || !selectedPaths.includes(item.path)" />更新已有技能</label>
          </li>
        </ul>
      </template>
      <ul v-if="results.length" class="rs-file-list" aria-label="导入结果"><li v-for="(item, index) in results" :key="`${item.filename}:${index}`"><span>{{ item.filename }}</span><small :class="item.success ? 'rs-success' : 'error'">{{ item.message }}</small></li></ul>
      <template #footer><p v-if="error" class="error rs-footer-error" role="alert">{{ error }}</p><div class="rs-dialog-footer"><span class="rs-label rs-small muted">导入后在智能体中选择<FieldHelp label="技能授权" :text="resourceHelp.bind" /></span><button v-if="importMode === 'local'" class="btn cta" type="button" :disabled="pending || !files.length" @click="upload">{{ pending ? '正在导入…' : `导入${files.length ? ` ${files.length} 个` : ''}技能包` }}</button><button v-else class="btn cta" type="button" :disabled="pending || !remotePreview || !selectedPaths.length || remotePreview.candidates.some(item => item.status === 'conflict' && selectedPaths.includes(item.path) && !overwritePaths.includes(item.path))" @click="importRemote">{{ pending ? '正在处理…' : `导入${selectedPaths.length ? ` ${selectedPaths.length} 个` : ''}技能` }}</button></div></template>
    </FormDrawer>
  </section>
</template>
<style src="../resource-surfaces.css"></style>
<style scoped>
.rs-import-source { display: grid; gap: 10px; }
.rs-import-source > .btn { justify-self: end; }
.rs-import-source textarea { font-family: var(--font-mono, monospace); resize: vertical; }
.rs-import-candidates { list-style: none; padding: 0; margin: 20px 0 0; }
.rs-import-candidates > li { padding: 14px 0; border-bottom: 1px solid var(--border); }
.rs-import-choice { display: flex; align-items: flex-start; gap: 10px; cursor: pointer; }
.rs-import-choice input,.rs-import-overwrite input { width: auto; flex-shrink: 0; margin: 3px 0 0; }
.rs-import-choice > span { display: grid; gap: 6px; min-width: 0; }
.rs-import-choice strong { font-size: 13px; }
.rs-import-choice small,.rs-import-choice code { color: var(--muted-foreground); font-size: 11px; overflow-wrap: anywhere; }
.rs-import-overwrite { display: flex; align-items: center; gap: 7px; margin: 10px 0 0 24px; font-size: 12px; }
</style>
