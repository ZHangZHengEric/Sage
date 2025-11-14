<template>
  <div class="knowledge-base-detail">
    <div class="header">
      <div class="header-left">
        <h2 class="title">{{ kbInfo.name || 'Knowledge Base' }}</h2>
        <p class="intro">{{ kbInfo.intro || t('knowledgeBase.noDescription') }}</p>
      </div>
      <div class="header-right">
        <button class="btn-link" @click="goBack">{{ t('knowledgeBase.backToList') }}</button>
      </div>
    </div>

    <div class="tabs">
      <button :class="['tab', { active: activeTab === 'documents' }]" @click="activeTab = 'documents'">{{
        t('knowledgeBase.documents') }}</button>
      <button :class="['tab', { active: activeTab === 'recall' }]" @click="activeTab = 'recall'">召回测试</button>
      <button :class="['tab', { active: activeTab === 'settings' }]" @click="activeTab = 'settings'">设置</button>
    </div>

    <div class="tab-content" v-if="activeTab === 'documents'">
      <div class="doc-filter">
        <input v-model="docQueryName" class="form-input" placeholder="关键词" />
        <button class="btn-primary" :disabled="docLoading" @click="loadDocs">查询</button>
        <input ref="fileInputRef" type="file" multiple style="display:none" @change="onFileChange"
          accept=".doc,.docx,.pdf,.txt,.json,.eml,.ppt,.pptx,.xlsx,.xls,.csv,.md" />
        <button class="btn-primary ml-auto" :disabled="docLoading" @click="triggerSelectFiles">上传文件</button>
      </div>
      <div class="doc-list">
        <table class="doc-table">
          <thead>
            <tr>
              <th>名称</th>
              <th>状态</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in docList" :key="d.id">
              <td>{{ d.doc_name }}</td>
              <td>
                <div class="status-cell" :title="statusText(d.status)">
                  <Clock v-if="d.status === 0" :size="16" class="status-icon pending" />
                  <Loader v-else-if="d.status === 1" :size="16" class="status-icon processing spin" />
                  <CheckCircle v-else-if="d.status === 2" :size="16" class="status-icon success" />
                  <XCircle v-else-if="d.status === 3" :size="16" class="status-icon failed" />
                  <span v-else>{{ statusText(d.status) }}</span>
                </div>
              </td>
              <td>{{ formatTime(d.create_time) }}</td>
              <td>
                <div class="action-cell">
                  <button class="icon-btn danger" :disabled="docLoading" @click="deleteDoc(d)" title="删除">
                    <Trash2 :size="16" />
                  </button>
                  <button class="icon-btn primary" :disabled="docLoading" @click="redoDoc(d)" title="重做">
                    <RotateCcw :size="16" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="pager">
          <span class="total">{{ t('common.total') }}: {{ docTotal }}</span>
          <button class="btn" :disabled="docPageNo <= 1 || docLoading" @click="prevPage">上一页</button>
          <span>{{ docPageNo }} / {{ totalPages }}</span>
          <button class="btn" :disabled="docPageNo >= totalPages || docLoading" @click="nextPage">下一页</button>
        </div>
      </div>
    </div>

    <div class="tab-content" v-else-if="activeTab === 'recall'">
      <div class="recall-ops">
        <input v-model="recallQuery" class="form-input" placeholder="输入问题或关键词" />
        <button class="btn-primary" :disabled="recallLoading" @click="runRecall">查询</button>
      </div>
      <div class="recall-list">
        <ul class="recall-items">
          <li v-for="r in recallResults" :key="makeRecallKey(r)" class="recall-item">
            <div class="recall-head">
              <div class="recall-title">{{ r.title }}</div>
              <div class="recall-meta">Score: {{ (r.score ?? 0).toFixed(4) }} </div>
            </div>
            <div class="recall-snippet">
              <ReactMarkdown :content="r.doc_content" />
            </div>

          </li>
        </ul>
      </div>
    </div>

    <div class="tab-content" v-else>
      <form class="settings-form" @submit.prevent="saveSettings">
        <div class="form-group">
          <label class="form-label">{{ t('knowledgeBase.name') }}</label>
          <input v-model="editForm.name" class="form-input" />
        </div>
        <div class="form-group">
          <label class="form-label">{{ t('knowledgeBase.description') }}</label>
          <textarea v-model="editForm.intro" rows="3" class="form-textarea"></textarea>
        </div>
        <div class="actions">
          <button type="submit" class="btn-primary" :disabled="saving">{{ saving ? t('common.save') : t('common.save')
            }}</button>
          <button type="button" class="btn-danger" :disabled="saving" @click="confirmDelete">{{ t('common.delete')
            }}</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { Trash2, RotateCcw, Clock, Loader, CheckCircle, XCircle } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import { useLanguage } from '../utils/i18n.js'
import { knowledgeBaseAPI } from '../api/knowledgeBase.js'
import ReactMarkdown from '../components/chat/ReactMarkdown.vue'

const { t } = useLanguage()
const route = useRoute()
const router = useRouter()

