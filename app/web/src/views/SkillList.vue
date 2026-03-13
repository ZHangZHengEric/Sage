<template>
  <div class="h-full w-full bg-background flex flex-col overflow-hidden">
    <!-- Header Area -->
    <div class="flex-none bg-background border-b px-6 py-4">
      <div class="flex items-center justify-between gap-4">
        <!-- Title & Description -->
        <div>
          <h1 class="text-2xl font-semibold tracking-tight">{{ t('skills.title') || 'Skills' }}</h1>
          <p class="text-sm text-muted-foreground mt-1">
            {{ t('skills.subtitle') || 'Manage system, user and agent skills' }}
          </p>
        </div>

        <!-- Actions -->
        <div class="flex items-center gap-3">
          <div class="relative w-64">
            <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              v-model="searchTerm"
              :placeholder="t('skills.searchPlaceholder') || 'Search skills...'"
              class="pl-9 h-10"
            />
          </div>
          <Button @click="openImportModal" class="gap-2">
            <Plus class="h-4 w-4" />
            {{ t('skills.import') || 'Import' }}
          </Button>
        </div>
      </div>

      <!-- Dimension Filter Tabs -->
      <div class="mt-4">
        <Tabs v-model="selectedDimension" class="w-full">
          <TabsList class="grid w-full max-w-2xl grid-cols-4">
            <TabsTrigger value="all" class="gap-2">
              <Layers class="h-4 w-4" />
              <span>{{ t('skills.all') || 'All' }}</span>
              <Badge variant="secondary" class="ml-1 text-xs">{{ counts.all }}</Badge>
            </TabsTrigger>
            <TabsTrigger value="system" class="gap-2">
              <Shield class="h-4 w-4" />
              <span>{{ t('skills.system') || 'System' }}</span>
              <Badge variant="secondary" class="ml-1 text-xs">{{ counts.system }}</Badge>
            </TabsTrigger>
            <TabsTrigger value="user" class="gap-2">
              <User class="h-4 w-4" />
              <span>{{ t('skills.user') || 'User' }}</span>
              <Badge variant="secondary" class="ml-1 text-xs">{{ counts.user }}</Badge>
            </TabsTrigger>
            <TabsTrigger value="agent" class="gap-2">
              <Bot class="h-4 w-4" />
              <span>{{ t('skills.agent') || 'Agent' }}</span>
              <Badge variant="secondary" class="ml-1 text-xs">{{ counts.agent }}</Badge>
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
    </div>

    <!-- Main Content Area -->
    <div class="flex-1 overflow-hidden p-6">
      <div v-if="loading" class="flex flex-col items-center justify-center h-full">
        <Loader class="h-8 w-8 animate-spin text-primary" />
        <p class="text-sm text-muted-foreground mt-2">{{ t('common.loading') || 'Loading...' }}</p>
      </div>

      <div v-else-if="displayedSkills.length === 0" class="flex flex-col items-center justify-center h-full text-center">
        <div class="rounded-full bg-muted/50 p-6 mb-4">
          <Box class="h-10 w-10 text-muted-foreground/50" />
        </div>
        <h3 class="text-lg font-medium text-foreground">{{ t('skills.noSkills') || 'No skills found' }}</h3>
        <p class="text-sm text-muted-foreground mt-1 max-w-xs mx-auto">
          {{ searchTerm ? t('skills.noSearchResults') : t('skills.noSkillsDesc') }}
        </p>
        <Button variant="outline" class="mt-4" @click="openImportModal">
          <Plus class="mr-2 h-4 w-4" />
          {{ t('skills.import') || 'Import Skill' }}
        </Button>
      </div>

      <ScrollArea v-else class="h-full">
        <div class="space-y-2 pr-4">
          <!-- Import Card (when dimension is selected) -->
          <Card
            v-if="canImportToCurrentDimension"
            class="border-dashed border-2 cursor-pointer hover:border-primary/50 hover:bg-muted/30 transition-all duration-200"
            @click="openImportModalWithDimension"
          >
            <CardContent class="flex items-center justify-center gap-3 py-6">
              <div class="p-2 rounded-full bg-muted">
                <Plus class="h-5 w-5 text-muted-foreground" />
              </div>
              <span class="text-sm font-medium text-muted-foreground">
                {{ getImportLabel() }}
              </span>
            </CardContent>
          </Card>

          <!-- Skill Items -->
          <Card
            v-for="skill in displayedSkills"
            :key="skill.name"
            class="group hover:shadow-md transition-all duration-200"
          >
            <CardContent class="p-4">
              <div class="flex items-start gap-4">
                <!-- Icon -->
                <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Box class="h-5 w-5" />
                </div>

                <!-- Content -->
                <div class="flex-1 min-w-0">
                  <div class="flex items-start justify-between gap-4">
                    <div class="min-w-0">
                      <h3 class="font-medium text-foreground truncate" :title="skill.name">
                        {{ skill.name }}
                      </h3>
                      <p class="text-sm text-muted-foreground line-clamp-2 mt-1">
                        {{ skill.description || t('skills.noDescription') }}
                      </p>
                    </div>

                    <!-- Actions -->
                    <DropdownMenu>
                      <DropdownMenuTrigger as-child>
                        <Button variant="ghost" size="icon" class="h-8 w-8 shrink-0">
                          <MoreVertical class="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" class="w-40">
                        <DropdownMenuItem @click="openEditModal(skill)">
                          <Edit class="h-4 w-4 mr-2" />
                          {{ t('skills.edit') || 'Edit' }}
                        </DropdownMenuItem>
                        <DropdownMenuSeparator v-if="canDelete(skill)" />
                        <DropdownMenuItem
                          v-if="canDelete(skill)"
                          class="text-destructive focus:text-destructive"
                          @click="confirmDelete(skill)"
                        >
                          <Trash2 class="h-4 w-4 mr-2" />
                          {{ t('skills.delete') || 'Delete' }}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>

                  <!-- Metadata -->
                  <div class="flex items-center gap-2 mt-3">
                    <Badge
                      :variant="getDimensionBadgeVariant(skill.dimension)"
                      class="text-xs"
                    >
                      <component :is="getDimensionIcon(skill.dimension)" class="h-3 w-3 mr-1" />
                      {{ getDimensionLabel(skill.dimension) }}
                    </Badge>
                    <span v-if="skill.agent_id" class="text-xs text-muted-foreground">
                      Agent: {{ skill.agent_id }}
                    </span>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </ScrollArea>
    </div>

    <!-- Import Dialog -->
    <Dialog v-model:open="showImportModal">
      <DialogContent class="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>{{ t('skills.import') || 'Import Skill' }}</DialogTitle>
          <DialogDescription>
            {{ t('skills.importDesc') || 'Choose how you want to import the skill' }}
          </DialogDescription>
        </DialogHeader>

        <!-- Dimension Selection -->
        <div class="space-y-3">
          <Label>{{ t('skills.importTo') || 'Import to' }}</Label>
          <Select v-model="importTargetDimension">
            <SelectTrigger>
              <SelectValue :placeholder="t('skills.selectDimension') || 'Select dimension'" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="system" :disabled="!isAdmin">
                <div class="flex items-center gap-2">
                  <Shield class="h-4 w-4 text-blue-500" />
                  <span>{{ t('skills.systemSkills') || 'System Skills' }}</span>
                </div>
              </SelectItem>
              <SelectItem value="user">
                <div class="flex items-center gap-2">
                  <User class="h-4 w-4 text-primary" />
                  <span>{{ t('skills.mySkills') || 'My Skills' }}</span>
                </div>
              </SelectItem>
              <SelectItem value="agent">
                <div class="flex items-center gap-2">
                  <Bot class="h-4 w-4 text-purple-500" />
                  <span>{{ t('skills.agentSkills') || 'Agent Skills' }}</span>
                </div>
              </SelectItem>
            </SelectContent>
          </Select>

          <!-- Agent Selection (show when agent dimension is selected) -->
          <div v-if="importTargetDimension === 'agent'" class="space-y-2">
            <Label>{{ t('skills.selectAgent') || 'Select Agent' }}</Label>
            <Select v-model="selectedAgent">
              <SelectTrigger>
                <SelectValue :placeholder="t('skills.selectAgentPlaceholder') || 'Select an agent'" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="agent in userAgents" :key="agent.id" :value="agent.id">
                  <div class="flex items-center gap-2">
                    <Bot class="h-4 w-4" />
                    <span>{{ agent.name || agent.id }}</span>
                  </div>
                </SelectItem>
                <SelectItem v-if="userAgents.length === 0" value="__no_agent__" disabled>
                  <span class="text-muted-foreground text-sm">{{ t('skills.noAgents') || 'No agents available' }}</span>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <!-- Import Method Tabs -->
        <Tabs v-model="importMode" class="w-full mt-4">
          <TabsList class="grid w-full grid-cols-2">
            <TabsTrigger value="upload">{{ t('skills.upload') || 'Upload' }}</TabsTrigger>
            <TabsTrigger value="url">{{ t('skills.urlImport') || 'URL' }}</TabsTrigger>
          </TabsList>

          <TabsContent value="upload" class="space-y-4 mt-4">
            <div
              class="border-2 border-dashed rounded-lg p-8 text-center hover:bg-muted/50 transition-colors cursor-pointer"
              :class="{ 'border-primary bg-primary/5': isDragging }"
              @click="$refs.fileInput.click()"
              @drop.prevent="handleDrop"
              @dragover.prevent="isDragging = true"
              @dragleave.prevent="isDragging = false"
            >
              <input
                type="file"
                ref="fileInput"
                class="hidden"
                accept=".zip"
                @change="handleFileChange"
              >
              <div class="flex flex-col items-center justify-center gap-3">
                <div class="p-3 rounded-full bg-muted">
                  <Upload class="h-6 w-6 text-muted-foreground" />
                </div>
                <div>
                  <p class="text-sm font-medium">{{ t('skills.dropFile') || 'Drop ZIP file here or click to browse' }}</p>
                  <p class="text-xs text-muted-foreground mt-1">{{ t('skills.zipOnly') || 'Only ZIP files are supported' }}</p>
                </div>
                <div v-if="selectedFile" class="mt-2 px-3 py-1.5 bg-primary/10 rounded text-sm font-medium text-primary">
                  {{ selectedFile.name }}
                </div>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="url" class="space-y-4 mt-4">
            <div class="space-y-2">
              <Label for="url">{{ t('skills.urlLabel') || 'Skill URL' }}</Label>
              <div class="flex items-center gap-2">
                <span class="text-sm text-muted-foreground">https://</span>
                <Input
                  id="url"
                  v-model="importUrl"
                  :placeholder="t('skills.urlPlaceholder') || 'example.com/skill.zip'"
                  class="flex-1"
                />
              </div>
            </div>
          </TabsContent>
        </Tabs>

        <Alert v-if="importError" variant="destructive">
          <AlertCircle class="h-4 w-4" />
          <AlertTitle>{{ t('common.error') || 'Error' }}</AlertTitle>
          <AlertDescription>{{ importError }}</AlertDescription>
        </Alert>

        <DialogFooter>
          <Button variant="outline" @click="showImportModal = false">
            {{ t('common.cancel') || 'Cancel' }}
          </Button>
          <Button
            @click="handleImport"
            :disabled="isImportDisabled || importing"
          >
            <Loader v-if="importing" class="mr-2 h-4 w-4 animate-spin" />
            {{ t('skills.import') || 'Import' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Edit Dialog -->
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
          <Button variant="outline" @click="showEditModal = false">
            {{ t('common.cancel') || 'Cancel' }}
          </Button>
          <Button @click="saveSkillContent" :disabled="saving">
            <Loader v-if="saving" class="mr-2 h-4 w-4 animate-spin" />
            {{ t('common.save') || 'Save' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Delete Confirmation Dialog -->
    <Dialog v-model:open="showDeleteDialog">
      <DialogContent class="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{{ t('skills.deleteConfirmTitle') || 'Delete Skill' }}</DialogTitle>
          <DialogDescription>
            {{ t('skills.deleteConfirmDesc', { name: skillToDelete?.name }) || `Are you sure you want to delete "${skillToDelete?.name}"? This action cannot be undone.` }}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" @click="showDeleteDialog = false">
            {{ t('common.cancel') || 'Cancel' }}
          </Button>
          <Button variant="destructive" @click="executeDelete" :disabled="deleting">
            <Loader v-if="deleting" class="mr-2 h-4 w-4 animate-spin" />
            {{ t('common.delete') || 'Delete' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import {
  Box,
  Search,
  Plus,
  Upload,
  Loader,
  Trash2,
  Layers,
  User,
  Shield,
  Edit,
  Bot,
  MoreVertical,
  AlertCircle
} from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { skillAPI } from '../api/skill.js'
import { agentAPI } from '../api/agent.js'
import { getCurrentUser } from '../utils/auth.js'

// shadcn components
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { toast } from 'vue-sonner'

// Composables
const { t } = useLanguage()

// State
const skills = ref([])
const loading = ref(false)
const searchTerm = ref('')
const selectedDimension = ref('all')
const currentUser = ref({ userid: '', role: 'user' })

// Import dialog state
const showImportModal = ref(false)
const importMode = ref('upload')
const importTargetDimension = ref('user')
const selectedFile = ref(null)
const importUrl = ref('')
const importing = ref(false)
const importError = ref('')
const isDragging = ref(false)
const fileInput = ref(null)

// Edit dialog state
const showEditModal = ref(false)
const editingSkill = ref(null)
const skillContent = ref('')
const saving = ref(false)

// Delete dialog state
const showDeleteDialog = ref(false)
const skillToDelete = ref(null)
const deleting = ref(false)

// Agent selection (for agent dimension import)
const selectedAgent = ref('')

// Computed
const isAdmin = computed(() => {
  return currentUser.value.role?.toLowerCase() === 'admin'
})

const counts = computed(() => ({
  all: skills.value.length,
  system: skills.value.filter(s => s.dimension === 'system').length,
  user: skills.value.filter(s => s.dimension === 'user' && s.owner_user_id === currentUser.value.userid).length,
  agent: skills.value.filter(s => s.dimension === 'agent' && s.owner_user_id === currentUser.value.userid).length
}))

const displayedSkills = computed(() => {
  let result = skills.value

  // Dimension filtering
  if (selectedDimension.value !== 'all') {
    result = result.filter(s => s.dimension === selectedDimension.value)
    // For user and agent dimensions, only show own skills
    if (selectedDimension.value === 'user' || selectedDimension.value === 'agent') {
      result = result.filter(s => s.owner_user_id === currentUser.value.userid)
    }
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

const canImportToCurrentDimension = computed(() => {
  if (selectedDimension.value === 'system') return isAdmin.value
  return selectedDimension.value !== 'all'
})

const isImportDisabled = computed(() => {
  // Upload mode requires file
  if (importMode.value === 'upload') {
    if (!selectedFile.value) return true
  }
  // URL mode requires URL
  if (importMode.value === 'url') {
    if (!importUrl.value) return true
  }
  // Agent dimension requires agent selection
  if (importTargetDimension.value === 'agent') {
    if (!selectedAgent.value) return true
  }
  return false
})

// Methods
const getDimensionBadgeVariant = (dimension) => {
  switch (dimension) {
    case 'system': return 'default'
    case 'user': return 'secondary'
    case 'agent': return 'outline'
    default: return 'secondary'
  }
}

const getDimensionIcon = (dimension) => {
  switch (dimension) {
    case 'system': return Shield
    case 'user': return User
    case 'agent': return Bot
    default: return Box
  }
}

const getDimensionLabel = (dimension) => {
  switch (dimension) {
    case 'system': return t('skills.system') || 'System'
    case 'user': return t('skills.user') || 'User'
    case 'agent': return t('skills.agent') || 'Agent'
    default: return dimension
  }
}

const getImportLabel = () => {
  switch (selectedDimension.value) {
    case 'system': return t('skills.importSystem') || 'Import System Skill'
    case 'agent': return t('skills.importAgent') || 'Import Agent Skill'
    default: return t('skills.import') || 'Import Skill'
  }
}

const canDelete = (skill) => {
  if (isAdmin.value) return true
  if (skill.dimension === 'system') return false
  return skill.owner_user_id === currentUser.value.userid
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
    toast.error(t('skills.loadFailed') || 'Failed to load skills')
  } finally {
    loading.value = false
  }
}

const openImportModal = () => {
  importTargetDimension.value = selectedDimension.value === 'all' ? 'user' : selectedDimension.value
  importMode.value = 'upload'
  selectedFile.value = null
  importUrl.value = ''
  importError.value = ''
  showImportModal.value = true
}

const openImportModalWithDimension = () => {
  importTargetDimension.value = selectedDimension.value
  openImportModal()
}

const handleFileChange = (event) => {
  const file = event.target.files[0]
  processFile(file)
}

const handleDrop = (event) => {
  isDragging.value = false
  const file = event.dataTransfer.files[0]
  processFile(file)
}

const processFile = (file) => {
  if (!file) return
  if (!file.name.endsWith('.zip')) {
    importError.value = t('skills.zipOnly') || 'Only ZIP files are supported'
    selectedFile.value = null
    if (fileInput.value) fileInput.value.value = ''
    return
  }
  selectedFile.value = file
  importError.value = ''
}

const handleImport = async () => {
  importing.value = true
  importError.value = ''

  try {
    const isSystemSkill = importTargetDimension.value === 'system'
    const isAgentSkill = importTargetDimension.value === 'agent'

    const importParams = {
      is_system: isSystemSkill,
      is_agent: isAgentSkill,
      agent_id: isAgentSkill ? selectedAgent.value : undefined
    }

    if (importMode.value === 'upload') {
      if (!selectedFile.value) return
      await skillAPI.uploadSkill(selectedFile.value, isSystemSkill, importParams)
    } else {
      if (!importUrl.value) return
      await skillAPI.importSkillFromUrl({
        url: importUrl.value,
        is_system: isSystemSkill,
        is_agent: isAgentSkill,
        agent_id: isAgentSkill ? selectedAgent.value : undefined
      })
    }

    await loadSkills()
    showImportModal.value = false
    selectedFile.value = null
    importUrl.value = ''
    if (fileInput.value) fileInput.value.value = ''
    toast.success(t('skills.importSuccess') || 'Skill imported successfully')
  } catch (error) {
    console.error('Import failed:', error)
    importError.value = error.message || t('skills.importFailed') || 'Import failed'
  } finally {
    importing.value = false
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
    toast.error(t('skills.loadContentFailed') || 'Failed to load skill content')
    showEditModal.value = false
  }
}

const saveSkillContent = async () => {
  if (!editingSkill.value) return

  try {
    saving.value = true
    await skillAPI.updateSkillContent(editingSkill.value.name, skillContent.value)
    toast.success(t('skills.updateSuccess') || 'Skill updated successfully')
    showEditModal.value = false
    loadSkills()
  } catch (error) {
    console.error('Failed to update skill:', error)
    toast.error(t('skills.updateFailed') || 'Failed to update skill')
  } finally {
    saving.value = false
  }
}

const confirmDelete = (skill) => {
  skillToDelete.value = skill
  showDeleteDialog.value = true
}

const executeDelete = async () => {
  if (!skillToDelete.value) return

  try {
    deleting.value = true
    await skillAPI.deleteSkill(skillToDelete.value.name)
    toast.success(t('skills.deleteSuccess') || 'Skill deleted successfully')
    showDeleteDialog.value = false
    await loadSkills()
  } catch (error) {
    toast.error(t('skills.deleteFailed') || 'Failed to delete skill')
  } finally {
    deleting.value = false
    skillToDelete.value = null
  }
}

onMounted(async () => {
  const user = await getCurrentUser()
  if (user) {
    currentUser.value = user
  }
  loadSkills()
  loadUserAgents()
})

// Load user agents for agent skill import
const loadUserAgents = async () => {
  try {
    const response = await agentAPI.getAgents()
    if (response && response.agents) {
      userAgents.value = response.agents
    }
  } catch (error) {
    console.error('Failed to load agents:', error)
  }
}

</script>
