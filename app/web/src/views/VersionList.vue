<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex items-center justify-between p-6 border-b">
      <div>
        <h2 class="text-lg font-medium">{{ t('system.versionManagement') }}</h2>
        <p class="text-sm text-muted-foreground mt-1">{{ t('system.version.description') }}</p>
      </div>
      <Button @click="openCreateDialog">
        <Plus class="w-4 h-4 mr-2" />
        {{ t('system.version.create') }}
      </Button>
    </div>

    <!-- Content -->
    <div class="flex-1 p-6 overflow-auto">
      <div v-if="loading" class="flex justify-center py-8">
        <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
      
      <div v-else-if="versions.length === 0" class="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <PackageX class="w-12 h-12 mb-4 opacity-50" />
        <p>{{ t('system.version.noVersions') }}</p>
      </div>

      <div v-else class="space-y-6">
        <Card v-for="version in versions" :key="version.version" class="overflow-hidden">
          <CardHeader class="bg-muted/30 pb-4">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-3">
                <CardTitle class="text-xl">v{{ version.version }}</CardTitle>
                <Badge variant="outline">{{ formatDate(version.pub_date) }}</Badge>
              </div>
              <Button variant="ghost" size="icon" @click="handleDelete(version)" class="text-destructive hover:text-destructive hover:bg-destructive/10">
                <Trash2 class="w-4 h-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent class="pt-6">
            <div class="grid md:grid-cols-2 gap-6">
              <!-- Release Notes -->
              <div>
                <h4 class="text-sm font-medium mb-2 flex items-center gap-2">
                  <FileText class="w-4 h-4" />
                  {{ t('system.version.releaseNotes') }}
                </h4>
                <ScrollArea class="h-[200px] w-full rounded-md border p-4">
                  <MarkdownRenderer :content="version.release_notes || t('system.version.noReleaseNotes')" />
                </ScrollArea>
              </div>

              <!-- Artifacts -->
              <div>
                <h4 class="text-sm font-medium mb-2 flex items-center gap-2">
                  <Package class="w-4 h-4" />
                  {{ t('system.version.artifacts') }}
                </h4>
                <div class="space-y-2">
                  <div v-for="artifact in version.artifacts" :key="artifact.platform" class="flex items-center justify-between p-3 rounded-lg border bg-card hover:bg-accent/50 transition-colors">
                    <div class="flex items-center gap-3">
                      <component :is="getPlatformIcon(artifact.platform)" class="w-5 h-5 text-muted-foreground" />
                      <div class="flex-1 min-w-0">
                        <p class="text-sm font-medium">{{ getPlatformName(artifact.platform) }}</p>
                        <div v-if="artifact.installer_url" class="flex items-center gap-2 mt-1">
                          <span class="text-[10px] uppercase font-bold text-muted-foreground bg-muted px-1.5 py-0.5 rounded">{{ t('system.version.installer') }}</span>
                          <a :href="artifact.installer_url" target="_blank" class="text-xs text-primary hover:underline truncate" :title="artifact.installer_url">
                            {{ artifact.installer_url.split('/').pop() }}
                          </a>
                        </div>
                        <div v-if="artifact.updater_url" class="flex items-center gap-2 mt-1">
                          <span class="text-[10px] uppercase font-bold text-muted-foreground bg-muted px-1.5 py-0.5 rounded">{{ t('system.version.updater') }}</span>
                          <a :href="artifact.updater_url" target="_blank" class="text-xs text-primary hover:underline truncate" :title="artifact.updater_url">
                            {{ artifact.updater_url.split('/').pop() }}
                          </a>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>

    <!-- Create Dialog -->
    <Dialog v-model:open="showCreateDialog">
      <DialogContent class="sm:max-w-[700px]">
        <DialogHeader>
          <DialogTitle>{{ t('system.version.create') }}</DialogTitle>
          <DialogDescription>
            {{ t('system.version.createDesc') }}
          </DialogDescription>
        </DialogHeader>
        
        <div class="grid gap-4 py-4">
          <div class="grid grid-cols-4 items-center gap-4">
            <Label class="text-right">{{ t('system.version.version') }}</Label>
            <Input v-model="form.version" placeholder="1.0.0" class="col-span-3" />
          </div>
          
          <div class="grid grid-cols-4 gap-4">
            <Label class="text-right pt-2">{{ t('system.version.releaseNotes') }}</Label>
            <Textarea v-model="form.release_notes" :placeholder="t('system.version.markdownSupported')" class="col-span-3 h-[150px]" />
          </div>

          <Separator class="my-2" />
          
          <div class="space-y-4">
            <div class="flex items-center justify-between">
              <Label class="text-base font-medium">{{ t('system.version.artifacts') }}</Label>
              <Button size="sm" variant="outline" @click="addArtifact">
                <Plus class="w-3 h-3 mr-1" /> {{ t('system.version.add') }}
              </Button>
            </div>

            <div v-for="(artifact, index) in form.artifacts" :key="index" class="p-4 border rounded-lg space-y-3 bg-muted/30">
              <div class="flex justify-between items-center">
                <span class="text-sm font-medium">{{ t('system.version.artifactNum', { n: index + 1 }) }}</span>
                <Button variant="ghost" size="icon" @click="removeArtifact(index)" class="h-6 w-6">
                  <X class="w-3 h-3" />
                </Button>
              </div>
              
              <div class="grid grid-cols-2 gap-3">
                <div class="space-y-1">
                  <Label class="text-xs">{{ t('system.version.platform') }}</Label>
                  <Select v-model="artifact.platform">
                    <SelectTrigger>
                      <SelectValue :placeholder="t('system.version.selectPlatform')" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="darwin-aarch64">{{ t('system.version.platformDarwinArm64') }}</SelectItem>
                      <SelectItem value="darwin-x86_64">{{ t('system.version.platformDarwinX64') }}</SelectItem>
                      <SelectItem value="windows-x86_64">{{ t('system.version.platformWindowsX64') }}</SelectItem>
                      <SelectItem value="linux-x86_64">{{ t('system.version.platformLinuxX64') }}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                
                <!-- Installer -->
                <div class="space-y-1">
                  <Label class="text-xs">{{ t('system.version.installerFile') }}</Label>
                  <div class="flex gap-2">
                    <Input 
                      v-model="artifact.installer_url" 
                      placeholder="https://..." 
                      class="flex-1"
                    />
                    <div class="relative">
                      <input
                        type="file"
                        class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                        @change="(e) => handleFileUpload(e, index, 'installer_url')"
                      />
                      <Button variant="secondary" size="icon" :disabled="uploading[`${index}_installer_url`]">
                        <Loader2 v-if="uploading[`${index}_installer_url`]" class="w-4 h-4 animate-spin" />
                        <Upload v-else class="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                </div>

                <!-- Updater -->
                <div class="space-y-1">
                  <Label class="text-xs">{{ t('system.version.updaterFile') }}</Label>
                  <div class="flex gap-2">
                    <Input 
                      v-model="artifact.updater_url" 
                      placeholder="https://..." 
                      class="flex-1"
                    />
                    <div class="relative">
                      <input
                        type="file"
                        class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                        @change="(e) => handleFileUpload(e, index, 'updater_url')"
                      />
                      <Button variant="secondary" size="icon" :disabled="uploading[`${index}_updater_url`]">
                        <Loader2 v-if="uploading[`${index}_updater_url`]" class="w-4 h-4 animate-spin" />
                        <Upload v-else class="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                </div>

                <!-- Signature -->
                <div class="space-y-1">
                  <Label class="text-xs">{{ t('system.version.updaterSignature') }}</Label>
                  <div class="flex gap-2">
                    <Textarea v-model="artifact.updater_signature" :placeholder="t('system.version.signaturePlaceholder')" class="h-[38px] min-h-[38px] font-mono text-xs flex-1 resize-none py-2" />
                     <div class="relative">
                      <input
                        type="file"
                        class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                        @change="(e) => handleSignatureUpload(e, index)"
                      />
                      <Button variant="secondary" size="icon">
                        <Upload class="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" @click="showCreateDialog = false">{{ t('common.cancel') }}</Button>
          <Button @click="handleSubmit" :disabled="submitting">
            <Loader2 v-if="submitting" class="w-4 h-4 mr-2 animate-spin" />
            {{ submitting ? t('common.creating') : t('system.version.create') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useLanguage } from '@/utils/i18n'
import { systemAPI } from '@/api/system'
import { ossAPI } from '@/api/oss'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Separator } from '@/components/ui/separator'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import { 
  Plus, Loader2, Package, FileText, Download, Trash2, 
  Apple, Monitor, X, Upload, PackageX 
} from 'lucide-vue-next'

