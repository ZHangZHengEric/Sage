<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { marked } from 'marked'
import { api, isForeign } from '../api.js'
import { formatBytes, markdownBody, resourceHelp } from '../resource-presentation.js'
import FieldHelp from './FieldHelp.vue'
import AppIcon from './AppIcon.vue'
import FormDrawer from './FormDrawer.vue'

const props = defineProps({ item: { type: Object, required: true } })
const emit = defineEmits(['removed'])
const open = ref(false), tab = ref('overview'), deleting = ref(false), confirmDelete = ref(false), deleteError = ref('')
const busy = ref(false)
const error = ref('')
const files = ref([])
const selected = ref('')
const content = ref('')
const kind = ref('text')
const previewUrl = ref('')
const previewMode = ref('preview')
const hexLimit = ref(4096)
const binary = ref(null)
const collapsed = ref(new Set())
let requestIndex = 0

const selectedFile = computed(() => files.value.find(file => file.path === selected.value))
const tree = computed(() => {
  const rows = []
  const folders = new Set()
  for (const file of files.value) {
    const parts = file.path.split('/')
    for (let i = 1; i < parts.length; i++) folders.add(parts.slice(0, i).join('/'))
  }
  for (const path of folders) rows.push({ path, folder: true, depth: path.split('/').length - 1 })
  for (const file of files.value) rows.push({ ...file, folder: false, depth: file.path.split('/').length - 1 })
  return rows.sort((a, b) => {
    const aParts = a.path.split('/'), bParts = b.path.split('/')
    for (let i = 0; i < Math.min(aParts.length, bParts.length); i++) {
      if (aParts[i] !== bParts[i]) return aParts[i].localeCompare(bParts[i])
    }
    return aParts.length - bParts.length
  }).filter(row => !row.path.split('/').slice(0, -1).some((_, index, parts) => collapsed.value.has(parts.slice(0, index + 1).join('/'))))
})
const hexRows = computed(() => {
  if (!binary.value) return []
  const bytes = binary.value.subarray(0, hexLimit.value)
  const rows = []
  for (let offset = 0; offset < bytes.length; offset += 16) {
    const slice = bytes.subarray(offset, offset + 16)
    rows.push(`${offset.toString(16).padStart(8, '0')}  ${Array.from(slice, value => value.toString(16).padStart(2, '0')).join(' ').padEnd(47)}  ${Array.from(slice, value => value >= 32 && value < 127 ? String.fromCharCode(value) : '.').join('')}`)
  }
  return rows
})

function clearPreview() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  content.value = ''
  binary.value = null
}

async function inspect() {
  const index = ++requestIndex
  tab.value = 'overview'; confirmDelete.value = false; deleteError.value = ''; collapsed.value = new Set()
  open.value = true
  busy.value = true
  error.value = ''
  files.value = []
  selected.value = ''
  clearPreview()
  try {
    const nextFiles = await api.skillFiles(props.item.skill_id, props.item._owner)
    if (index !== requestIndex) return
    files.value = nextFiles
    await selectFile(files.value.find(file => file.path === 'SKILL.md')?.path || files.value[0]?.path)
  } catch (exc) { if (index === requestIndex) error.value = exc.message }
  finally { if (index === requestIndex) busy.value = false }
}

