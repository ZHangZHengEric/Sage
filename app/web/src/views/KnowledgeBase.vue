<template>
  <div class="knowledge-base-page">

    <!-- 搜索和筛选 -->
    <div class="filters-section">

      <div class="kb-actions">
        <button class="btn-primary" @click="showAddKnowledgeBaseForm">
          <Plus :size="16" />
          {{ t('knowledgeBase.addKnowledgeBase') }}
        </button>
      </div>
    </div>

    <!-- 列表视图的过滤器和内容 -->
    <div v-if="viewMode === 'list'" class="list-content">
      <div class="kb-grid">
        <div v-for="kb in filteredKnowledgeBases" :key="kb.id" class="kb-card" @click="goToDetail(kb)">
          <!-- 卡片头部 -->
          <div class="kb-header">
            <div class="kb-icon" :class="getTypeIconClass(kb.dataSource)">
              <BookOpen :size="24" />
            </div>
            <div class="kb-info">
              <div class="kb-title-row">
                <div class="kb-title-left">
                  <h3 class="kb-name">{{ kb.name }}</h3>
                  <div class="kb-index">
                    <span class="index-name">{{ `${kb.index_name}` }}</span>
                    <button class="index-copy-btn" @click.stop="copyIndexName(kb)">
                      <Copy :size="14" />
                      {{ t('common.copy') || '复制' }}
                    </button>
                  </div>
                </div>
                <div class="kb-actions">

                  <div class="kb-status-indicator" :class="{ disabled: kb.disabled }">
                    <div class="status-dot"></div>
                    <span class="status-text">{{ kb.disabled ? t('knowledgeBase.disabled') : t('knowledgeBase.enabled') }}</span>
                  </div>
                </div>
              </div>
              <p class="kb-description">
                {{ getSimpleDescription(kb) }}
              </p>
            </div>
          </div>
          <!-- 类型信息 -->
          <div class="kb-type-section">
            <div class="type-badge" :class="kb.dataSource">
              <span class="type-icon">{{ getTypeIcon(kb.dataSource) }}</span>
              <span class="type-name">{{ getTypeName(kb.dataSource) }}</span>
            </div>
            <div class="type-details">
              <div class="kb-stats">
                <span class="stats-label">{{ t('knowledgeBase.documents') }}:</span>
                <span class="stats-value">{{ kb.docNum || 0 }}</span>
              </div>
              <div class="kb-stats">
                <span class="stats-label">{{ t('knowledgeBase.lastUpdated') }}:</span>
                <span class="stats-value">{{ formatDate(kb.createTime) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div v-if="filteredKnowledgeBases.length === 0" class="empty-state">
        <BookOpen :size="48" class="empty-icon" />
        <h3>{{ t('knowledgeBase.noKnowledgeBases') }}</h3>
        <p>{{ t('knowledgeBase.noKnowledgeBasesDesc') }}</p>
      </div>
    </div>
    <!-- 知识库添加视图 -->
    <KnowledgeBaseAdd 
      v-if="viewMode === 'add-kb'" 
      @success="handleKnowledgeBaseSuccess" 
      @cancel="backToList"
      ref="knowledgeBaseAddRef" 
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { BookOpen, Plus, RefreshCw, Copy } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { knowledgeBaseAPI } from '../api/knowledgeBase.js'
import KnowledgeBaseAdd from '../components/KnowledgeBaseAdd.vue'

// Composables
const { t } = useLanguage()

// Refs
const knowledgeBaseAddRef = ref(null)
const router = useRouter()

// State
const knowledgeBases = ref([])
const searchTerm = ref('')
const viewMode = ref('list') // 'list', 'add-kb'
const loading = ref(false)
const refreshingKbs = ref(new Set())

const filteredKnowledgeBases = computed(() => {
  if (!searchTerm.value.trim()) {
    return knowledgeBases.value
  }

  const query = searchTerm.value.toLowerCase()
  return knowledgeBases.value.filter(kb =>
    kb.name.toLowerCase().includes(query) ||
    (kb.intro && kb.intro.toLowerCase().includes(query))
  )
})

const uniqueTypes = computed(() => {
  const types = [...new Set(knowledgeBases.value.map(kb => kb.dataSource))]
  return types
})

// API Methods
const loadKnowledgeBases = async () => {
  try {
    loading.value = true
    const response = await knowledgeBaseAPI.getKnowledgeBases({ page_no: 1, page_size: 50 })
    if (response && response.success) {
      const { list } = response.data || {}
      knowledgeBases.value = Array.isArray(list) ? list : []
    }
  } catch (error) {
    console.error('Failed to load knowledge bases:', error)
    // 使用模拟数据作为后备
    knowledgeBases.value = [
      {
        id: '1',
        name: '产品文档知识库',
        type: 'document',
        description: '包含所有产品相关的文档和说明',
        document_count: 156,
        updated_at: '2024-01-15T10:30:00Z',
        disabled: false
      },
      {
        id: '2',
        name: '技术支持知识库',
        type: 'document',
        description: '常见问题解答和技术支持文档',
        document_count: 89,
        updated_at: '2024-01-14T15:45:00Z',
        disabled: false
      }
    ]
  } finally {
    loading.value = false
  }
}

// Methods
const showAddKnowledgeBaseForm = () => {
  // 重置表单
  if (knowledgeBaseAddRef.value) {
    knowledgeBaseAddRef.value.resetForm()
  }
  viewMode.value = 'add-kb'
}

const handleKnowledgeBaseSuccess = async () => {
  await loadKnowledgeBases()
  backToList()
}

// 获取简化的知识库描述
const getSimpleDescription = (kb) => {
  if (!kb) return t('knowledgeBase.noDescription')
  return kb.intro || t('knowledgeBase.noDescription')
}

// 获取类型图标类名
const getTypeIconClass = (type) => {
  switch (type?.toLowerCase()) {
    case 'document':
      return 'type-document'
    case 'qa':
      return 'type-qa'
    case 'code':
      return 'type-code'
    default:
      return 'type-default'
  }
}

// 获取类型图标
const getTypeIcon = (type) => {
  switch (type?.toLowerCase()) {
    case 'document':
      return '📄'
    case 'qa':
      return '❓'
    case 'code':
      return '💻'
    default:
      return '📚'
  }
}

// 获取类型名称
const getTypeName = (type) => {
  switch (type?.toLowerCase()) {
    case 'document':
      return t('knowledgeBase.documentType')
    case 'qa':
      return t('knowledgeBase.qaType')
    case 'code':
      return t('knowledgeBase.codeType')
    default:
      return t('knowledgeBase.unknownType')
  }
}

// 格式化日期
const formatDate = (dateString) => {
  if (!dateString) return '-'
  const date = new Date(dateString)
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const backToList = () => {
  viewMode.value = 'list'
}

const goToDetail = (kb) => {
  if (!kb || !kb.id) return
  router.push({ name: 'KnowledgeBaseDetail', params: { kdbId: kb.id } })
}

const copyIndexName = async (kb) => {
  const text = kb?.index_name || ''
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return
    }
  } catch (_) {}
  const ta = document.createElement('textarea')
  ta.value = text
  document.body.appendChild(ta)
  ta.select()
  try { document.execCommand('copy') } catch (_) {}
  document.body.removeChild(ta)
}

// 生命周期
onMounted(() => {
  loadKnowledgeBases()
})
</script>

<style scoped>
.knowledge-base-page {
  padding: 1.5rem;
  min-height: 100vh;
  background: transparent;
}

/* 搜索和筛选区域样式 */
.filters-section {
  margin-bottom: 24px;
  padding: 20px;
  background: white;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.search-box {
  position: relative;
  max-width: 400px;
}

.search-input {
  width: 100%;
  padding: 12px 16px 12px 44px;
  border: 2px solid rgba(0, 0, 0, 0.1);
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.5;
  background: #fafafa;
  transition: all 0.2s ease;
  outline: none;
}

.search-input:focus {
  border-color: #667eea;
  background: white;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

.search-input::placeholder {
  color: rgba(0, 0, 0, 0.5);
  font-weight: 400;
}

.search-box::before {
  content: '🔍';
  position: absolute;
  left: 16px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 16px;
  color: rgba(0, 0, 0, 0.4);
  pointer-events: none;
  z-index: 1;
}

.list-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  max-height: calc(100vh - 120px);
  background: white;
}

.kb-actions {
  display: flex;
  gap: 12px;
}

.btn-primary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border: none;
  border-radius: 8px;
  background: #667eea;
  color: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-primary:hover {
  background: #5a6fd8;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px 32px;
  text-align: center;
  color: rgba(0, 0, 0, 0.7);
}

.empty-icon {
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-state h3 {
  margin: 0 0 8px 0;
  font-size: 18px;
  font-weight: 600;
  color: #333333;
}

.empty-state p {
  margin: 0;
  font-size: 14px;
  line-height: 1.5;
  color: rgba(0, 0, 0, 0.7);
}

.kb-grid {
  padding: 24px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 20px;
}

.kb-card {
  background: white;
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 12px;
  padding: 20px;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.kb-card:hover {
  border-color: #667eea;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}

.kb-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.kb-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.kb-icon.type-document {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.kb-icon.type-qa {
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
}

.kb-icon.type-code {
  background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
}

.kb-icon.type-default {
  background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
}

.kb-info {
  flex: 1;
  min-width: 0;
}

.kb-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  gap: 12px;
}

.kb-title-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.kb-index {
  display: flex;
  align-items: center;
  gap: 6px;
}

.index-name {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
  color: #555;
  background: #f2f2f2;
  border: 1px solid rgba(0,0,0,0.1);
  border-radius: 4px;
  padding: 2px 6px;
}

.index-copy-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  border: none;
  border-radius: 4px;
  padding: 2px 6px;
  background: rgba(102, 126, 234, 0.1);
  color: #667eea;
  cursor: pointer;
}

.index-copy-btn:hover {
  background: rgba(102, 126, 234, 0.2);
}

.kb-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.action-btn {
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
  flex-shrink: 0;
}

.action-btn:hover:not(:disabled) {
  background: rgba(102, 126, 234, 0.2);
  transform: scale(1.05);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.refresh-btn .spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.kb-name {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #333333;
  word-break: break-word;
}

.kb-status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #4ade80;
}

.kb-status-indicator.disabled .status-dot {
  background: #ef4444;
}

.status-text {
  font-size: 12px;
  font-weight: 500;
  color: rgba(0, 0, 0, 0.7);
}

.kb-description {
  margin: 0;
  font-size: 14px;
  color: rgba(0, 0, 0, 0.7);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.kb-type-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(0, 0, 0, 0.1);
}

.type-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  width: fit-content;
}

.type-badge.document {
  background: rgba(102, 126, 234, 0.1);
  color: #667eea;
  border: 1px solid rgba(102, 126, 234, 0.2);
}

.type-badge.qa {
  background: rgba(79, 172, 254, 0.1);
  color: #4facfe;
  border: 1px solid rgba(79, 172, 254, 0.2);
}

.type-badge.code {
  background: rgba(67, 233, 123, 0.1);
  color: #43e97b;
  border: 1px solid rgba(67, 233, 123, 0.2);
}

.type-icon {
  font-size: 14px;
}

.type-name {
  letter-spacing: 0.5px;
}

.type-details {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.kb-stats {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.stats-label {
  font-weight: 600;
  color: rgba(0, 0, 0, 0.7);
  min-width: 60px;
}

.stats-value {
  color: #333333;
  flex: 1;
}
</style>