const { t } = useLanguage()
const loading = ref(true)
const versions = ref([])
const showCreateDialog = ref(false)
const submitting = ref(false)
const uploading = ref({})

const form = ref({
  version: '',
  release_notes: '',
  artifacts: []
})

const resetForm = () => {
  form.value = {
    version: '',
    release_notes: '',
    artifacts: [{ platform: '', installer_url: '', updater_url: '', updater_signature: '' }]
  }
  uploading.value = {}
}

const openCreateDialog = () => {
  resetForm()
  showCreateDialog.value = true
}

const addArtifact = () => {
  form.value.artifacts.push({ platform: '', installer_url: '', updater_url: '', updater_signature: '' })
}

const removeArtifact = (index) => {
  form.value.artifacts.splice(index, 1)
  // clean up uploading keys if any
  Object.keys(uploading.value).forEach(k => {
    if (k.startsWith(`${index}_`)) delete uploading.value[k]
  })
}

const handleFileUpload = async (event, index, field) => {
  const file = event.target.files[0]
  if (!file) return

  if (!form.value.version) {
    toast.error(t('system.version.versionRequired'))
    event.target.value = ''
    return
  }

  const platform = form.value.artifacts[index].platform
  if (!platform) {
    toast.error(t('system.version.selectPlatform'))
    event.target.value = ''
    return
  }

  const uploadKey = `${index}_${field}`
  uploading.value[uploadKey] = true
  try {
    const version = form.value.version
    let filename = file.name
    
    let ext = ''
    if (filename.endsWith('.app.tar.gz')) {
      ext = '.app.tar.gz'
    } else if (filename.endsWith('.tar.gz')) {
      ext = '.tar.gz'
    } else {
      const dotIndex = filename.lastIndexOf('.')
      if (dotIndex !== -1) {
        ext = filename.substring(dotIndex)
      }
    }

    filename = `SageAI-${version}-${platform}${ext}`

    const path = `bundle/${version}/${filename}`
    const res = await ossAPI.upload(file, path)
    if (res && res.url) {
      form.value.artifacts[index][field] = res.url
      toast.success(t('system.version.uploadSuccess'))
    } else {
      toast.error(t('system.version.uploadError'))
    }
  } catch (error) {
    console.error(error)
    toast.error(t('system.version.uploadError'))
  } finally {
    uploading.value[uploadKey] = false
  }
}