async function selectFile(path) {
  if (!path) return
  const index = ++requestIndex
  selected.value = path
  previewMode.value = 'preview'
  hexLimit.value = 4096
  clearPreview()
  busy.value = true
  error.value = ''
  try {
    const { blob } = await api.skillFile(props.item.skill_id, path, props.item._owner)
    if (index !== requestIndex) return
    const lower = path.toLowerCase()
    const image = /\.(png|jpe?g|gif|webp|avif|bmp|svg)$/.test(lower)
    const pdf = lower.endsWith('.pdf')
    const audio = /\.(mp3|m4a|wav|ogg|flac)$/.test(lower)
    const video = /\.(mp4|webm|mov)$/.test(lower)
    if (image || pdf || audio || video) {
      kind.value = image ? 'image' : pdf ? 'pdf' : audio ? 'audio' : 'video'
      const mime = lower.endsWith('.svg') ? 'image/svg+xml' : lower.endsWith('.pdf') ? 'application/pdf'
        : lower.endsWith('.png') ? 'image/png' : lower.endsWith('.webp') ? 'image/webp'
          : lower.endsWith('.gif') ? 'image/gif' : lower.endsWith('.avif') ? 'image/avif'
            : lower.endsWith('.mp3') ? 'audio/mpeg' : lower.endsWith('.mp4') ? 'video/mp4'
              : lower.endsWith('.webm') ? 'video/webm' : lower.endsWith('.ogg') ? 'audio/ogg'
                : lower.endsWith('.wav') ? 'audio/wav' : lower.endsWith('.m4a') ? 'audio/mp4'
                  : lower.endsWith('.mov') ? 'video/quicktime' : lower.endsWith('.flac') ? 'audio/flac'
                    : lower.endsWith('.bmp') ? 'image/bmp' : 'image/jpeg'
      previewUrl.value = URL.createObjectURL(new Blob([blob], { type: mime }))
    } else {
      const bytes = new Uint8Array(await blob.arrayBuffer())
      if (index !== requestIndex) return
      try {
        if (bytes.includes(0)) throw new Error('binary')
        content.value = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
        kind.value = lower.endsWith('.md') || lower.endsWith('.markdown') ? 'markdown' : 'text'
      } catch {
        kind.value = 'binary'
        binary.value = bytes
      }
    }
  } catch (exc) { if (index === requestIndex) error.value = exc.message }
  finally { if (index === requestIndex) busy.value = false }
}

function toggleFolder(path) {
  const next = new Set(collapsed.value)
  if (next.has(path)) next.delete(path)
  else next.add(path)
  collapsed.value = next
}

