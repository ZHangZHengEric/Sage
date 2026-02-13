<template>
  <div class="min-h-screen bg-background pb-10">
    <!-- Header Section with Breadcrumb and Actions -->
    <div class="border-b bg-card/50 backdrop-blur-sm sticky top-0 z-10">
      <div class="container max-w-7xl mx-auto py-4 px-4 md:px-6">
        <div class="flex flex-col space-y-4">

          <!-- Title and Stats -->
          <div class="flex flex-col md:flex-row md:items-start md:justify-between gap-6">
            <div class="flex items-start gap-4">
              <div class="p-3 rounded-xl bg-primary/10 text-primary shrink-0">
                <BookOpen v-if="kbInfo.dataSource === 'document'" class="h-5 w-5" />
                <MessageSquare v-else-if="kbInfo.dataSource === 'qa'" class="h-5 w-5" />
                <Code v-else-if="kbInfo.dataSource === 'code'" class="h-5 w-5" />
                <Layers v-else class="h-5 w-5" />
              </div>
              <div class="space-y-1">
                <h1 class="text-2xl md:text-3xl font-bold tracking-tight text-foreground">{{ kbInfo.name || 'Loading...' }}</h1>
                <p class="text-muted-foreground text-sm md:text-base max-w-xl leading-relaxed">
                  {{ kbInfo.intro || t('knowledgeBase.noDescription') }}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="container max-w-7xl mx-auto py-8 px-4 md:px-6">
      <Tabs v-model="activeTab" class="w-full space-y-6">
        <TabsList class="h-12 w-full justify-start rounded-lg bg-muted/50 p-1">
          <TabsTrigger 
            value="documents" 
            class="h-full px-6 rounded-md data-[state=active]:bg-background data-[state=active]:shadow-sm data-[state=active]:text-primary transition-all"
          >
            <FileText class="mr-2 h-4 w-4" />
            {{ t('knowledgeBase.documents') }}
          </TabsTrigger>
          <TabsTrigger 
            value="recall"
            class="h-full px-6 rounded-md data-[state=active]:bg-background data-[state=active]:shadow-sm data-[state=active]:text-primary transition-all"
          >
            <Search class="mr-2 h-4 w-4" />
            {{ t('knowledgeBase.recallTest') }}
          </TabsTrigger>
          <TabsTrigger 
            value="settings"
            class="h-full px-6 rounded-md data-[state=active]:bg-background data-[state=active]:shadow-sm data-[state=active]:text-primary transition-all"
            v-if="canEdit"
          >
            <Settings class="mr-2 h-4 w-4" />
            {{ t('knowledgeBase.settings') }}
          </TabsTrigger>
        </TabsList>
        
        <!-- Documents Tab -->
        <TabsContent value="documents" class="space-y-4 animate-in fade-in slide-in-from-bottom-2 duration-300">
          <div class="flex flex-col sm:flex-row items-center justify-between gap-4 bg-card p-1 rounded-lg">
            <div class="relative w-full sm:w-72">
              <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input 
                v-model="docQueryName" 
                :placeholder="t('knowledgeBase.searchDocs')" 
                class="pl-9 h-10 bg-background border-muted hover:border-primary/50 transition-colors"
                @keyup.enter="loadDocs"
              />
            </div>
            
            <div class="flex items-center gap-3 w-full sm:w-auto">
               <input ref="fileInputRef" type="file" multiple style="display:none" @change="onFileChange"
                accept=".doc,.docx,.pdf,.txt,.json,.eml,.ppt,.pptx,.xlsx,.xls,.csv,.md" />
               <Button v-if="canEdit" size="default" @click="triggerSelectFiles" :disabled="docLoading" class="w-full sm:w-auto shadow-sm">
                 <Upload class="mr-2 h-4 w-4" />
                 {{ t('knowledgeBase.uploadFile') }}
               </Button>
            </div>
          </div>

          <div class="rounded-xl border bg-card shadow-sm overflow-hidden">
            <Table>
              <TableHeader class="bg-muted/30">
                <TableRow class="hover:bg-transparent">
                  <TableHead class="w-[400px] pl-6 h-12">{{ t('knowledgeBase.docName') }}</TableHead>
                  <TableHead class="h-12">{{ t('knowledgeBase.docStatus') }}</TableHead>
                  <TableHead class="h-12">{{ t('knowledgeBase.docCreatedAt') }}</TableHead>
                  <TableHead class="text-right pr-6 h-12">{{ t('common.actions') }}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="d in docList" :key="d.id" class="group hover:bg-muted/30 transition-colors">
                  <TableCell class="font-medium pl-6 py-4">
                    <div class="flex items-center gap-3">
                      <div class="p-2.5 rounded-lg bg-primary/5 text-primary group-hover:bg-primary group-hover:text-primary-foreground transition-colors duration-300">
                        <FileText class="h-4 w-4" />
                      </div>
                      <span class="truncate max-w-[300px] font-medium text-foreground" :title="d.doc_name">{{ d.doc_name }}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge :variant="getStatusVariant(d.status)" class="flex w-fit items-center gap-1.5 px-2.5 py-0.5 font-normal transition-colors">
                      <component :is="getStatusIcon(d.status)" class="h-3.5 w-3.5" :class="{'animate-spin': d.status === 1}" />
                      <span>{{ statusText(d.status) }}</span>
                    </Badge>
                  </TableCell>
                  <TableCell class="text-muted-foreground text-sm">{{ formatTime(d.create_time) }}</TableCell>
                  <TableCell class="text-right pr-6">
                    <div class="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-all duration-200">
                      <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-primary hover:bg-primary/10" @click="redoDoc(d)" :title="t('knowledgeBase.redo')">
                        <RotateCcw class="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10" @click="deleteDoc(d)" :title="t('common.delete')">
                        <Trash2 class="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
                <TableRow v-if="docList.length === 0 && !docLoading">
                   <TableCell colspan="4" class="h-64 text-center">
                     <div class="flex flex-col items-center justify-center text-muted-foreground/50">
                       <div class="p-4 rounded-full bg-muted/50 mb-4">
                         <FileText class="h-8 w-8" />
                       </div>
                       <span class="text-lg font-medium text-foreground/80 mb-1">{{ t('knowledgeBase.noDocs') }}</span>
                       <span class="text-sm">{{ t('knowledgeBase.noDocsDesc') }}</span>
                     </div>
                   </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>

          <!-- Pagination -->
          <div class="flex items-center justify-between py-4" v-if="docTotal > 0">
             <div class="text-sm text-muted-foreground">
               {{ t('knowledgeBase.totalDocuments', { n: docTotal }) }}
             </div>
             <div class="flex items-center space-x-2">
               <Button
                variant="outline"
                size="sm"
                :disabled="docPageNo <= 1 || docLoading"
                @click="prevPage"
                class="h-8 w-8 p-0"
              >
                <ChevronLeft class="h-4 w-4" />
              </Button>
              <div class="text-sm font-medium min-w-[3rem] text-center">
                 {{ docPageNo }} / {{ totalPages }}
              </div>
              <Button
                variant="outline"
                size="sm"
                :disabled="docPageNo >= totalPages || docLoading"
                @click="nextPage"
                class="h-8 w-8 p-0"
              >
                <ChevronRight class="h-4 w-4" />
              </Button>
             </div>
          </div>
        </TabsContent>
        
        <!-- Recall Tab -->
        <TabsContent value="recall" class="space-y-4 animate-in fade-in slide-in-from-bottom-2 duration-300">
          <div class="flex flex-col space-y-2 bg-card p-4 rounded-lg border border-muted/60 shadow-sm">
             <div class="flex flex-col sm:flex-row w-full gap-3">
               <div class="relative flex-1">
                 <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                 <Input 
                   v-model="recallQuery" 
                   :placeholder="t('knowledgeBase.recallPlaceholder')" 
                   class="pl-9 h-10 bg-background" 
                   @keyup.enter="runRecall" 
                 />
               </div>
               <Button @click="runRecall" :disabled="recallLoading" class="h-10 px-6">
                 <Search class="mr-2 h-4 w-4" />
                 {{ t('knowledgeBase.recallQuery') }}
               </Button>
             </div>
             <p class="text-xs text-muted-foreground px-1">{{ t('knowledgeBase.recallTestDesc') }}</p>
          </div>

          <div v-if="recallResults.length > 0" class="flex flex-col max-h-[calc(100vh-320px)] min-h-[200px] mt-4">
             <div class="flex items-center justify-between pb-2 border-b shrink-0 mb-4 mr-2">
               <span class="text-sm font-medium flex items-center gap-2">
                 <Search class="h-4 w-4 text-primary" />
                 {{ t('knowledgeBase.recallResults') }} ({{ recallResults.length }})
               </span>
             </div>
             
             <div class="overflow-y-auto pr-2 space-y-4 pb-4 scrollbar-thin scrollbar-thumb-muted-foreground/20 scrollbar-track-transparent flex-1">
               <Card v-for="(r, i) in recallResults" :key="makeRecallKey(r)" class="border-muted/60 transition-all hover:shadow-md group">
                 <CardHeader class="pb-3 bg-muted/10 pt-4 border-b border-muted/40">
                   <div class="flex justify-between items-start gap-4">
                     <div class="space-y-1.5">
                       <CardTitle class="text-base font-semibold text-foreground flex items-center gap-3">
                         <span class="bg-primary text-primary-foreground w-6 h-6 rounded-md flex items-center justify-center text-xs font-bold shadow-sm">{{ i + 1 }}</span>
                         <span class="line-clamp-1">{{ r.title }}</span>
                       </CardTitle>
                       <div class="flex items-center gap-2 pl-9">
                          <Badge variant="outline" class="text-[10px] h-5 px-1.5 text-muted-foreground bg-background/50">Doc ID: {{ r.doc_id }}</Badge>
                       </div>
                     </div>
                     <Badge :variant="getScoreVariant(r.score)" class="shrink-0 text-xs font-medium px-2.5 py-0.5 shadow-sm">
                       Score: {{ (r.score ?? 0).toFixed(4) }}
                     </Badge>
                   </div>
                 </CardHeader>
                 <CardContent class="pt-4 pl-4 md:pl-12 pr-4 md:pr-8">
                   <div class=" overflow-y-auto pr-2 scrollbar-thin scrollbar-thumb-muted-foreground/20 scrollbar-track-transparent prose prose-sm dark:prose-invert max-w-none text-muted-foreground/90 bg-muted/30 p-4 rounded-lg border border-muted/50 leading-relaxed group-hover:bg-muted/50 transition-colors">
                     <MarkdownRenderer :content="r.doc_content" />
                   </div>
                 </CardContent>
               </Card>
             </div>
          </div>
             
          <div v-else-if="!recallLoading && recallQuery" class="text-center py-16">
            <div class="bg-muted/30 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4">
              <Search class="h-8 w-8 text-muted-foreground/40" />
            </div>
            <h3 class="text-lg font-medium text-foreground">{{ t('knowledgeBase.noRecallResults') }}</h3>
            <p class="text-muted-foreground text-sm mt-1">{{ t('knowledgeBase.noRecallResultsDesc') }}</p>
          </div>
        </TabsContent>

        <!-- Settings Tab -->
        <TabsContent value="settings" v-if="canEdit" class="animate-in fade-in slide-in-from-bottom-2 duration-300">
          <div class="max-w-3xl mx-auto py-4">
            <Card class="border-muted/60 shadow-sm">
              <CardHeader class="border-b bg-muted/10 pb-6">
                <CardTitle class="text-xl">{{ t('knowledgeBase.settings') }}</CardTitle>
                <CardDescription>{{ t('knowledgeBase.settingsDesc') }}</CardDescription>
              </CardHeader>
              <CardContent class="space-y-6 pt-8">
                <div class="grid gap-3">
                  <Label for="kb-name" class="text-base">{{ t('knowledgeBase.name') }}</Label>
                  <Input id="kb-name" v-model="editForm.name" class="h-11" />
                </div>
                <div class="grid gap-3">
                  <Label for="kb-intro" class="text-base">{{ t('knowledgeBase.description') }}</Label>
                  <Textarea id="kb-intro" v-model="editForm.intro" rows="6" class="resize-none" />
                  <p class="text-xs text-muted-foreground">{{ t('knowledgeBase.descriptionHint') }}</p>
                </div>
              </CardContent>
              <CardFooter class="flex justify-between border-t bg-muted/10 py-4 px-6 mt-6">
                <Button variant="ghost" class="text-destructive hover:text-destructive hover:bg-destructive/10" @click="confirmDelete" :disabled="saving">
                   <Trash2 class="mr-2 h-4 w-4" />
                   {{ t('common.delete') }}
                </Button>
                <Button @click="saveSettings" :disabled="saving" class="min-w-[100px]">
                  {{ saving ? t('knowledgeBase.status.processing') : t('common.save') }}
                </Button>
              </CardFooter>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { Trash2, RotateCcw, Clock, Loader, CheckCircle2, XCircle, ArrowLeft, Upload, Search, ChevronRight, BookOpen, MessageSquare, Code, Layers, FileText, Settings, ChevronLeft, AlertCircle } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import { useLanguage } from '../utils/i18n.js'
