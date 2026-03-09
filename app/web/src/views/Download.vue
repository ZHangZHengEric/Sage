<template>
  <div class="container mx-auto py-10 px-4 min-h-screen">
    <div class="max-w-3xl mx-auto space-y-8">
      <div class="text-center space-y-4 pt-10">
        <h1 class="text-4xl font-bold tracking-tight text-primary">{{ t('download.title') }}</h1>
        <p class="text-muted-foreground text-lg">
          {{ t('download.subtitle') }}
        </p>
      </div>

      <div v-if="loading" class="flex justify-center py-20">
        <LoadingBubble />
      </div>

      <div v-else-if="error" class="text-center text-destructive py-10 bg-destructive/10 rounded-lg">
        {{ error }}
      </div>

      <div v-else class="grid gap-6 md:grid-cols-2">
        <!-- Mac Version -->
        <div class="rounded-xl border bg-card text-card-foreground shadow">
          <div class="flex flex-col space-y-1.5 p-6">
            <h3 class="font-semibold leading-none tracking-tight flex items-center gap-2">
              <AppleIcon class="h-6 w-6" />
              {{ t('download.macOS') }}
            </h3>
            <p class="text-sm text-muted-foreground">{{ t('download.macOSReq') }}</p>
          </div>
          <div class="p-6 pt-0 space-y-4">
            <div v-if="getArtifact('darwin-aarch64') && getArtifact('darwin-aarch64').installer_url" class="space-y-2">
              <Button class="w-full" @click="download(getArtifact('darwin-aarch64').installer_url)">
                <DownloadIcon class="mr-2 h-4 w-4" />
                {{ t('download.macOSArm') }}
              </Button>
              <p class="text-xs text-muted-foreground text-center">
                {{ t('download.macOSArmDesc') }}
              </p>
            </div>
            <div v-if="getArtifact('darwin-x86_64') && getArtifact('darwin-x86_64').installer_url" class="pt-2">
              <Button variant="outline" class="w-full" @click="download(getArtifact('darwin-x86_64').installer_url)">
                <DownloadIcon class="mr-2 h-4 w-4" />
                {{ t('download.macOSIntel') }}
              </Button>
            </div>
            <div v-if="(!getArtifact('darwin-aarch64') || !getArtifact('darwin-aarch64').installer_url) && (!getArtifact('darwin-x86_64') || !getArtifact('darwin-x86_64').installer_url)" class="text-center text-muted-foreground py-4">
              {{ t('download.comingSoon') }}
            </div>
          </div>
        </div>

        <!-- Windows Version -->
        <div class="rounded-xl border bg-card text-card-foreground shadow">
          <div class="flex flex-col space-y-1.5 p-6">
            <h3 class="font-semibold leading-none tracking-tight flex items-center gap-2">
              <MonitorIcon class="h-6 w-6" />
              {{ t('download.windows') }}
            </h3>
            <p class="text-sm text-muted-foreground">{{ t('download.windowsReq') }}</p>
          </div>
          <div class="p-6 pt-0">
            <div v-if="getArtifact('windows-x86_64') && getArtifact('windows-x86_64').installer_url" class="space-y-2">
              <Button class="w-full" @click="download(getArtifact('windows-x86_64').installer_url)">
                <DownloadIcon class="mr-2 h-4 w-4" />
                {{ t('download.windowsDownload') }}
              </Button>
            </div>
            <div v-else class="text-center text-muted-foreground py-4">
              {{ t('download.comingSoon') }}
            </div>
          </div>
        </div>
      </div>

      <div v-if="version" class="mt-10 p-6 bg-muted/30 rounded-lg border">
        <div class="flex justify-between items-center mb-4">
          <h2 class="text-xl font-semibold">{{ t('download.releaseNotes') }} - {{ version.version }}</h2>
          <span class="text-sm text-muted-foreground">
            {{ t('download.releasedOn') }} {{ formatDate(version.pub_date) }}
          </span>
        </div>
        <div class="prose dark:prose-invert max-w-none">
          <MarkdownRenderer :content="version.release_notes || t('download.noNotes')" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { systemAPI } from '@/api/system'
import { Button } from '@/components/ui/button'
import LoadingBubble from '@/components/chat/LoadingBubble.vue'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import { Apple as AppleIcon, Monitor as MonitorIcon, Download as DownloadIcon } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n'

const { t } = useLanguage()
const version = ref(null)
const loading = ref(true)
const error = ref(null)

const getArtifact = (platform) => {
  if (!version.value || !version.value.artifacts) return null
  return version.value.artifacts.find(a => a.platform === platform)
}

const download = (url) => {
  if (url) {
    window.open(url, '_blank')
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleDateString()
}

onMounted(async () => {
  try {
    const res = await systemAPI.getLatestVersion()
    version.value = res
  } catch (err) {
    console.error(err)
    // If 404, it might mean no version published yet
    if (err.response && err.response.status === 404) {
       error.value = t('download.noVersions')
    } else {
       error.value = t('download.loadErrorRetry')
    }
  } finally {
    loading.value = false
  }
})
</script>