const kdbId = route.params.kdbId
const activeTab = ref('documents')
const kbInfo = ref({})
const saving = ref(false)
const editForm = ref({ name: '', intro: '' })
const docList = ref([])
const docLoading = ref(false)
const docQueryName = ref('')
const docPageNo = ref(1)
const docPageSize = ref(10)
const docTotal = ref(0)
const selectedFiles = ref([])
const fileInputRef = ref(null)
const docRefreshTimer = ref(null)
const recallQuery = ref('')
const recallResults = ref([])
const recallLoading = ref(false)
const recallExpandedMap = ref({})
const allowedExts = ['.doc', '.docx', '.pdf', '.txt', '.json', '.eml', '.ppt', '.pptx', '.xlsx', '.xls', '.csv', '.md']

const loadInfo = async () => {
  const res = await knowledgeBaseAPI.getKnowledgeBase(kdbId)
  if (res && res.success) {
    kbInfo.value = res.data || {}
    editForm.value.name = kbInfo.value.name || ''
    editForm.value.intro = kbInfo.value.intro || ''
  }
}

const saveSettings = async () => {
  try {
    saving.value = true
    await knowledgeBaseAPI.updateKnowledgeBase(kdbId, { name: editForm.value.name, intro: editForm.value.intro })
    await loadInfo()
  } finally {
    saving.value = false
  }
}

const confirmDelete = async () => {
  const ok = window.confirm(t('knowledgeBase.deleteConfirm').replace('{name}', kbInfo.value.name || ''))
  if (!ok) return
  const res = await knowledgeBaseAPI.deleteKnowledgeBase(kdbId)
  if (res && res.success) {
    goBack()
  }
}

const goBack = () => {
  router.push({ name: 'KnowledgeBase' })
}

onMounted(() => {
  loadInfo()
  loadDocs()
  docRefreshTimer.value = setInterval(() => {
    if (activeTab.value === 'documents' && !docLoading.value) {
      loadDocs()
    }
  }, 5000)
})

onUnmounted(() => {
  if (docRefreshTimer.value) {
    clearInterval(docRefreshTimer.value)
    docRefreshTimer.value = null
  }
})

const loadDocs = async () => {
  try {
    docLoading.value = true
    const res = await knowledgeBaseAPI.getDocuments({ kdb_id: kdbId, query_name: docQueryName.value, page: docPageNo.value, page_size: docPageSize.value })
    if (res && res.success) {
      const { list = [], total = 0 } = res.data || {}
      docList.value = list
      docTotal.value = total
    }
  } finally {
    docLoading.value = false
  }
}

const onFileChange = (e) => {
  const fl = Array.from((e.target && e.target.files) || [])
  const filtered = fl.filter((f) => {
    const name = f.name || ''
    const idx = name.lastIndexOf('.')
    const ext = idx >= 0 ? name.slice(idx).toLowerCase() : ''
    return allowedExts.includes(ext)
  })
  if (filtered.length !== fl.length) {
    window.alert('仅支持上传以下文件类型：' + allowedExts.join(', '))
  }
  selectedFiles.value = filtered
  if (selectedFiles.value.length) {
    addByFiles()
  } else {
    if (fileInputRef.value) fileInputRef.value.value = ''
  }
}

const triggerSelectFiles = () => {
  if (fileInputRef.value) fileInputRef.value.click()
}

const addByFiles = async () => {
  if (!selectedFiles.value.length) return
  try {
    docLoading.value = true
    const res = await knowledgeBaseAPI.addDocumentsByFiles({ kdb_id: kdbId, files: selectedFiles.value, override: false })
    if (res && res.success) {
      await loadDocs()
      selectedFiles.value = []
      if (fileInputRef.value) fileInputRef.value.value = ''
    }
  } finally {
    docLoading.value = false
  }
}

const deleteDoc = async (d) => {
  const res = await knowledgeBaseAPI.deleteDocument(d.id)
  if (res && res.success) {
    await loadDocs()
  }
}

const redoDoc = async (d) => {
  const res = await knowledgeBaseAPI.redoDocument(d.id)
  if (res && res.success) {
    await loadDocs()
  }
}

const prevPage = () => {
  if (docPageNo.value <= 1) return
  docPageNo.value -= 1
  loadDocs()
}

const nextPage = () => {
  const tp = totalPages.value
  if (docPageNo.value >= tp) return
  docPageNo.value += 1
  loadDocs()
}

const totalPages = computed(() => {
  return Math.max(1, Math.ceil(docTotal.value / docPageSize.value))
})

const formatTime = (iso) => {
  try {
    return new Date(iso).toLocaleString()
  } catch (e) {
    return iso
  }
}

const runRecall = async () => {
  try {
    recallLoading.value = true
    const res = await knowledgeBaseAPI.retrieve({ kdb_id: kdbId, query: recallQuery.value, top_k: 10 })
    if (res && res.success) {
      const list = Array.isArray(res.data) ? res.data : []
      recallResults.value = list
    }
  } finally {
    recallLoading.value = false
  }
}

