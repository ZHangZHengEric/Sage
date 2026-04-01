<template>
  <ResizablePanel
    :title="t('workspace.title')"
    :badge="workspaceFiles?.length || 0"
    size="large"
    @close="$emit('close')"
  >
    <template #icon>
      <FolderOpen class="w-4 h-4 text-muted-foreground" />
    </template>

    <div class="h-full overflow-y-auto p-4 space-y-4">
      <div class="space-y-1">
        <div v-if="isLoading" class="flex flex-col items-center justify-center py-8 text-muted-foreground">
          <FolderOpen class="w-12 h-12 mb-2 opacity-50 animate-pulse" />
          <p class="text-sm">{{ t('workspace.loading') }}</p>
        </div>
        <div v-else-if="hasValidFiles" class="flex flex-col gap-1">
          <WorkspaceFileTree
            v-for="node in fileTree"
            :key="node.path"
            :item="node"
            @download="handleDownload"
            @view="handleView"
          />
        </div>
        <div v-else class="flex flex-col items-center justify-center py-8 text-muted-foreground">
          <FolderOpen class="w-12 h-12 mb-2 opacity-50" />
          <p class="text-sm">{{ t('workspace.noFiles') }}</p>
        </div>
      </div>
    </div>
  </ResizablePanel>

  <Dialog v-model:open="previewOpen">
    <DialogContent class="max-w-[90vw] h-[85vh] p-0 overflow-hidden">
      <FileRenderer
        v-if="previewItem"
        :file-path="previewItem.path"
        :file-name="previewItem.name"
        :item="previewRendererItem"
        :dialog-mode="true"
      />
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import { FolderOpen } from 'lucide-vue-next'
import ResizablePanel from './ResizablePanel.vue'
import WorkspaceFileTree from './WorkspaceFileTree.vue'
import FileRenderer from './workbench/renderers/FileRenderer.vue'
import { Dialog, DialogContent } from '@/components/ui/dialog'

const props = defineProps({
  workspaceFiles: {
    type: Array,
    default: () => []
  },
  isLoading: {
    type: Boolean,
    default: false
  },
  agentId: {
    type: String,
    default: ''
  },
  sessionId: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['close', 'downloadFile'])

const { t } = useLanguage()
const previewOpen = ref(false)
const previewItem = ref(null)

const hasValidFiles = computed(() => {
  return props.workspaceFiles && props.workspaceFiles.length > 0
})

const fileTree = computed(() => {
  if (!props.workspaceFiles || props.workspaceFiles.length === 0) return []

  const root = []
  const map = {}

  props.workspaceFiles.forEach(file => {
    map[file.path] = { ...file, children: [] }
  })

  props.workspaceFiles.forEach(file => {
    const node = map[file.path]
    const parts = file.path.split('/')
    if (parts.length > 1) {
      const parentPath = parts.slice(0, -1).join('/')
      if (map[parentPath]) {
        map[parentPath].children.push(node)
      } else {
        root.push(node)
      }
    } else {
      root.push(node)
    }
  })

  const sortNodes = (nodes) => {
    nodes.sort((a, b) => {
      if (a.is_directory !== b.is_directory) {
        return a.is_directory ? -1 : 1
      }
      return a.name.localeCompare(b.name)
    })
    nodes.forEach(node => {
      if (node.children.length > 0) sortNodes(node.children)
    })
  }

  sortNodes(root)
  return root
})

const handleDownload = (item) => {
  emit('downloadFile', item)
}

const previewRendererItem = computed(() => {
  if (!previewItem.value) return null
  return {
    ...previewItem.value,
    agentId: props.agentId,
    sessionId: props.sessionId,
    role: 'assistant',
    timestamp: Date.now()
  }
})

const handleView = (item) => {
  if (!item || item.is_directory) return
  previewItem.value = item
  previewOpen.value = true
}
</script>
