<template>
  <div class="artifacts-card w-full max-w-md">
    <div class="rounded-lg border border-border/70 bg-white/85 shadow-sm backdrop-blur-xl transition-colors dark:bg-card/80">
      <div class="flex items-center gap-3 border-b border-border/70 p-3">
        <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
          <PackageOpen class="h-4 w-4" />
        </div>
        <div class="min-w-0 flex-1">
          <div class="truncate text-sm font-medium text-foreground">
            {{ artifacts.title || 'Artifacts' }}
          </div>
        </div>
        <Badge variant="outline" class="text-[10px]">
          {{ artifacts.items.length }}
        </Badge>
      </div>

      <div class="space-y-2 p-3">
        <button
          v-for="item in artifacts.items"
          :key="item.id || item.path"
          type="button"
          class="group flex w-full cursor-pointer items-center gap-3 rounded-md border border-border/70 bg-background/70 p-3 text-left transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          @click="openArtifact(item)"
        >
          <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <component :is="iconForItem(item)" class="h-4 w-4" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-sm font-medium leading-5 text-foreground">
              {{ item.title }}
            </div>
            <div class="truncate text-xs leading-5 text-muted-foreground">
              {{ item.path }}
            </div>
          </div>
          <Badge v-if="item.status" variant="outline" class="shrink-0 text-[10px]">
            {{ item.status }}
          </Badge>
          <ExternalLink class="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import {
  ExternalLink,
  File,
  FileArchive,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileVideo,
  PackageOpen,
  Presentation,
} from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { useWorkbenchStore } from '@/stores/workbench.js'
import { usePanelStore } from '@/stores/panel.js'
import { resolveAgentWorkspacePath } from '@/utils/agentWorkspacePath'

const props = defineProps({
  artifacts: {
    type: Object,
    required: true,
  },
  messageId: {
    type: String,
    default: '',
  },
  agentId: {
    type: String,
    default: '',
  },
})

const workbenchStore = useWorkbenchStore()
const panelStore = usePanelStore()

function iconForItem(item) {
  switch (item.type) {
    case 'markdown':
    case 'text':
    case 'pdf':
      return FileText
    case 'image':
      return FileImage
    case 'video':
      return FileVideo
    case 'spreadsheet':
      return FileSpreadsheet
    case 'presentation':
      return Presentation
    case 'archive':
      return FileArchive
    default:
      return File
  }
}

async function openArtifact(item) {
  const resolvedPath = await resolveAgentWorkspacePath(item.path, props.agentId)
  const normalizedPath = normalizePath(resolvedPath || item.path)
  const stableKey = props.messageId
    ? `file:${props.messageId}:${normalizedPath}`
    : `file:${normalizedPath}`

  panelStore.openWorkbench()
  workbenchStore.setRealtime(false)

  const targetByMessage = (workbenchStore.items || []).find((entry) => entry?.stableKey === stableKey)
  if (jumpToWorkbenchItem(targetByMessage)) return

  const targetByPath = [...(workbenchStore.items || [])].reverse().find((entry) => (
    (entry?.type === 'file' || entry?.type === 'image') &&
    normalizePath(workbenchPathForItem(entry)) === normalizedPath
  ))
  if (jumpToWorkbenchItem(targetByPath)) return

  const createdItem = workbenchStore.addItem({
    type: item.type === 'image' ? 'image' : 'file',
    role: 'assistant',
    timestamp: Date.now(),
    messageId: props.messageId || null,
    stableKey,
    data: {
      filePath: normalizedPath,
      path: normalizedPath,
      fileName: item.title || fileNameFromPath(normalizedPath),
      src: item.type === 'image' ? normalizedPath : undefined,
    },
  })
  jumpToWorkbenchItem(createdItem)
}

function jumpToWorkbenchItem(item) {
  if (!item) return false
  if (item.sessionId) {
    workbenchStore.setSessionId(item.sessionId, { autoJumpToLast: false })
  }
  const index = (workbenchStore.filteredItems || []).findIndex((entry) => entry?.id === item.id)
  if (index !== -1) {
    workbenchStore.setCurrentIndex(index)
    return true
  }
  return false
}

function workbenchPathForItem(item) {
  const data = item?.data || {}
  if (item?.type === 'image') return data.src || data.filePath || data.path || ''
  return data.filePath || data.path || data.src || ''
}

function normalizePath(path) {
  if (!path) return ''
  let normalized = String(path)
  try {
    normalized = decodeURIComponent(normalized).trim()
  } catch {
    normalized = String(path).trim()
  }
  if (normalized.startsWith('`') && normalized.endsWith('`')) {
    normalized = normalized.slice(1, -1)
  }
  if (normalized.startsWith('/sage-workspace/')) {
    normalized = normalized.replace('/sage-workspace/', '/')
  }
  if (normalized.startsWith('file://')) {
    normalized = normalized.replace(/^file:\/\/\/?/i, '/')
  }
  return normalized
}

function fileNameFromPath(path) {
  return String(path || '').split('/').filter(Boolean).pop() || 'file'
}
</script>