const makeRecallKey = (r) => `${r.doc_id || ''}-${r.doc_segment_id || ''}-${r.start || 0}-${r.end || 0}`
const isRecallExpanded = (r) => !!recallExpandedMap.value[makeRecallKey(r)]
const toggleRecall = (r) => {
  const k = makeRecallKey(r)
  recallExpandedMap.value[k] = !recallExpandedMap.value[k]
}

const buildExpanded = (r) => {
  const text = r.full_content || ''
  return highlightWindow(text, r.start, r.end, text.length, text.length)
}

const highlightWindow = (text, start, end, before = 120, after = 160) => {
  if (!text) return ''
  if (typeof start !== 'number' || typeof end !== 'number') {
    return text
  }
  const s = Math.max(0, Math.min(start, text.length))
  const e = Math.max(s, Math.min(end, text.length))
  const preStart = Math.max(0, s - before)
  const postEnd = Math.min(text.length, e + after)
  const prefixEllipsis = preStart > 0 ? '…' : ''
  const suffixEllipsis = postEnd < text.length ? '…' : ''
  return `${prefixEllipsis}${text.slice(preStart, s)}<span class="recall-highlight">${text.slice(s, e)}</span>${text.slice(e, postEnd)}${suffixEllipsis}`
}

const statusText = (s) => {
  switch (s) {
    case 0: return t('knowledgeBase.status.pending')
    case 1: return t('knowledgeBase.status.processing')
    case 2: return t('knowledgeBase.status.success')
    case 3: return t('knowledgeBase.status.failed')
    default: return `${s}`
  }
}
</script>

<style scoped>
.knowledge-base-detail {
  padding: 24px;
}

.header {
  background: white;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.header-right {
  display: flex;
  align-items: flex-start;
}

.title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.intro {
  margin: 8px 0 0 0;
  color: rgba(0, 0, 0, 0.7);
}

.btn-link {
  background: none;
  border: none;
  color: #667eea;
  cursor: pointer;
  margin-bottom: 8px;
}

.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.tab {
  padding: 8px 12px;
  border: 1px solid rgba(0, 0, 0, 0.1);
  background: white;
  border-radius: 8px;
  cursor: pointer;
}

.tab.active {
  background: #667eea;
  color: white;
  border-color: #667eea;
}

.tab-content {
  background: white;
  border-radius: 12px;
  padding: 16px;
}

.placeholder {
  color: rgba(0, 0, 0, 0.6);
}

.settings-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
   width: 50%;

}

.form-label {
  font-size: 14px;
  font-weight: 600;
}

.form-input,
.form-textarea {
  padding: 10px 12px;
  border: 1px solid rgba(0, 0, 0, 0.2);
  border-radius: 8px;
}

.actions {
  display: flex;
  gap: 8px;
}

.btn-primary {
  background: #667eea;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
}

.btn-danger {
  background: #ef4444;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
}

.doc-ops {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  align-items: start;
  margin-bottom: 12px;
}

.doc-filter {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.doc-list {
  overflow: auto;
}

.doc-table {
  width: 100%;
  border-collapse: collapse;
}

.doc-table th,
.doc-table td {
  border-bottom: 1px solid rgba(0, 0, 0, 0.1);
  padding: 8px;
  text-align: left;
}

.action-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 6px;
  background: rgba(102, 126, 234, 0.1);
  color: #667eea;
  cursor: pointer;
  transition: all 0.2s ease;
}

.icon-btn:hover:not(:disabled) {
  background: rgba(102, 126, 234, 0.2);
  transform: scale(1.05);
}

.icon-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.icon-btn.danger {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.icon-btn.danger:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.2);
}

.icon-btn.primary {
  background: rgba(102, 126, 234, 0.1);
  color: #667eea;
}

.pager {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 12px;
  justify-content: center;
}

.btn {
  border: 1px solid rgba(0, 0, 0, 0.2);
  background: white;
  border-radius: 6px;
  padding: 6px 10px;
  cursor: pointer;
}

.recall-ops {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.recall-items {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 8px;
}

.recall-item {
  padding: 8px;
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 8px;
}

.recall-head {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 8px;
}

.recall-title {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recall-meta {
  color: rgba(218, 12, 12, 0.875);
  font-size: 14px;
}

.recall-snippet {
  margin-top: 6px;
  border: 1px solid rgba(32, 199, 37, 0.809);
  border-radius: 8px;
  padding: 8px;
}

.recall-expanded {
  margin-top: 8px;
}

.recall-section {
  margin-top: 8px;
}

.recall-subtitle {
  font-size: 12px;
  color: rgba(0, 0, 0, 0.6);
  margin-bottom: 4px;
}

:deep(.recall-highlight) {
  color: #ef4444;
}

.status-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-icon {
  display: inline-flex;
}

.status-icon.pending {
  color: #9ca3af;
}

.status-icon.processing {
  color: #667eea;
}

.status-icon.success {
  color: #10b981;
}

.status-icon.failed {
  color: #ef4444;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

.spin {
  animation: spin 1s linear infinite;
}
</style>