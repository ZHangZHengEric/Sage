<template>
  <div class="h-full w-full bg-background flex flex-col overflow-hidden">
    <!-- Header Area -->
    <div class="flex-none bg-background border-b">
      <!-- Categories / Tabs -->
      <div class="p-4 md:px-6 pb-4 flex justify-between items-center">
        <div class="flex items-center gap-2 overflow-x-auto no-scrollbar pb-1">
          <button
            v-for="group in groups"
            :key="group.id"
            class="flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-medium transition-all border shrink-0"
            :class="selectedGroup === group.id
              ? 'bg-primary text-primary-foreground border-primary shadow-sm' 
              : 'bg-background text-muted-foreground border-input hover:bg-muted hover:text-foreground'"
            @click="selectedGroup = group.id"
          >
            <component :is="group.icon" class="h-3.5 w-3.5" />
            <span>{{ group.label }}</span>
            <span class="ml-1 text-xs opacity-70 bg-black/10 dark:bg-white/10 px-1.5 rounded-full">{{ group.count }}</span>
          </button>
        </div>
        <div class="relative flex-1 sm:w-64 sm:flex-none">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input v-model="searchTerm" :placeholder="t('skills.searchPlaceholder')" class="pl-9 h-9 w-full" />
        </div>
      </div>
    </div>

    <!-- Main Content Area -->
    <div class="flex-1 overflow-hidden bg-muted/5 p-4 md:p-6">
      <ScrollArea class="h-full">
        <div v-if="loading" class="flex flex-col items-center justify-center py-20">
          <Loader class="h-8 w-8 animate-spin text-primary" />
        </div>

        <div v-else-if="displayedSkills.length > 0" class="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 pb-20">
          <Card 
            class="flex flex-col items-center justify-center border-dashed border-2 cursor-pointer hover:border-primary/50 hover:bg-muted/50 transition-all duration-300 min-h-[140px]"
            @click="showImportModal = true"
          >
            <div class="flex flex-col items-center gap-2 text-muted-foreground hover:text-primary transition-colors">
              <div class="p-2 rounded-full bg-muted/50">
                <Plus class="h-6 w-6" />
              </div>
              <span class="font-medium">{{ t('skills.import') }}</span>
            </div>
          </Card>
          <Card 
            v-for="skill in displayedSkills" 
            :key="skill.name" 
            class="group hover:shadow-md transition-all duration-300 border-muted/60 hover:border-primary/50 bg-card"
          >
            <CardHeader class="flex flex-row items-start gap-4 space-y-0 pb-3">
              <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary group-hover:bg-primary group-hover:text-primary-foreground transition-colors">
                <Box class="h-5 w-5" />
              </div>
              <div class="space-y-1 overflow-hidden flex-1">
                <div class="flex items-center justify-between">
                  <CardTitle class="text-base truncate" :title="skill.name">
                    {{ skill.name }}
                  </CardTitle>
                  <div class="flex items-center gap-0 -mr-2 -mt-1">
                    <Button 
                      v-if="canEdit(skill)" 
                      variant="ghost" 
                      size="icon" 
                      class="h-7 w-7 text-muted-foreground hover:text-primary opacity-0 group-hover:opacity-100 transition-opacity"
                      @click.stop="openEditModal(skill)"
                    >
                      <Edit class="h-4 w-4" />
                    </Button>
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger as-child>
                          <Button 
                            v-if="canDelete(skill)" 
                            variant="ghost" 
                            size="icon" 
                            class="h-7 w-7 text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity"
                            @click.stop="deleteSkill(skill)"
                          >
                            <Trash2 class="h-4 w-4" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>{{ t('skills.delete') || 'Delete' }}</p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                </div>
                <CardDescription class="line-clamp-2 text-xs">
                  {{ skill.description || t('skills.noDescription') }}
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent class="pt-0 pb-3">
              <div class="flex items-center gap-2 mt-2 text-xs text-muted-foreground">
       
                <div v-if="skill.user_id === currentUser.userid" class="flex items-center gap-1 bg-primary/5 px-2 py-1 rounded text-primary/80">
                  <User class="h-3 w-3" />
                  <span>{{ t('skills.mine') || 'My Skill' }}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <div v-else class="flex flex-col items-center justify-center py-20 text-center">
          <div class="rounded-full bg-muted/50 p-6 mb-4">
            <Box class="h-10 w-10 text-muted-foreground/50" />
          </div>
          <h3 class="text-lg font-medium text-foreground">{{ t('skills.noSkills') || 'No skills found' }}</h3>
          <p class="text-sm text-muted-foreground mt-1 max-w-xs mx-auto">
            {{ searchTerm ? t('skills.noSearchResults') : t('skills.noSkillsDesc') }}
          </p>
          <Button variant="outline" class="mt-4" @click="showImportModal = true">
            <Plus class="mr-2 h-4 w-4" />
            {{ t('skills.import') }}
          </Button>
        </div>
      </ScrollArea>
    </div>

    <!-- Import Modal -->
    <Dialog v-model:open="showImportModal">
      <DialogContent class="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{{ t('skills.import') }}</DialogTitle>
          <DialogDescription>
            {{ t('skills.importDesc') }}
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
            <Loader v-if="importing" class="mr-2 h-4 w-4 animate-spin" />
            {{ t('skills.confirm') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    <!-- Edit Modal -->
    <Dialog v-model:open="showEditModal">
      <DialogContent class="sm:max-w-[800px] sm:h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{{ t('skills.edit') }} - {{ editingSkill?.name }}</DialogTitle>
          <DialogDescription>
            {{ t('skills.editDesc') || 'Edit SKILL.md content' }}
          </DialogDescription>
        </DialogHeader>
        
        <div class="flex-1 min-h-0 py-4">
          <Textarea 
            v-model="skillContent" 
            class="h-full font-mono text-sm resize-none"
            :placeholder="t('skills.contentPlaceholder') || 'Enter markdown content...'" 
          />
        </div>

        <DialogFooter>
          <Button variant="outline" @click="showEditModal = false">{{ t('skills.cancel') }}</Button>
          <Button type="primary" @click="saveSkillContent" :disabled="saving">
            <Loader v-if="saving" class="mr-2 h-4 w-4 animate-spin" />
            {{ t('skills.save') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Box, Search, Folder, Plus, Upload, Loader, Trash2, Layers, User, Shield, Edit } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { skillAPI } from '../api/skill.js'
import { getCurrentUser } from '../utils/auth.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { toast } from 'vue-sonner'

// Composables
const { t } = useLanguage()

// State
const skills = ref([])
const loading = ref(false)
const searchTerm = ref('')
const selectedGroup = ref('all')
const showImportModal = ref(false)
const importMode = ref('upload') // 'upload' or 'url'
const selectedFile = ref(null)
const importUrl = ref('')
const importing = ref(false)
const importError = ref('')
const fileInput = ref(null)
const currentUser = ref({ userid: '', role: 'user' })

const showEditModal = ref(false)
const editingSkill = ref(null)
const skillContent = ref('')
const saving = ref(false)

// Groups Configuration
const groups = computed(() => [
  { 
    id: 'all', 
    label: t('skills.allSkills') || 'All Skills', 
    icon: Layers,
    count: skills.value.length
  },
  { 
    id: 'mine', 
    label: t('skills.mySkills') || 'My Skills', 
    icon: User,
    count: skills.value.filter(s => s.user_id === currentUser.value.userid).length
  },
  { 
    id: 'system', 
    label: t('skills.systemSkills') || 'System Skills', 
    icon: Shield,
    count: skills.value.filter(s => s.user_id !== currentUser.value.userid).length
  }
])

// Computed
const displayedSkills = computed(() => {
  let result = skills.value

  // Group filtering
  if (selectedGroup.value === 'mine') {
    result = result.filter(s => s.user_id === currentUser.value.userid)
  } else if (selectedGroup.value === 'system') {
    result = result.filter(s => s.user_id !== currentUser.value.userid)
  }

  // Search filtering
  if (searchTerm.value.trim()) {
    const query = searchTerm.value.toLowerCase()
    result = result.filter(skill => 
      skill.name.toLowerCase().includes(query) || 
      (skill.description && skill.description.toLowerCase().includes(query))
    )
  }
  
  return result
})

const isImportDisabled = computed(() => {
  if (importMode.value === 'upload') {
    return !selectedFile.value
  } else {
    return !importUrl.value
  }
})

const canDelete = (skill) => {
  // If skill has no owner (system skill), user cannot delete
  if (currentUser.value.role && currentUser.value.role.toLowerCase() === 'admin') return true
  if (!skill.user_id) return false
  return skill.user_id === currentUser.value.userid
}

const canEdit = (skill) => {
  return canDelete(skill)
}

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

const deleteSkill = async (skill) => {
  if (!canDelete(skill)) return
  if (!confirm(t('skills.deleteConfirm', { name: skill.name }) || 'Are you sure you want to delete this skill?')) return
  
  try {
    loading.value = true
    await skillAPI.deleteSkill(skill.name)
    toast.success(t('skills.deleteSuccess'))
    await loadSkills()
  } catch (error) {
    console.error('Failed to delete skill:', error)
    toast.error(t('skills.deleteFailed'), {
      description: error.message,
    })
  } finally {
    loading.value = false
  }
}

const openEditModal = async (skill) => {
  editingSkill.value = skill
  skillContent.value = ''
  showEditModal.value = true
  
  try {
    const response = await skillAPI.getSkillContent(skill.name)
    if (response.content) {
      skillContent.value = response.content
    }
  } catch (error) {
    console.error('Failed to load skill content:', error)
    toast.error(t('skills.loadContentFailed'), {
      description: error.message
    })
    showEditModal.value = false
  }
}

const saveSkillContent = async () => {
  if (!editingSkill.value) return
  
  try {
    saving.value = true
    await skillAPI.updateSkillContent(editingSkill.value.name, skillContent.value)
    toast.success(t('skills.updateSuccess'))
    showEditModal.value = false
    loadSkills()
  } catch (error) {
    console.error('Failed to update skill:', error)
    toast.error(t('skills.updateFailed'), {
      description: error.message 
    })
  } finally {
    saving.value = false
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
      
      // Pass file object directly, API handles FormData
      await skillAPI.uploadSkill(selectedFile.value)
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
    toast.success(t('skills.importSuccess'))
  } catch (error) {
    console.error('Import failed:', error)
    importError.value = error.message || 'Import failed'
  } finally {
    importing.value = false
  }
}

onMounted(async () => {
  const user = await getCurrentUser()
  if (user) {
    currentUser.value = user
  }
  loadSkills()
})
</script>