const handleSignatureUpload = async (event, index) => {
  const file = event.target.files[0]
  if (!file) return

  const reader = new FileReader()
  reader.onload = (e) => {
    form.value.artifacts[index].updater_signature = e.target.result
    toast.success(t('system.version.signatureLoaded'))
  }
  reader.onerror = () => {
    toast.error(t('system.version.signatureReadError'))
  }
  reader.readAsText(file)
}

const handleSubmit = async () => {
  if (!form.value.version) {
    toast.error(t('system.version.versionRequired'))
    return
  }
  if (form.value.artifacts.length === 0) {
    toast.error(t('system.version.artifactRequired'))
    return
  }
  if (form.value.artifacts.some(a => !a.platform || (!a.installer_url && !a.updater_url))) {
    toast.error(t('system.version.platformAndUrlRequired'))
    return
  }

  submitting.value = true
  try {
     await systemAPI.createVersion(form.value)
     showCreateDialog.value = false
     toast.success(t('system.version.createSuccess'))
     fetchVersions()
  } catch (error) {
    console.error(error)
    toast.error(error.response?.data?.detail || t('system.version.createError'))
  } finally {
    submitting.value = false
  }
}

const handleDelete = async (version) => {
  if (!confirm(t('system.version.deleteConfirm', { version: version.version }))) return
  
  try {
    await systemAPI.deleteVersion(version.version)
    toast.success(t('system.version.deleteSuccess'))
    fetchVersions()
  } catch (error) {
    console.error(error)
    toast.error(t('system.version.deleteError'))
  }
}

const fetchVersions = async () => {
  loading.value = true
  try {
    const res = await systemAPI.getVersions()
    versions.value = res || []
  } catch (error) {
    console.error(error)
    // If backend 404s, suppress error if it means "no route" vs "no data"
    // But list_versions route exists.
    // If user means "latest" endpoint returning 404, that was fixed.
    // For list endpoint, it returns [].
    toast.error(t('system.version.loadError'))
  } finally {
    loading.value = false
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleDateString() + ' ' + new Date(dateStr).toLocaleTimeString()
}

const getPlatformIcon = (platform) => {
  if (platform.includes('darwin')) return Apple
  if (platform.includes('windows')) return Monitor
  return Package
}

const getPlatformName = (platform) => {
  const map = {
    'darwin-aarch64': t('system.version.platformDarwinArm64'),
    'darwin-x86_64': t('system.version.platformDarwinX64'),
    'windows-x86_64': t('system.version.platformWindowsX64'),
    'linux-x86_64': t('system.version.platformLinuxX64')
  }
  return map[platform] || platform
}

onMounted(() => {
  fetchVersions()
})
</script>
