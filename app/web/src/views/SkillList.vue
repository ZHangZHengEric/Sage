<template>
  <div class="h-full w-full bg-background flex flex-col overflow-hidden">
    <!-- Header Area -->
    <div class="flex-none bg-background border-b px-6 py-4">
      <div class="flex items-center justify-between gap-4">
     <!-- Dimension Filter Tabs -->
      <div class="mt-4">
        <Tabs v-model="selectedDimension" class="w-full">
          <TabsList class="grid w-full max-w-md grid-cols-2">
            <TabsTrigger value="system" class="gap-2">
              <Shield class="h-4 w-4" />
              <span>{{ t('skills.system') }}</span>
              <Badge variant="secondary" class="ml-1 text-xs">{{ counts.system }}</Badge>
            </TabsTrigger>
            <TabsTrigger value="user" class="gap-2">
              <User class="h-4 w-4" />
              <span>{{ t('skills.mine')  }}</span>
              <Badge variant="secondary" class="ml-1 text-xs">{{ counts.user }}</Badge>
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
        <!-- Actions -->
        <div class="flex items-center gap-3">
          <div class="relative w-64">
            <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input v-model="searchTerm" :placeholder="t('skills.searchPlaceholder') || 'Search skills...'"
              class="pl-9 h-10" />
          </div>
          <Button @click="openImportModal" class="gap-2">
            <Plus class="h-4 w-4" />
            {{ t('skills.import') || 'Import' }}
          </Button>
        </div>
      </div>

 
    </div>

    <!-- Main Content Area -->
    <div class="flex-1 overflow-hidden p-6">
      <div v-if="loading" class="flex flex-col items-center justify-center h-full">
        <Loader class="h-8 w-8 animate-spin text-primary" />
        <p class="text-sm text-muted-foreground mt-2">{{ t('common.loading') || 'Loading...' }}</p>
      </div>

      <div v-else-if="displayedSkills.length === 0"
        class="flex flex-col items-center justify-center h-full text-center">
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
          <!-- Skill Items -->
          <Card v-for="skill in displayedSkills" :key="skill.name"
            class="group hover:shadow-md transition-all duration-200">
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
                      <p class="text-sm text-muted-foreground line-clamp-3 mt-1">
                        {{ skill.description || t('skills.noDescription') }}
                      </p>
                    </div>

                    <!-- Actions -->
                    <DropdownMenu v-if="canEdit(skill) || canDelete(skill)">
                      <DropdownMenuTrigger as-child>
                        <Button variant="ghost" size="icon" class="h-8 w-8 shrink-0">
                          <MoreVertical class="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" class="w-40">
                        <DropdownMenuItem v-if="canEdit(skill)" @click="openEditModal(skill)">
                          <Edit class="h-4 w-4 mr-2" />
                          {{ t('skills.edit') || 'Edit' }}
                        </DropdownMenuItem>
                        <DropdownMenuSeparator v-if="canEdit(skill) && canDelete(skill)" />
                        <DropdownMenuItem v-if="canDelete(skill)" class="text-destructive focus:text-destructive"
                          @click="confirmDelete(skill)">
                          <Trash2 class="h-4 w-4 mr-2" />
                          {{ t('skills.delete') || 'Delete' }}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
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
      <DialogContent class="sm:max-w-[800px] sm:h-[80vh] flex flex-col">
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

    <!-- Delete Confirmation Dialog -->
    <Dialog v-model:open="showDeleteDialog">
      <DialogContent class="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{{ t('skills.deleteConfirmTitle') || 'Delete Skill' }}</DialogTitle>
          <DialogDescription>
            {{ t('skills.deleteConfirmDesc', { name: skillToDelete?.name }) || `Are you sure you want to delete
            "${skillToDelete?.name}"? This action cannot be undone.` }}
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

// Composables
const { t } = useLanguage()

// Use the skill list composable
const {
  // State
  searchTerm,
  selectedDimension,
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
  getDimensionBadgeVariant,
  getDimensionIcon,
  getDimensionLabel,
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
</script>
