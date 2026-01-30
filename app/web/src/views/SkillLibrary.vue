<template>
  <div class="h-screen w-full bg-background p-6">
    <div class="flex h-full flex-col space-y-6">
      <!-- Header -->
      <div class="flex items-center justify-between pb-4 border-b">
        <div>
          <h1 class="text-2xl font-bold tracking-tight">{{ t('skills.title') }}</h1>
          <p class="text-muted-foreground">{{ t('skills.subtitle') }}</p>
        </div>
        <Button @click="showImportModal = true">
          <Plus class="mr-2 h-4 w-4" />
          {{ t('skills.import') }}
        </Button>
      </div>

      <!-- Search -->
      <div class="flex items-center justify-between">
        <div class="relative w-full max-w-sm">
          <Search class="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input 
            v-model="searchTerm" 
            :placeholder="t('skills.search')" 
            class="pl-9"
          />
        </div>
      </div>

      <!-- Content -->
      <ScrollArea class="flex-1 -mr-4 pr-4">
        <div v-if="filteredSkills.length > 0" class="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <Card 
            v-for="skill in filteredSkills" 
            :key="skill.name" 
            class="transition-all hover:shadow-md hover:-translate-y-0.5 group"
          >
            <CardHeader class="flex flex-row items-start gap-4 space-y-0 pb-2">
              <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Box class="h-5 w-5" />
              </div>
              <div class="space-y-1 overflow-hidden flex-1">
                <CardTitle class="text-base truncate" :title="skill.name">
                  {{ skill.name }}
                </CardTitle>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <CardDescription class="line-clamp-2 text-xs cursor-help">
                        {{ skill.description || t('skills.noDescription') }}
                      </CardDescription>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p class="max-w-xs text-sm">{{ skill.description || t('skills.noDescription') }}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </CardHeader>
            <CardContent>
              <div class="flex items-center pt-4 border-t mt-2 text-xs text-muted-foreground" :title="skill.path">
                <Folder class="mr-1 h-3.5 w-3.5" />
                <span class="truncate">{{ getFolderName(skill.path) }}</span>
              </div>
            </CardContent>
          </Card>
        </div>

        <div v-else class="flex flex-col items-center justify-center py-12 text-center">
          <div class="rounded-full bg-muted p-4">
            <Box class="h-8 w-8 text-muted-foreground" />
          </div>
          <h3 class="mt-4 text-lg font-semibold">{{ t('skills.noSkillsDesc') }}</h3>
        </div>
      </ScrollArea>
    </div>

    <!-- Import Modal -->
    <Dialog v-model:open="showImportModal">
      <DialogContent class="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{{ t('skills.import') }}</DialogTitle>
          <DialogDescription>
            Import skills via ZIP file upload or from a URL.
          </DialogDescription>
        </DialogHeader>
        
        <Tabs v-model="importMode" class="w-full">
          <TabsList class="grid w-full grid-cols-2">
            <TabsTrigger value="upload">{{ t('skills.upload') }}</TabsTrigger>
            <TabsTrigger value="url">{{ t('skills.urlImport') }}</TabsTrigger>
          </TabsList>
          
          <TabsContent value="upload" class="space-y-4 pt-4">
            <div 
              class="border-2 border-dashed rounded-lg p-8 text-center hover:bg-muted/50 transition-colors cursor-pointer"
              @click="$refs.fileInput.click()"
              @drop.prevent="handleDrop"
              @dragover.prevent
            >
              <input 
                type="file" 
                ref="fileInput" 
                class="hidden" 
                accept=".zip" 
                @change="handleFileChange"
              >
              <div class="flex flex-col items-center justify-center gap-2">
                <Upload class="h-8 w-8 text-muted-foreground" />
                <div v-if="selectedFile" class="text-sm font-medium text-primary">
                  {{ selectedFile.name }}
                </div>
                <div v-else class="text-sm text-muted-foreground">
                  Drop file here or <span class="text-primary hover:underline">click to upload</span>
                </div>
                <p class="text-xs text-muted-foreground mt-1">Only .zip files are allowed</p>
              </div>
            </div>
          </TabsContent>
          
          <TabsContent value="url" class="space-y-4 pt-4">
            <div class="flex items-center space-x-2">
              <span class="text-sm font-medium text-muted-foreground">HTTPS</span>
              <Input 
                v-model="importUrl" 
                :placeholder="t('skills.urlPlaceholder')"
                class="flex-1"
              />
            </div>
          </TabsContent>
        </Tabs>

        <div v-if="importError" class="text-sm text-destructive font-medium">
          {{ importError }}
        </div>

        <DialogFooter>
          <Button variant="outline" @click="showImportModal = false">{{ t('skills.cancel') }}</Button>
          <Button type="primary" @click="handleImport" :disabled="isImportDisabled || importing">
            <Loader2 v-if="importing" class="mr-2 h-4 w-4 animate-spin" />
            {{ t('skills.confirm') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Box, Search, Folder, Plus, Upload, Loader2 } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { skillAPI } from '../api/skill.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

// Composables
const { t } = useLanguage()

// State
const skills = ref([])
const loading = ref(false)
const searchTerm = ref('')
const showImportModal = ref(false)
const importMode = ref('upload') // 'upload' or 'url'
const selectedFile = ref(null)
const importUrl = ref('')
const importing = ref(false)
const importError = ref('')
const fileInput = ref(null)

// Computed
const filteredSkills = computed(() => {
  if (!searchTerm.value.trim()) return skills.value
  const query = searchTerm.value.toLowerCase()
  return skills.value.filter(skill => 
    skill.name.toLowerCase().includes(query) || 
    (skill.description && skill.description.toLowerCase().includes(query))
  )
})

const isImportDisabled = computed(() => {
  if (importMode.value === 'upload') {
    return !selectedFile.value
  } else {
    return !importUrl.value
  }
})

// API Methods
const loadSkills = async () => {
  try {
    loading.value = true
    const response = await skillAPI.getSkills()
    if (response.skills) {
      skills.value = response.skills
    }
  } catch (error) {
    console.error('Failed to load skills:', error)
  } finally {
    loading.value = false
  }
}

const getFolderName = (path) => {
  if (!path) return ''
  const parts = path.split(/[/\\]/)
  return parts[parts.length - 1]
}

const handleFileChange = (event) => {
  const file = event.target.files[0]
  processFile(file)
}

const handleDrop = (event) => {
  const file = event.dataTransfer.files[0]
  processFile(file)
}

const processFile = (file) => {
  if (file) {
    if (!file.name.endsWith('.zip')) {
      importError.value = 'Only ZIP files are supported'
      selectedFile.value = null
      if (fileInput.value) fileInput.value.value = ''
      return
    }
    selectedFile.value = file
    importError.value = ''
  }
}

const handleImport = async () => {
  importing.value = true
  importError.value = ''

  try {
    if (importMode.value === 'upload') {
      if (!selectedFile.value) return
      
      const formData = new FormData()
      formData.append('file', selectedFile.value)
      
      await skillAPI.uploadSkill(formData)
    } else {
      if (!importUrl.value) return
      await skillAPI.importSkillFromUrl({ url: importUrl.value })
    }
    
    // Refresh list and close modal
    await loadSkills()
    showImportModal.value = false
    selectedFile.value = null
    importUrl.value = ''
    if (fileInput.value) fileInput.value.value = ''
  } catch (error) {
    console.error('Import failed:', error)
    importError.value = error.message || 'Import failed'
  } finally {
    importing.value = false
  }
}

onMounted(() => {
  loadSkills()
})
</script>
