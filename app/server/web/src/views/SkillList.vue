<template>
  <div ref="skillListRoot" tabindex="-1" class="h-full w-full bg-background flex flex-col overflow-hidden outline-none">
    <!-- Header Area -->
    <div class="flex-none bg-background border-b">
      <div class="flex items-center justify-between gap-4">
        <div class="p-4 md:px-6 pb-4 flex items-center gap-2 overflow-x-auto no-scrollbar pb-1">
          <Tabs v-model="selectedDimension" class="w-full">
            <TabsList class="grid w-full max-w-md grid-cols-2 bg-transparent h-auto gap-2">
              <TabsTrigger value="system" class="gap-2 rounded-full border data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:border-primary shadow-none">
              <Shield class="h-4 w-4" />
              <span>{{ t('skills.system') }}</span>
              <span class="ml-1 text-xs opacity-70 bg-black/10 dark:bg-white/10 px-1.5 rounded-full">{{ counts.system }}</span>
            </TabsTrigger>
              <TabsTrigger value="user" class="gap-2 rounded-full border data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:border-primary shadow-none">
              <User class="h-4 w-4" />
              <span>{{ t('skills.mine')  }}</span>
              <span class="ml-1 text-xs opacity-70 bg-black/10 dark:bg-white/10 px-1.5 rounded-full">{{ counts.user }}</span>
            </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        <div class="flex items-center gap-3">
          <div class="inline-flex rounded-md border bg-background p-0.5">
            <Button
              variant="ghost"
              size="sm"
              class="h-8 px-2"
              :class="viewMode === 'card' ? 'bg-primary/10 text-primary' : 'text-muted-foreground'"
              @click="viewMode = 'card'"
            >
              <LayoutGrid class="h-4 w-4 mr-1" />
              {{ t('skills.viewCard') }}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              class="h-8 px-2"
              :class="viewMode === 'list' ? 'bg-primary/10 text-primary' : 'text-muted-foreground'"
              @click="viewMode = 'list'"
            >
              <List class="h-4 w-4 mr-1" />
              {{ t('skills.viewList') }}
            </Button>
          </div>
          <div class="relative w-64">
            <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input v-model="searchTerm" :placeholder="t('skills.searchPlaceholder')"
              class="pl-9 h-10" />
          </div>
          <Button @click="openImportModal" class="gap-2">
            <Plus class="h-4 w-4" />
            {{ t('skills.import') }}
          </Button>
        </div>
      </div>
    </div>

    <!-- Main Content Area -->
    <div class="flex-1 overflow-hidden p-6">
      <div v-if="loading" class="flex flex-col items-center justify-center h-full">
        <Loader class="h-8 w-8 animate-spin text-primary" />
        <p class="text-sm text-muted-foreground mt-2">{{ t('common.loading') }}</p>
      </div>

      <div v-else-if="displayedSkills.length === 0"
        class="flex flex-col items-center justify-center h-full text-center">
        <div class="rounded-full bg-muted/50 p-6 mb-4">
          <Box class="h-10 w-10 text-muted-foreground/50" />
        </div>
        <h3 class="text-lg font-medium text-foreground">{{ t('skills.noSkills') }}</h3>
        <p class="text-sm text-muted-foreground mt-1 max-w-xs mx-auto">
          {{ searchTerm ? t('skills.noSearchResults') : t('skills.noSkillsDesc') }}
        </p>
        <Button variant="outline" class="mt-4" @click="openImportModal">
          <Plus class="mr-2 h-4 w-4" />
          {{ t('skills.import') }}
        </Button>
      </div>

      <ScrollArea v-else class="h-full">
        <div class="space-y-2 pr-4">
          <!-- Card View -->
          <div v-if="viewMode === 'card'" class="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 pb-20">
            <Card
              class="flex flex-col items-center justify-center border-dashed border-2 cursor-pointer hover:border-primary/50 hover:bg-muted/50 transition-all duration-300 min-h-[140px]"
              @click="openImportModal"
            >
              <div class="flex flex-col items-center gap-2 text-muted-foreground hover:text-primary transition-colors">
                <div class="p-2 rounded-full bg-muted/50">
                  <Plus class="h-6 w-6" />
                </div>
                <span class="font-medium">{{ t('skills.import') }}</span>
              </div>
            </Card>

            <Card v-for="skill in displayedSkills" :key="skill.name"
              class="group hover:shadow-md transition-all duration-300 border-muted/60 hover:border-primary/50 bg-card">
              <CardHeader class="flex flex-row items-start gap-4 space-y-0 pb-3">
                <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary group-hover:bg-primary group-hover:text-primary-foreground transition-colors">
                  <Box class="h-5 w-5" />
                </div>

                <div class="space-y-1 overflow-hidden flex-1">
                  <div class="flex items-center justify-between">
                    <CardTitle class="text-base truncate" :title="skill.name">
                      {{ skill.name }}
                    </CardTitle>
                    <DropdownMenu v-if="canEdit(skill) || canDelete(skill)" :modal="false">
                      <DropdownMenuTrigger as-child>
                        <Button variant="ghost" size="icon" class="h-7 w-7 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity">
                          <MoreVertical class="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" class="w-40">
                        <DropdownMenuItem v-if="canEdit(skill)" @select="handleEditAction(skill)">
                          <Edit class="h-4 w-4 mr-2" />
                          {{ t('skills.edit') }}
                        </DropdownMenuItem>
                        <DropdownMenuSeparator v-if="canEdit(skill) && canDelete(skill)" />
                        <DropdownMenuItem v-if="canDelete(skill)" class="text-destructive focus:text-destructive"
                          @select="handleDeleteAction(skill)">
                          <Trash2 class="h-4 w-4 mr-2" />
                          {{ t('skills.delete') }}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                  <CardDescription class="line-clamp-2 text-xs">
                    {{ skill.description || t('skills.noDescription') }}
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent class="pt-0 pb-3">
                <div class="flex items-center gap-2 mt-2 text-xs text-muted-foreground">
                  <Badge variant="outline" class="text-[10px]">
                    {{ selectedDimension === 'system' ? t('skills.system') : t('skills.mine') }}
                  </Badge>
                  <Badge v-if="skill.owner_user_id === currentUser.userid" variant="secondary" class="text-[10px]">
                    {{ t('skills.mySkill') }}
                  </Badge>
                </div>
              </CardContent>
            </Card>
          </div>

          <!-- List View -->
          <div v-else class="space-y-2 pb-20">
            <Card
              class="border-dashed border-2 cursor-pointer hover:border-primary/50 hover:bg-muted/50 transition-all duration-300"
              @click="openImportModal"
            >
              <CardContent class="py-3 flex items-center gap-3 text-muted-foreground hover:text-primary transition-colors">
                <Plus class="h-4 w-4" />
                <span class="font-medium">{{ t('skills.import') }}</span>
              </CardContent>
            </Card>

            <Card
              v-for="skill in displayedSkills"
              :key="`list-${skill.name}`"
              class="group border-muted/60 hover:border-primary/40 transition-all"
            >
              <CardContent class="py-3">
                <div class="flex items-start gap-3">
                  <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <Box class="h-4 w-4" />
                  </div>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center justify-between gap-2">
                      <div class="min-w-0">
                        <div class="font-medium text-sm truncate" :title="skill.name">{{ skill.name }}</div>
                        <div class="text-xs text-muted-foreground line-clamp-1 mt-0.5">
                          {{ skill.description || t('skills.noDescription') }}
                        </div>
                      </div>
                      <div class="flex items-center gap-1">
                        <Button
                          v-if="canEdit(skill)"
                          variant="ghost"
                          size="icon"
                          class="h-7 w-7 text-muted-foreground hover:text-primary"
                          @click.stop="openEditModal(skill)"
                        >
                          <Edit class="h-4 w-4" />
                        </Button>
                        <Button
                          v-if="canDelete(skill)"
                          variant="ghost"
                          size="icon"
                          class="h-7 w-7 text-muted-foreground hover:text-destructive"
                          @click.stop="confirmDelete(skill)"
                        >
                          <Trash2 class="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                    <div class="mt-2 inline-flex items-center gap-1 bg-primary/5 px-2 py-1 rounded text-primary/80 text-xs">
                      <component :is="selectedDimension === 'system' ? Shield : User" class="h-3 w-3" />
                      <span>{{ selectedDimension === 'system' ? (t('skills.system') || 'System') : (t('skills.mine') || 'Mine') }}</span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </ScrollArea>
    </div>

    <!-- Import Dialog -->
    <Dialog :open="showImportModal" @update:open="showImportModal = $event">
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
            </SelectContent>
          </Select>
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
              :class="{ 'border-primary bg-primary/5': isDragging }" @click="$refs.fileInput.click()"
              @drop.prevent="handleDrop" @dragover.prevent="isDragging = true" @dragleave.prevent="isDragging = false">
              <input type="file" ref="fileInput" class="hidden" accept=".zip" @change="handleFileChange">
                <div class="flex flex-col items-center justify-center gap-3">
                  <div class="p-3 rounded-full bg-muted">
                    <Upload class="h-6 w-6 text-muted-foreground" />
                  </div>
                  <div>
                    <p class="text-sm font-medium">{{ t('skills.dropFile') || 'Drop ZIP file here or click to browse' }}
                    </p>
                    <p class="text-xs text-muted-foreground mt-1">{{ t('skills.zipOnly') || 'Only ZIP files are supported' }}</p>
                  </div>
                  <div v-if="selectedFile"
                    class="mt-2 px-3 py-1.5 bg-primary/10 rounded text-sm font-medium text-primary">
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
                <Input id="url" v-model="importUrl" :placeholder="t('skills.urlPlaceholder') || 'example.com/skill.zip'"
                  class="flex-1" />
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
          <Button @click="handleImport" :disabled="isImportDisabled || importing">
            <Loader v-if="importing" class="mr-2 h-4 w-4 animate-spin" />
            {{ t('skills.import') || 'Import' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Edit Dialog -->
    <Dialog v-model:open="showEditModal">
      <DialogContent
        class="sm:max-w-[800px] sm:h-[80vh] flex flex-col"
        @close-auto-focus="handleEditDialogCloseAutoFocus"
      >
        <DialogHeader>
          <DialogTitle>{{ t('skills.edit') }} - {{ editingSkill?.name }}</DialogTitle>
          <DialogDescription>
            {{ t('skills.editDesc') || 'Edit SKILL.md content' }}
          </DialogDescription>
        </DialogHeader>

        <div class="flex-1 min-h-0 py-4">
          <Textarea v-model="skillContent" class="h-full font-mono text-sm resize-none"
            :placeholder="t('skills.contentPlaceholder') || 'Enter markdown content...'" />
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

    <!-- Delete Confirmation Popover -->
    <div v-if="showDeleteDialog" class="fixed inset-0 z-50 flex items-center justify-center">
      <div class="absolute inset-0 bg-black/50" @click="showDeleteDialog = false"></div>
      <Card class="relative z-10 w-full max-w-md mx-4">
        <CardHeader>
          <CardTitle class="text-lg">{{ t('skills.deleteConfirmTitle') || 'Delete Confirmation' }}</CardTitle>
          <CardDescription>
            {{ t('skills.deleteSkillConfirm', { name: skillToDelete?.name }) || `确定要删除 Skill "${skillToDelete?.name}" 吗？此操作无法撤销。` }}
          </CardDescription>
        </CardHeader>
        <CardFooter class="flex justify-end gap-3 pt-4">
          <Button variant="outline" @click="showDeleteDialog = false">
            {{ t('common.cancel') || 'Cancel' }}
          </Button>
          <Button variant="destructive" @click="executeDelete" :disabled="deleting">
            <Loader v-if="deleting" class="mr-2 h-4 w-4 animate-spin" />
            {{ t('common.delete') || 'Delete' }}
          </Button>
        </CardFooter>
      </Card>
    </div>

  </div>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import {
  Box,
  Search,
  Plus,
  Upload,
  Loader,
  Trash2,
  User,
  Shield,
  Edit,
  LayoutGrid,
  List,
  MoreVertical,
  AlertCircle
} from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { useSkillList } from '../composables/skill/useSkillList.js'

// shadcn components
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from '@/components/ui/card'
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

// Composables
const { t } = useLanguage()
const viewMode = ref('card')
const skillListRoot = ref(null)

// Use the skill list composable
const {
  // State
  searchTerm,
  selectedDimension,
  currentUser,
  loading,
  showImportModal,
  importMode,
  importTargetDimension,
  selectedFile,
  importUrl,
  importing,
  importError,
  isDragging,
  fileInput,
  showEditModal,
  editingSkill,
  skillContent,
  saving,
  showDeleteDialog,
  skillToDelete,
  deleting,

  // Computed
  isAdmin,
  counts,
  displayedSkills,
  isImportDisabled,

  // Methods
  canEdit,
  canDelete,
  openImportModal,
  handleFileChange,
  handleDrop,
  handleImport,
  openEditModal,
  saveSkillContent,
  confirmDelete,
  executeDelete
} = useSkillList(t)

const restoreSkillListFocus = () => {
  if (typeof document !== 'undefined' && document.activeElement instanceof HTMLElement) {
    document.activeElement.blur()
  }

  if (typeof document !== 'undefined') {
    if (document.body?.style?.pointerEvents === 'none') {
      document.body.style.pointerEvents = ''
    }

    if (document.documentElement?.style?.pointerEvents === 'none') {
      document.documentElement.style.pointerEvents = ''
    }
  }

  const focusRoot = () => {
    skillListRoot.value?.focus?.()
  }

  if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
    window.requestAnimationFrame(focusRoot)
    return
  }

  focusRoot()
}

const handleEditDialogCloseAutoFocus = (event) => {
  event.preventDefault()
  restoreSkillListFocus()
}

watch(showEditModal, async (open, wasOpen) => {
  if (!open && wasOpen) {
    await nextTick()
    restoreSkillListFocus()
  }
})

const queueMenuAction = (callback) => {
  if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
    window.requestAnimationFrame(callback)
    return
  }

  setTimeout(callback, 0)
}

const handleEditAction = (skill) => {
  queueMenuAction(() => {
    void openEditModal(skill)
  })
}

const handleDeleteAction = (skill, agentId = null) => {
  queueMenuAction(() => {
    confirmDelete(skill, agentId)
  })
}
</script>
