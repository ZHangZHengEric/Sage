<template>
  <div class="h-full w-full bg-background p-4 md:p-6 overflow-hidden flex flex-col">
    <div v-if="loading" class="flex-1 flex items-center justify-center">
      <Loader class="h-8 w-8 animate-spin text-primary" />
    </div>
    <div v-else-if="error" class="flex-1 flex flex-col items-center justify-center text-center">
       <p class="text-destructive mb-4">{{ error }}</p>
       <Button @click="goBack">{{ t('tools.backToList') }}</Button>
    </div>
    <ToolDetail v-else-if="tool" :tool="tool" @back="goBack" @edit="openAnyToolEditor" class="flex-1 overflow-hidden" />
  </div>

  <Dialog v-model:open="isAnyToolEditorOpen">
    <DialogContent class="sm:max-w-[980px] max-h-[90vh] overflow-hidden flex flex-col p-0 gap-0">
      <DialogHeader class="px-6 py-4 border-b">
        <DialogTitle>
          {{ anyToolEditorMode === 'edit' ? (t('tools.editTool') || 'Edit Tool') : (t('tools.addTool') || 'Add Tool') }}
        </DialogTitle>
        <DialogDescription class="hidden">
          {{ anyToolEditorMode === 'edit' ? 'Edit an AnyTool definition' : 'Create an AnyTool definition' }}
        </DialogDescription>
      </DialogHeader>
      <div class="flex-1 overflow-y-auto">
        <AnyToolToolEditor
          :tool="editingAnyToolTool"
          :mode="anyToolEditorMode"
          :loading="isSavingAnyToolTool"
          @submit="handleAnyToolToolSubmit"
          @cancel="isAnyToolEditorOpen = false"
        />
      </div>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toolAPI } from '../api/tool.js'
import ToolDetail from '../components/ToolDetail.vue'
import AnyToolToolEditor from '../components/AnyToolToolEditor.vue'
import { Loader } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useLanguage } from '../utils/i18n.js'

const route = useRoute()
const router = useRouter()
const { t } = useLanguage()
const tool = ref(null)
const loading = ref(true)
const error = ref('')
const isAnyToolEditorOpen = ref(false)
const anyToolEditorMode = ref('create')
const editingAnyToolTool = ref(null)
const isSavingAnyToolTool = ref(false)

const loadTool = async () => {
  try {
    loading.value = true
    const toolName = route.params.toolName
    // Since we don't have a getTool API, we fetch all and find
    const response = await toolAPI.getTools()
    if (response && response.tools) {
      const found = response.tools.find(t => t.name === toolName)
      if (found) {
        tool.value = found
      } else {
        error.value = 'Tool not found'
      }
    } else {
      error.value = 'Failed to load tools'
    }
  } catch (err) {
    console.error(err)
    error.value = err.message || 'Error loading tool'
  } finally {
    loading.value = false
  }
}

const goBack = () => {
  router.push({ name: 'Tools' })
}

const openAnyToolEditor = async () => {
  anyToolEditorMode.value = 'edit'
  const baseTool = tool.value ? { ...tool.value } : null
  try {
    const response = await toolAPI.getMcpServers()
    const server = response?.servers?.find((item) => item.name === 'AnyTool')
    const fullTool = server?.tools?.find((item) => item.name === baseTool?.name)
    editingAnyToolTool.value = fullTool ? { ...fullTool } : baseTool
  } catch (error) {
    console.error(error)
    editingAnyToolTool.value = baseTool
  }
  isAnyToolEditorOpen.value = true
}

const handleAnyToolToolSubmit = async ({ tool_definition, original_name }) => {
  try {
    isSavingAnyToolTool.value = true
    const response = await toolAPI.upsertAnyToolTool({
      tool_definition,
      original_name,
      server_name: 'AnyTool',
    })
    isAnyToolEditorOpen.value = false
    if (response?.tool_name) {
      await router.replace({ name: 'ToolDetailView', params: { toolName: response.tool_name } })
    }
    await loadTool()
  } catch (err) {
    console.error(err)
    error.value = err.message || 'Error saving tool'
  } finally {
    isSavingAnyToolTool.value = false
  }
}

onMounted(() => {
  loadTool()
})

watch(
  () => route.params.toolName,
  () => {
    loadTool()
  }
)
</script>
