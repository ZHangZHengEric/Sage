<template>
  <div class="h-full w-full bg-background flex flex-col overflow-hidden">
    <!-- Header Area -->
    <div class="flex-none bg-background border-b">
      <!-- Categories / Tabs -->
      <div class=" md:px-6 p-4 flex justify-between items-center">
        <div class="flex items-center gap-2 overflow-x-auto no-scrollbar pb-1">
          <button
            v-for="group in groups"
            :key="group.id"
            class="flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-medium transition-all border shrink-0"
            :class="selectedGroup === group.id
              ? 'bg-primary text-primary-foreground border-primary shadow-sm' 
              : 'bg-background text-muted-foreground border-input hover:bg-muted hover:text-foreground'"
            @click="handleGroupClick(group.id)"
          >
            <component :is="group.icon" class="h-3.5 w-3.5" />
            <span>{{ group.label }}</span>
            <span class="ml-1 text-xs opacity-70 bg-black/10 dark:bg-white/10 px-1.5 rounded-full">{{ group.count }}</span>
          </button>
        </div>
        <div class="relative flex-1 sm:w-64 sm:flex-none">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input v-model="searchTerm" :placeholder="t('knowledgeBase.searchPlaceholder')" class="pl-9 h-9 w-full" />
        </div>
      </div>
      
    </div>

    <!-- Main Content Area -->
    <div class="flex-1 overflow-hidden bg-muted/5 p-4 md:p-6">
      <ScrollArea class="h-full">
        <div v-if="loading" class="flex flex-col items-center justify-center py-20">
          <Loader class="h-8 w-8 animate-spin text-primary" />
        </div>

        <div v-else-if="displayedKnowledgeBases.length > 0" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 pb-20">
          <Card 
            class="flex flex-col items-center justify-center border-dashed border-2 cursor-pointer hover:border-primary/50 hover:bg-muted/50 transition-all duration-300 min-h-[180px]"
            @click="showAddKnowledgeBaseForm"
          >
            <div class="flex flex-col items-center gap-2 text-muted-foreground hover:text-primary transition-colors">
              <div class="p-3 rounded-full bg-muted/50">
                <Plus class="h-6 w-6" />
              </div>
              <span class="font-medium">{{ t('knowledgeBase.addKnowledgeBase') }}</span>
            </div>
          </Card>
          <Card v-for="kb in displayedKnowledgeBases" :key="kb.id"
            class="cursor-pointer hover:shadow-md transition-all duration-300 group border-muted/60 hover:border-primary/50 bg-card"
            @click="goToDetail(kb)">
            <CardHeader class="pb-3">
              <div class="flex justify-between items-start">
                <div class="flex items-center gap-3">
                  <div
                    class="p-2 rounded-lg bg-primary/10 text-primary group-hover:bg-primary group-hover:text-primary-foreground transition-colors duration-300">
                    <component :is="getTypeIcon(kb.dataSource)" class="h-5 w-5" />
                  </div>
                  <CardTitle class="text-base font-semibold leading-none mb-1.5">{{ kb.name }}</CardTitle>
                  <Button variant="ghost" size="icon"
                    class="h-5 w-5 hover:bg-muted text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity"
                    @click="copyIndexName(kb)">
                    <Copy class="h-3 w-3" />
                  </Button>

                </div>
            
                <Badge :variant="kb.disabled ? 'secondary' : 'default'" class="capitalize text-[10px] px-1.5 py-0 h-5">
                  {{ kb.disabled ? t('knowledgeBase.disabled') : t('knowledgeBase.enabled') }}
                </Badge>
              </div>
            </CardHeader>

            <CardContent class="pb-3">
              <p class="text-sm text-muted-foreground line-clamp-2 min-h-[2.5rem]">
                {{ getSimpleDescription(kb) }}
              </p>
            </CardContent>

            <CardFooter
              class="pt-3 border-t bg-muted/20 flex justify-between items-center text-xs text-muted-foreground">
              <div class="flex items-center gap-2">
                <Badge variant="outline" class="bg-background/50 border-0 shadow-none px-0 font-normal text-muted-foreground">
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
        <div v-else class="flex flex-col items-center justify-center py-20 text-center">
          <div class="bg-muted/30 p-6 rounded-full mb-6">
            <BookOpen class="h-16 w-16 text-muted-foreground/40" />
          </div>
          <h3 class="text-xl font-semibold text-foreground mb-2">{{ t('knowledgeBase.noKnowledgeBases') }}</h3>
          <p class="text-muted-foreground max-w-sm">{{ searchTerm ? t('knowledgeBase.noSearchResults') : t('knowledgeBase.noKnowledgeBasesDesc') }}</p>
          <Button variant="outline" class="mt-6" @click="showAddKnowledgeBaseForm">
            <Plus class="mr-2 h-4 w-4" />
            {{ t('knowledgeBase.addKnowledgeBase') }}
          </Button>
        </div>
      </ScrollArea>
    </div>

    <!-- Add View Modal -->
    <Dialog v-model:open="showAddModal">
      <DialogContent class="max-w-3xl p-0 border-0 bg-transparent shadow-none">
        <KnowledgeBaseAdd @success="handleKnowledgeBaseSuccess" @cancel="showAddModal = false" ref="knowledgeBaseAddRef" />
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { BookOpen, Plus, Copy, Search, FileText, Clock, Loader, MessageSquare, Code, Layers } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { knowledgeBaseAPI } from '../api/knowledgeBase.js'
import KnowledgeBaseAdd from '../components/KnowledgeBaseAdd.vue'