import { knowledgeBaseAPI } from '../api/knowledgeBase.js'
import { getCurrentUser } from '../utils/auth.js'
import MarkdownRenderer from '../components/chat/MarkdownRenderer.vue'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'

const { t } = useLanguage()
const route = useRoute()
const router = useRouter()
const currentUser = ref(getCurrentUser())

const kdbId = route.params.kdbId
const activeTab = ref('documents')

const canEdit = computed(() => {
  if (!currentUser.value) return false
  if (currentUser.value.role === 'admin') return true
  return kbInfo.value.user_id === currentUser.value.userid
})

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
const allowedExts = computed(() => {
  if (kbInfo.value.type === 'qa') {
    return ['.csv', '.xlsx', '.xls']
  }
  return ['.doc', '.docx', '.pdf', '.txt', '.json', '.eml', '.ppt', '.pptx', '.xlsx', '.xls', '.csv', '.md']
})

const loadInfo = async () => {
  try {
    const res = await knowledgeBaseAPI.getKnowledgeBase(kdbId)
    kbInfo.value = res || {}
    editForm.value.name = kbInfo.value.name || ''
    editForm.value.intro = kbInfo.value.intro || ''
  } catch (e) {
    console.error(e)
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
  try {
    await knowledgeBaseAPI.deleteKnowledgeBase(kdbId)
    goBack()
  } catch (e) {
    console.error(e)
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
    const { list = [], total = 0 } = res || {}
    docList.value = list
    docTotal.value = total
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
    return allowedExts.value.includes(ext)
  })
  if (filtered.length !== fl.length) {
    window.alert(t('knowledgeBase.fileTypeWarning') + ' ' + allowedExts.value.join(', '))
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
    await knowledgeBaseAPI.addDocumentsByFiles({ kdb_id: kdbId, files: selectedFiles.value, override: false })
    await loadDocs()
    selectedFiles.value = []
    if (fileInputRef.value) fileInputRef.value.value = ''
  } finally {
    docLoading.value = false
  }
}

