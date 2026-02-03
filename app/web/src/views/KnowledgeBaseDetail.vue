<template>
  <div class="container py-6 space-y-6 max-w-7xl mx-auto min-h-screen">
    <!-- Header -->
    <div class="flex flex-col space-y-2">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
           <Button variant="ghost" size="icon" @click="goBack" class="mr-2 -ml-2">
             <ArrowLeft class="h-4 w-4" />
           </Button>
           <h2 class="text-2xl font-bold tracking-tight">{{ kbInfo.name || 'Knowledge Base' }}</h2>
        </div>
      </div>
      <p class="text-muted-foreground ml-10">{{ kbInfo.intro || t('knowledgeBase.noDescription') }}</p>
    </div>

    <Tabs v-model="activeTab" class="w-full">
      <TabsList class="grid w-full grid-cols-3 max-w-[400px]">
        <TabsTrigger value="documents">{{ t('knowledgeBase.documents') }}</TabsTrigger>
        <TabsTrigger value="recall">召回测试</TabsTrigger>
        <TabsTrigger value="settings">设置</TabsTrigger>
      </TabsList>
      
      <!-- Documents Tab -->
      <TabsContent value="documents" class="space-y-4 mt-6">
        <div class="flex items-center justify-between gap-4 flex-wrap">
          <div class="flex items-center gap-2 flex-1 min-w-[200px] max-w-sm">
            <Input 
              v-model="docQueryName" 
              placeholder="搜索文档..." 
              class="h-9"
              @keyup.enter="loadDocs"
            />
            <Button size="sm" @click="loadDocs" :disabled="docLoading">查询</Button>
          </div>
          
          <div class="flex items-center gap-2">
             <input ref="fileInputRef" type="file" multiple style="display:none" @change="onFileChange"
              accept=".doc,.docx,.pdf,.txt,.json,.eml,.ppt,.pptx,.xlsx,.xls,.csv,.md" />
             <Button v-if="canEdit" size="sm" @click="triggerSelectFiles" :disabled="docLoading">
               <Upload class="mr-2 h-4 w-4" />
               上传文件
             </Button>
          </div>
        </div>

        <div class="rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>创建时间</TableHead>
                <TableHead class="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="d in docList" :key="d.id">
                <TableCell class="font-medium">{{ d.doc_name }}</TableCell>
                <TableCell>
                  <div class="flex items-center gap-2" :title="statusText(d.status)">
                    <Clock v-if="d.status === 0" class="h-4 w-4 text-muted-foreground" />
                    <Loader v-else-if="d.status === 1" class="h-4 w-4 text-primary animate-spin" />
                    <CheckCircle2 v-else-if="d.status === 2" class="h-4 w-4 text-green-500" />
                    <XCircle v-else-if="d.status === 3" class="h-4 w-4 text-destructive" />
                    <span class="text-sm text-muted-foreground">{{ statusText(d.status) }}</span>
                  </div>
                </TableCell>
                <TableCell>{{ formatTime(d.create_time) }}</TableCell>
                <TableCell class="text-right">
                  <div class="flex justify-end gap-2">
                    <Button variant="ghost" size="icon" class="h-8 w-8 text-primary hover:text-primary hover:bg-primary/10" @click="redoDoc(d)" title="重做">
                      <RotateCcw class="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" class="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10" @click="deleteDoc(d)" title="删除">
                      <Trash2 class="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
              <TableRow v-if="docList.length === 0">
                 <TableCell colspan="4" class="h-32 text-center text-muted-foreground">
                   暂无文档
                 </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>

        <!-- Pagination -->
        <div class="flex items-center justify-end space-x-2 py-4">
           <div class="text-sm text-muted-foreground mr-4">
             {{ t('common.total') }}: {{ docTotal }}
           </div>
           <Button
            variant="outline"
            size="sm"
            :disabled="docPageNo <= 1 || docLoading"
            @click="prevPage"
          >
            上一页
          </Button>
          <div class="text-sm font-medium w-16 text-center">
             {{ docPageNo }} / {{ totalPages }}
          </div>
          <Button
            variant="outline"
            size="sm"
            :disabled="docPageNo >= totalPages || docLoading"
            @click="nextPage"
          >
            下一页
          </Button>
        </div>
      </TabsContent>
      
      <!-- Recall Tab -->
      <TabsContent value="recall" class="space-y-6 mt-6">
        <div class="flex gap-4">
           <Input v-model="recallQuery" placeholder="输入问题或关键词进行召回测试..." class="max-w-xl" @keyup.enter="runRecall" />
           <Button @click="runRecall" :disabled="recallLoading">
             <Search class="mr-2 h-4 w-4" />
             查询
           </Button>
        </div>

        <div class="space-y-4">
           <Card v-for="r in recallResults" :key="makeRecallKey(r)" class="overflow-hidden">
             <CardHeader class="pb-2 bg-muted/20">
               <div class="flex justify-between items-start">
                 <CardTitle class="text-base font-medium truncate pr-4">{{ r.title }}</CardTitle>
                 <Badge variant="outline" class="bg-background">Score: {{ (r.score ?? 0).toFixed(4) }}</Badge>
               </div>
             </CardHeader>
             <CardContent class="pt-4">
               <div class="prose prose-sm dark:prose-invert max-w-none">
                 <MarkdownRenderer :content="r.doc_content" />
               </div>
             </CardContent>
           </Card>
           
           <div v-if="recallResults.length === 0 && !recallLoading" class="text-center py-12 text-muted-foreground bg-muted/10 rounded-lg border border-dashed">
             暂无召回结果，请尝试搜索
           </div>
        </div>
      </TabsContent>

      <!-- Settings Tab -->
      <TabsContent value="settings" class="mt-6" v-if="canEdit">
        <Card>
          <CardHeader>
            <CardTitle>知识库设置</CardTitle>
            <CardDescription>管理知识库的基本信息</CardDescription>
          </CardHeader>
          <CardContent class="space-y-4">
            <div class="grid gap-2">
              <Label for="kb-name">{{ t('knowledgeBase.name') }}</Label>
              <Input id="kb-name" v-model="editForm.name" />
            </div>
            <div class="grid gap-2">
              <Label for="kb-intro">{{ t('knowledgeBase.description') }}</Label>
              <Textarea id="kb-intro" v-model="editForm.intro" rows="4" />
            </div>
          </CardContent>
          <CardFooter class="flex justify-between border-t bg-muted/20 pt-4">
            <Button variant="destructive" @click="confirmDelete" :disabled="saving">
               {{ t('common.delete') }}
            </Button>
            <Button @click="saveSettings" :disabled="saving">
              {{ saving ? '保存中...' : t('common.save') }}
            </Button>
          </CardFooter>
        </Card>
      </TabsContent>
    </Tabs>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { Trash2, RotateCcw, Clock, Loader, CheckCircle2, XCircle, ArrowLeft, Upload, Search } from 'lucide-vue-next'
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
    return allowedExts.value.includes(ext)
  })
  if (filtered.length !== fl.length) {
    window.alert('仅支持上传以下文件类型：' + allowedExts.value.join(', '))
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
      const list = Array.isArray(res.data.search_results) ? res.data.search_results : []
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