// UI Components
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Dialog, DialogContent } from '@/components/ui/dialog'

// Composables
const { t } = useLanguage()

// Refs
const knowledgeBaseAddRef = ref(null)
const router = useRouter()

// State
const knowledgeBases = ref([])
const searchTerm = ref('')
const showAddModal = ref(false)
const loading = ref(true)
const selectedGroup = ref('all')

// Groups Configuration
const groups = computed(() => [
  { 
    id: 'all', 
    label: t('knowledgeBase.all') || 'All', 
    icon: Layers,
    count: knowledgeBases.value.length
  },
  { 
    id: 'document', 
    label: t('knowledgeBase.documentType') || 'Documents', 
    icon: BookOpen,
    count: knowledgeBases.value.filter(k => k.dataSource === 'document').length
  },
  { 
    id: 'qa', 
    label: t('knowledgeBase.qaType') || 'Q&A', 
    icon: MessageSquare,
    count: knowledgeBases.value.filter(k => k.dataSource === 'qa').length
  },
  { 
    id: 'code', 
    label: t('knowledgeBase.codeType') || 'Code', 
    icon: Code,
    count: knowledgeBases.value.filter(k => k.dataSource === 'code').length
  }
])

const displayedKnowledgeBases = computed(() => {
  let result = knowledgeBases.value

  // Group filtering
  if (selectedGroup.value !== 'all') {
    result = result.filter(k => k.dataSource === selectedGroup.value)
  }

  // Search filtering
  if (searchTerm.value.trim()) {
    const query = searchTerm.value.toLowerCase()
    result = result.filter(kb =>
      kb.name.toLowerCase().includes(query) ||
      (kb.intro && kb.intro.toLowerCase().includes(query))
    )
  }
  
  return result
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
   
  } finally {
    loading.value = false
  }
}

// Methods
const handleGroupClick = (groupId) => {
  selectedGroup.value = groupId
}

const showAddKnowledgeBaseForm = () => {
  if (knowledgeBaseAddRef.value) {
    knowledgeBaseAddRef.value.resetForm()
  }
  showAddModal.value = true
}

const handleKnowledgeBaseSuccess = async () => {
  await loadKnowledgeBases()
  showAddModal.value = false
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

const getTypeIcon = (type) => {
  switch (type?.toLowerCase()) {
    case 'document':
      return BookOpen
    case 'qa':
      return MessageSquare
    case 'code':
      return Code
    default:
      return Layers
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