const deleteDoc = async (d) => {
  try {
    await knowledgeBaseAPI.deleteDocument(d.id)
    await loadDocs()
  } catch (e) { console.error(e) }
}

const redoDoc = async (d) => {
  try {
    await knowledgeBaseAPI.redoDocument(d.id)
    await loadDocs()
  } catch (e) { console.error(e) }
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

const formatDate = (iso) => {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString()
  } catch (e) {
    return iso
  }
}

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
    const list = Array.isArray(res?.results) ? res.results : []
    recallResults.value = list
  } finally {
    recallLoading.value = false
  }
}

const makeRecallKey = (r) => `${r.doc_id || ''}-${r.doc_segment_id || ''}-${r.start || 0}-${r.end || 0}`

const getStatusVariant = (s) => {
  switch (s) {
    case 1: return 'secondary' // Processing
    case 2: return 'default' // Success (green-ish usually, but default is dark)
    case 3: return 'destructive' // Failed
    default: return 'outline' // Pending
  }
}

const getStatusIcon = (s) => {
  switch (s) {
    case 1: return Loader
    case 2: return CheckCircle2
    case 3: return AlertCircle
    default: return Clock
  }
}

const statusText = (s) => {
  switch (s) {
    case 0: return t('knowledgeBase.status.pending')
    case 1: return t('knowledgeBase.status.processing')
    case 2: return t('knowledgeBase.status.success')
    case 3: return t('knowledgeBase.status.failed')
    default: return t('knowledgeBase.status.unknown')
  }
}

const getScoreVariant = (score) => {
  if (score > 0.8) return 'default'
  if (score > 0.6) return 'secondary'
  return 'outline'
}
</script>

<style scoped>
:deep(.recall-highlight) {
  @apply bg-yellow-200 dark:bg-yellow-900/50 text-foreground rounded px-0.5;
}
</style>