function safeMarkdown(source) {
  const documentNode = new DOMParser().parseFromString(marked.parse(source, { async: false, gfm: true }), 'text/html')
  const allowed = new Set(['A', 'BLOCKQUOTE', 'BR', 'CODE', 'DEL', 'EM', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'HR', 'LI', 'OL', 'P', 'PRE', 'STRONG', 'TABLE', 'TBODY', 'TD', 'TH', 'THEAD', 'TR', 'UL'])
  for (const node of [...documentNode.body.querySelectorAll('*')]) {
    if (['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'SVG', 'MATH'].includes(node.tagName)) { node.remove(); continue }
    if (!allowed.has(node.tagName)) { node.replaceWith(...node.childNodes); continue }
    const href = node.tagName === 'A' ? node.getAttribute('href') : null
    for (const attribute of [...node.attributes]) node.removeAttribute(attribute.name)
    if (node.tagName === 'A') {
      if (href && /^https?:\/\//i.test(href)) {
        node.setAttribute('href', href)
        node.setAttribute('target', '_blank')
        node.setAttribute('rel', 'noopener noreferrer')
      }
    }
  }
  return documentNode.body.innerHTML
}

const markdownHtml = computed(() => kind.value === 'markdown' && previewMode.value === 'preview' ? safeMarkdown(selected.value === 'SKILL.md' ? markdownBody(content.value) : content.value) : '')
async function setTab(value) {
  tab.value = value
  if (value === 'overview' && selected.value !== 'SKILL.md' && files.value.some(file => file.path === 'SKILL.md')) await selectFile('SKILL.md')
}
async function remove() {
  if (isForeign(props.item) || deleting.value) return
  deleting.value = true; deleteError.value = ''
  try { await api.deleteSkill(props.item.skill_id); close(); emit('removed') }
  catch (exc) { deleteError.value = exc.message }
  finally { deleting.value = false }
}
function close() { open.value = false; requestIndex++; busy.value = false; clearPreview() }
onBeforeUnmount(clearPreview)
</script>

<template>
  <button class="btn ghost" type="button" :aria-label="`查看 ${item.name} 详情`" @click="inspect">查看<AppIcon name="chevron" /></button>
  <FormDrawer :model-value="open" title="技能详情" centered panel-class="resource-dialog skill-dialog" :busy="deleting" @update:model-value="close">
    <template v-if="open">
      <div class="rs-identity"><span class="rs-icon"><AppIcon name="skill" /></span><div><h2>{{ item.name }}</h2><div class="rs-technical">{{ item._owner?.username || '我的技能' }}</div></div><span v-if="isForeign(item)" class="rs-badge readonly">只读</span><span v-else class="rs-badge">可用</span></div>
      <nav class="rs-detail-tabs" aria-label="技能详情分区"><button type="button" :aria-pressed="tab === 'overview'" @click="setTab('overview')">说明</button><button type="button" :aria-pressed="tab === 'files'" @click="setTab('files')">文件</button></nav>
      <section v-if="tab === 'overview'" class="rs-section"><dl class="rs-metadata"><div><dt>所有者</dt><dd>{{ item._owner?.username || '我' }}</dd></div><div><dt>修订</dt><dd class="rs-label">{{ item.revision ?? '—' }}<FieldHelp label="修订编号" :text="resourceHelp.revision" /></dd></div><div><dt>文件</dt><dd>{{ item.file_count ?? files.length }} 个 · {{ formatBytes(item.total_bytes ?? files.reduce((sum, file) => sum + file.size, 0)) }}</dd></div></dl></section>
      <div class="skill-browser" :class="{ overview: tab === 'overview' }">
        <aside v-if="tab === 'files'" class="skill-files" aria-label="技能文件">
          <div class="file-heading"><span class="rs-label">文件<FieldHelp label="技能文件" :text="resourceHelp.files" /></span><span>{{ files.length }}</span></div>
          <div v-for="entry in tree" :key="entry.path" class="tree-entry"><button type="button" class="tree-button" :class="{ active: !entry.folder && selected === entry.path }" :style="{ paddingLeft: `${entry.depth * 16 + 12}px` }" :aria-label="entry.path" :aria-current="!entry.folder && selected === entry.path ? 'true' : undefined" :aria-expanded="entry.folder ? !collapsed.has(entry.path) : undefined" @click="entry.folder ? toggleFolder(entry.path) : selectFile(entry.path)"><AppIcon :name="entry.folder ? 'folder' : 'file'" /><span>{{ entry.path.split('/').at(-1) }}</span></button></div>
        </aside>
        <div class="file-viewer">
          <div class="file-toolbar"><span class="file-path">{{ selected || '选择文件' }}</span><span v-if="selectedFile" class="file-size">{{ formatBytes(selectedFile.size) }}</span><div v-if="kind === 'markdown' && selected" class="view-switch" aria-label="Markdown 查看方式"><button type="button" :aria-pressed="previewMode === 'preview'" @click="previewMode = 'preview'">预览</button><button type="button" :aria-pressed="previewMode === 'source'" @click="previewMode = 'source'">源码</button></div></div>
          <p v-if="busy" class="viewer-state" role="status">正在加载…</p>
          <div v-else-if="error" class="viewer-state error" role="alert">{{ error }}<button class="btn ghost" type="button" @click="files.length ? selectFile(selected) : inspect()">重新加载</button></div>
          <div v-else-if="selected" class="file-content">
            <div v-if="kind === 'markdown' && previewMode === 'preview'" class="markdown-preview" v-html="markdownHtml" />
            <pre v-else-if="kind === 'text' || kind === 'markdown'" class="source-code"><code>{{ content }}</code></pre>
            <img v-else-if="kind === 'image'" class="image-preview" :src="previewUrl" :alt="selected" />
            <iframe v-else-if="kind === 'pdf'" class="pdf-preview" :src="previewUrl" :title="selected" />
            <audio v-else-if="kind === 'audio'" :src="previewUrl" controls />
            <video v-else-if="kind === 'video'" class="video-preview" :src="previewUrl" controls />
            <div v-else-if="kind === 'binary'" class="binary-preview"><pre class="source-code"><code>{{ hexRows.join('\n') }}</code></pre><button v-if="binary && hexLimit < binary.length" class="btn ghost" type="button" @click="hexLimit += 4096">显示更多字节</button></div>
          </div>
          <p v-else-if="!files.length && !busy" class="viewer-state">暂无文件</p>
        </div>
      </div>
    </template>
    <template #footer><p v-if="deleteError" class="error rs-footer-error" role="alert">{{ deleteError }}</p><div class="rs-dialog-footer">
      <template v-if="confirmDelete"><span class="rs-small">确认删除 {{ item.name }}？</span><div class="row"><button class="btn ghost" type="button" :disabled="deleting" @click="confirmDelete = false">取消</button><button class="btn rs-destructive" type="button" :disabled="deleting" @click="remove">{{ deleting ? '正在删除…' : '确认删除' }}</button></div></template>
      <template v-else><button v-if="!isForeign(item)" class="btn ghost rs-danger" type="button" :disabled="busy" @click="confirmDelete = true"><AppIcon name="trash" />删除技能</button><span v-else class="rs-small muted rs-label">只读<FieldHelp label="只读权限" :text="resourceHelp.readonly" /></span><div class="rs-label"><FieldHelp label="技能授权" :text="resourceHelp.bind" /><router-link class="btn cta" to="/agents" @click="close">前往智能体配置<AppIcon name="chevron" /></router-link></div></template>
    </div></template>
  </FormDrawer>
</template>

<style scoped>
.skill-browser { display: grid; grid-template-columns: minmax(170px, 210px) minmax(0, 1fr); min-height: 360px; border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
.skill-browser.overview { display: block; }
.skill-files { min-width: 0; border-right: 1px solid var(--border); background: var(--background); overflow: auto; }
.file-heading { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; font-size: 11px; font-weight: 600; color: var(--muted-foreground); }
.tree-button { display: flex; align-items: center; gap: 7px; width: 100%; min-height: 34px; padding: 7px 12px; border: 0; background: transparent; color: var(--foreground); text-align: left; font-size: 11px; }
.tree-button:hover, .tree-button.active { background: var(--muted); }
.tree-button.active { color: var(--primary); font-weight: 600; }
.tree-button:focus-visible { outline: 2px solid var(--primary); outline-offset: -2px; }
.tree-button .app-icon { width: 14px; height: 14px; color: var(--muted-foreground); }
.tree-button span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-viewer { min-width: 0; background: var(--card); }
.file-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; min-height: 47px; padding: 9px 14px; border-bottom: 1px solid var(--border); }
.file-path { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; font-weight: 500; }
.file-size { flex: none; color: var(--muted-foreground); font-size: 10px; }
.file-toolbar .view-switch { flex: none; margin-left: auto; }
.viewer-state { display: flex; align-items: center; gap: 12px; padding: 20px; font-size: 13px; }
.file-content { min-height: 260px; }
.source-code { margin: 0; padding: 20px; overflow: auto; white-space: pre; font-size: 12px; line-height: 1.8; tab-size: 2; }
.markdown-preview { padding: 22px 26px; overflow-wrap: anywhere; line-height: 1.9; font-size: 14px; }
.markdown-preview :deep(h1) { font-size: 23px; margin: 0 0 20px; }
.markdown-preview :deep(h2) { font-size: 19px; margin: 24px 0 12px; }
.markdown-preview :deep(h3) { font-size: 15px; margin: 22px 0 10px; }
.markdown-preview :deep(pre) { overflow: auto; padding: 14px; background: var(--background); border-radius: 10px; }
.markdown-preview :deep(code) { font-size: .9em; }
.markdown-preview :deep(table) { border-collapse: collapse; display: block; overflow: auto; }
.markdown-preview :deep(th), .markdown-preview :deep(td) { border: 1px solid var(--border); padding: 6px 10px; }
.markdown-preview :deep(blockquote) { margin: 18px 0; padding: 10px 15px; border-left: 2px solid var(--primary); background: var(--background); color: var(--muted-foreground); }
.image-preview, .video-preview { display: block; max-width: 100%; max-height: 65vh; margin: 20px auto; }
.pdf-preview { width: 100%; height: 65vh; border: 0; }
.binary-preview .btn { margin: 0 16px 16px; }
@media (max-width: 760px) { .skill-browser { grid-template-columns: 1fr; } .skill-files { max-height: 165px; border-right: 0; border-bottom: 1px solid var(--border); } .file-content { min-height: 250px; } .markdown-preview { padding: 20px; font-size: 13px; } }
</style>
