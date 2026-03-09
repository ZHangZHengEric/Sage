<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex items-center justify-between p-6 border-b">
      <div>
        <h2 class="text-lg font-medium">{{ t('system.versionManagement') }}</h2>
        <p class="text-sm text-muted-foreground mt-1">Manage application versions and release notes</p>
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
        <p>No versions found</p>
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
                  <MarkdownRenderer :content="version.release_notes || 'No release notes.'" />
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
                      <div>
                        <p class="text-sm font-medium">{{ getPlatformName(artifact.platform) }}</p>
                        <p class="text-xs text-muted-foreground truncate max-w-[200px]" :title="artifact.url">{{ artifact.url }}</p>
                      </div>
                    </div>
                    <Button variant="ghost" size="icon" as-child>
                      <a :href="artifact.url" target="_blank">
                        <Download class="w-4 h-4" />
                      </a>
                    </Button>
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
            Publish a new version with artifacts for different platforms.
          </DialogDescription>
        </DialogHeader>
        
        <div class="grid gap-4 py-4">
          <div class="grid grid-cols-4 items-center gap-4">
            <Label class="text-right">Version</Label>
            <Input v-model="form.version" placeholder="1.0.0" class="col-span-3" />
          </div>
          
          <div class="grid grid-cols-4 gap-4">
            <Label class="text-right pt-2">Release Notes</Label>
            <Textarea v-model="form.release_notes" placeholder="Markdown supported..." class="col-span-3 h-[150px]" />
          </div>

          <Separator class="my-2" />
          
          <div class="space-y-4">
            <div class="flex items-center justify-between">
              <Label class="text-base font-medium">Artifacts</Label>
              <Button size="sm" variant="outline" @click="addArtifact">
                <Plus class="w-3 h-3 mr-1" /> Add
              </Button>
            </div>

            <div v-for="(artifact, index) in form.artifacts" :key="index" class="p-4 border rounded-lg space-y-3 bg-muted/30">
              <div class="flex justify-between items-center">
                <span class="text-sm font-medium">Artifact #{{ index + 1 }}</span>
                <Button variant="ghost" size="icon" @click="removeArtifact(index)" class="h-6 w-6">
                  <X class="w-3 h-3" />
                </Button>
              </div>
              
              <div class="grid grid-cols-2 gap-3">
                <div class="space-y-1">
                  <Label class="text-xs">Platform</Label>
                  <Select v-model="artifact.platform">
                    <SelectTrigger>
                      <SelectValue placeholder="Select platform" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="darwin-aarch64">macOS (Apple Silicon)</SelectItem>
                      <SelectItem value="darwin-x86_64">macOS (Intel)</SelectItem>
                      <SelectItem value="windows-x86_64">Windows (x64)</SelectItem>
                      <SelectItem value="linux-x86_64">Linux (x64)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                
                <div class="space-y-1">
                  <Label class="text-xs">File Upload</Label>
                  <div class="flex gap-2">
                    <Input 
                      v-model="artifact.url" 
                      placeholder="https://..." 
                      class="flex-1"
                    />
                    <div class="relative">
                      <input
                        type="file"
                        class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                        @change="(e) => handleFileUpload(e, index)"
                      />
                      <Button variant="secondary" size="icon" :disabled="uploading[index]">
                        <Loader2 v-if="uploading[index]" class="w-4 h-4 animate-spin" />
                        <Upload v-else class="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              </div>

              <div class="space-y-1">
                <Label class="text-xs">Signature (Optional)</Label>
                <Textarea v-model="artifact.signature" placeholder="Paste .sig content here..." class="h-[60px] font-mono text-xs" />
              </div>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" @click="showCreateDialog = false">Cancel</Button>
          <Button @click="handleSubmit" :disabled="submitting">
            <Loader2 v-if="submitting" class="w-4 h-4 mr-2 animate-spin" />
            {{ submitting ? 'Creating...' : 'Create Version' }}
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
    artifacts: [{ platform: '', url: '', signature: '' }]
  }
  uploading.value = {}
}

const openCreateDialog = () => {
  resetForm()
  showCreateDialog.value = true
}

const addArtifact = () => {
  form.value.artifacts.push({ platform: '', url: '', signature: '' })
}

const removeArtifact = (index) => {
  form.value.artifacts.splice(index, 1)
  delete uploading.value[index]
}

const handleFileUpload = async (event, index) => {
  const file = event.target.files[0]
  if (!file) return

  uploading.value[index] = true
  try {
    const res = await ossAPI.upload(file)
    if (res && res.url) {
      form.value.artifacts[index].url = res.url
      toast.success('File uploaded successfully')
    } else {
      toast.error('Upload failed')
    }
  } catch (error) {
    console.error(error)
    toast.error('Upload failed')
  } finally {
    uploading.value[index] = false
  }
}

const handleSubmit = async () => {
  if (!form.value.version) {
    toast.error('Version is required')
    return
  }
  if (form.value.artifacts.length === 0) {
    toast.error('At least one artifact is required')
    return
  }
  if (form.value.artifacts.some(a => !a.platform || !a.url)) {
    toast.error('Platform and URL are required for all artifacts')
    return
  }

  submitting.value = true
  try {
     await systemAPI.createVersion(form.value)
     showCreateDialog.value = false
     toast.success('Version created successfully')
     fetchVersions()
  } catch (error) {
    console.error(error)
    toast.error(error.response?.data?.detail || 'Failed to create version')
  } finally {
    submitting.value = false
  }
}

const handleDelete = async (version) => {
  if (!confirm(`Are you sure you want to delete version ${version.version}?`)) return
  
  try {
    await systemAPI.deleteVersion(version.version)
    toast.success('Version deleted')
    fetchVersions()
  } catch (error) {
    console.error(error)
    toast.error('Delete failed')
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
    toast.error('Failed to load versions')
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
    'darwin-aarch64': 'macOS (Apple Silicon)',
    'darwin-x86_64': 'macOS (Intel)',
    'windows-x86_64': 'Windows (x64)',
    'linux-x86_64': 'Linux (x64)'
  }
  return map[platform] || platform
}

onMounted(() => {
  fetchVersions()
})
</script>
