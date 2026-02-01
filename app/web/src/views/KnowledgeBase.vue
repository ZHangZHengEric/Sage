<template>
  <div class="container py-6 space-y-6 h-[calc(100vh-60px)]">
    <!-- Header & Filters -->
    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-card p-4 rounded-lg border shadow-sm" v-if="viewMode === 'list'">
      <div class="relative w-full sm:w-80">
        <Search class="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          v-model="searchTerm"
          :placeholder="t('knowledgeBase.search') || 'Search...'"
          class="pl-9"
        />
      </div>
      
      <Button @click="showAddKnowledgeBaseForm">
        <Plus class="mr-2 h-4 w-4" />
        {{ t('knowledgeBase.addKnowledgeBase') }}
      </Button>
    </div>

    <!-- List Content -->
    <div v-if="viewMode === 'list'" class="space-y-6">
      <!-- Grid -->
      <div v-if="filteredKnowledgeBases.length > 0" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <Card 
          v-for="kb in filteredKnowledgeBases" 
          :key="kb.id" 
          class="cursor-pointer hover:shadow-md transition-all duration-300 group border-muted/60 hover:border-primary/50"
          @click="goToDetail(kb)"
        >
          <CardHeader class="pb-3">
            <div class="flex justify-between items-start">
              <div class="flex items-center gap-3">
                <div 
                  class="p-2 rounded-lg bg-primary/10 text-primary group-hover:bg-primary group-hover:text-primary-foreground transition-colors duration-300"
                >
                  <BookOpen class="h-5 w-5" />
                </div>
                <div>
                  <CardTitle class="text-base font-semibold leading-none mb-1.5">{{ kb.name }}</CardTitle>
                  <div class="flex items-center gap-1.5 text-xs text-muted-foreground" @click.stop>
                    <span class="truncate max-w-[120px] font-mono bg-muted px-1.5 py-0.5 rounded">{{ kb.index_name }}</span>
                    <Button 
                      variant="ghost" 
                      size="icon" 
                      class="h-5 w-5 hover:bg-muted text-muted-foreground"
                      @click="copyIndexName(kb)"
                    >
                      <Copy class="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              </div>
              
              <Badge 
                :variant="kb.disabled ? 'secondary' : 'default'" 
                class="capitalize"
              >
                {{ kb.disabled ? t('knowledgeBase.disabled') : t('knowledgeBase.enabled') }}
              </Badge>
            </div>
          </CardHeader>
          
          <CardContent class="pb-3">
            <p class="text-sm text-muted-foreground line-clamp-2 min-h-[2.5rem]">
              {{ getSimpleDescription(kb) }}
            </p>
          </CardContent>
          
          <CardFooter class="pt-3 border-t bg-muted/20 flex justify-between items-center text-xs text-muted-foreground">
             <div class="flex items-center gap-2">
               <Badge variant="outline" class="bg-background/50">
                 {{ getTypeName(kb.dataSource) }}
               </Badge>
             </div>
             <div class="flex items-center gap-3">
               <span class="flex items-center gap-1" :title="t('knowledgeBase.documents')">
                 <FileText class="h-3.5 w-3.5" />
                 {{ kb.docNum || 0 }}
               </span>
               <span class="flex items-center gap-1" :title="t('knowledgeBase.lastUpdated')">
                 <Clock class="h-3.5 w-3.5" />
                 {{ formatDate(kb.createTime) }}
               </span>
             </div>
          </CardFooter>
        </Card>
      </div>

      <!-- Empty State -->
      <div v-else class="flex flex-col items-center justify-center py-20 text-center animate-in fade-in zoom-in-95 duration-500">
        <div class="bg-muted/30 p-6 rounded-full mb-6">
          <BookOpen class="h-16 w-16 text-muted-foreground/40" />
        </div>
        <h3 class="text-xl font-semibold text-foreground mb-2">{{ t('knowledgeBase.noKnowledgeBases') }}</h3>
        <p class="text-muted-foreground max-w-sm">{{ t('knowledgeBase.noKnowledgeBasesDesc') }}</p>
        <Button variant="outline" class="mt-6" @click="showAddKnowledgeBaseForm">
          <Plus class="mr-2 h-4 w-4" />
          {{ t('knowledgeBase.addKnowledgeBase') }}
        </Button>
      </div>
    </div>

    <!-- Add View -->
    <div v-if="viewMode === 'add-kb'" class="animate-in slide-in-from-right-10 duration-300">
       <KnowledgeBaseAdd 
        @success="handleKnowledgeBaseSuccess" 
        @cancel="backToList"
        ref="knowledgeBaseAddRef" 
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { BookOpen, Plus, Copy, Search, FileText, Clock } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { knowledgeBaseAPI } from '../api/knowledgeBase.js'
import KnowledgeBaseAdd from '../components/KnowledgeBaseAdd.vue'

// UI Components
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'

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
    // Keep mock data for fallback/demo if API fails
    knowledgeBases.value = [
      {
        id: '1',
        name: '产品文档知识库',
        dataSource: 'document',
        intro: '包含所有产品相关的文档和说明',
        docNum: 156,
        createTime: '2024-01-15T10:30:00Z',
        disabled: false,
        index_name: 'prod_docs_v1'
      },
      {
        id: '2',
        name: '技术支持知识库',
        dataSource: 'qa',
        intro: '常见问题解答和技术支持文档',
        docNum: 89,
        createTime: '2024-01-14T15:45:00Z',
        disabled: true,
        index_name: 'tech_support_v1'
      }
    ]
  } finally {
    loading.value = false
  }
}

// Methods
const showAddKnowledgeBaseForm = () => {
  if (knowledgeBaseAddRef.value) {
    knowledgeBaseAddRef.value.resetForm()
  }
  viewMode.value = 'add-kb'
}

const handleKnowledgeBaseSuccess = async () => {
  await loadKnowledgeBases()
  backToList()
}

const backToList = () => {
  viewMode.value = 'list'
}

const goToDetail = (kb) => {
  if (!kb || !kb.id) return
  router.push({ name: 'KnowledgeBaseDetail', params: { kdbId: kb.id } })
}

const getSimpleDescription = (kb) => {
  if (!kb) return t('knowledgeBase.noDescription')
  return kb.intro || t('knowledgeBase.noDescription')
}

const getTypeName = (type) => {
  switch (type?.toLowerCase()) {
    case 'document':
      return t('knowledgeBase.documentType') || 'Document'
    case 'qa':
      return t('knowledgeBase.qaType') || 'Q&A'
    case 'code':
      return t('knowledgeBase.codeType') || 'Code'
    default:
      return t('knowledgeBase.unknownType') || 'Unknown'
  }
}

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

const copyIndexName = async (kb) => {
  const text = kb?.index_name || ''
  if (!text) return
  
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return
    }
  } catch (_) {}
  
  // Fallback
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  try { document.execCommand('copy') } catch (_) {}
  document.body.removeChild(ta)
}

onMounted(() => {
  loadKnowledgeBases()
})
</script>