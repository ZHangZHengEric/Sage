<template>
  <form @submit="handleSubmit" class="w-full max-w-[800px] mx-auto">
    <div v-if="uploadedFiles.length > 0" class="mb-3">
      <div class="flex flex-wrap gap-2 p-3 bg-muted/50 rounded-xl border border-border">
        <div v-for="(file, index) in uploadedFiles" :key="index" class="relative w-20 h-20 rounded-lg overflow-hidden bg-background border border-border group">
          <img v-if="file.type === 'image'" :src="file.preview" :alt="`预览图 ${index + 1}`" class="w-full h-full object-cover" />
          <video v-else-if="file.type === 'video'" :src="file.preview || file.url" class="w-full h-full object-cover" muted playsinline></video>
          <div v-else class="flex flex-col items-center justify-center w-full h-full p-2 text-muted-foreground" :title="file.name">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mb-1">
              <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
              <polyline points="13 2 13 9 20 9"></polyline>
            </svg>
            <span class="text-[10px] truncate w-full text-center">{{ file.name }}</span>
          </div>

          <button
            type="button"
            @click="removeFile(index)"
            class="absolute top-1 right-1 w-5 h-5 flex items-center justify-center rounded-full bg-background/90 text-destructive hover:bg-destructive hover:text-destructive-foreground transition-colors shadow-sm opacity-0 group-hover:opacity-100"
            :title="t('messageInput.removeFile')"
          >
            <span class="text-xs">✕</span>
          </button>
        </div>
      </div>
    </div>

    <div
      class="relative flex flex-col gap-2 p-3 bg-muted/30 border border-input rounded-2xl focus-within:ring-2 focus-within:ring-ring focus-within:border-primary transition-all shadow-sm message-input-drop-zone"
      :class="{ 'bg-primary/5 border-primary/50': isDraggingOver }"
      @dragenter="handleDragEnter"
      @dragover="handleDragOver"
      @dragleave="handleDragLeave"
      @drop="handleDrop"
    >
      <div v-if="showSkillList && (filteredSkills.length > 0 || loadingSkills)" class="absolute bottom-full left-0 w-full mb-2 bg-popover border border-border rounded-lg shadow-lg max-h-60 overflow-y-auto z-50 bg-background">
        <div v-if="loadingSkills" class="p-3 text-center text-sm text-muted-foreground">
          加载中...
        </div>
        <div v-else-if="filteredSkills.length === 0" class="p-3 text-center text-sm text-muted-foreground">
          未找到相关技能
        </div>
        <div v-else>
          <div
            v-for="(skill, index) in filteredSkills"
            :key="skill.name"
            class="px-4 py-2 cursor-pointer hover:bg-accent hover:text-accent-foreground flex items-center justify-between transition-colors text-sm"
            :class="{ 'bg-accent text-accent-foreground': index === selectedSkillIndex }"
            @click="selectSkill(skill)"
          >
            <div class="flex flex-col overflow-hidden">
              <span class="font-medium truncate">{{ skill.name }}</span>
              <span v-if="skill.description" class="text-xs text-muted-foreground truncate">{{ skill.description }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="flex items-start gap-2">
        <div v-if="currentSkill" class="flex items-center gap-1 h-7 px-2.5 bg-primary/10 text-primary rounded-full text-xs font-medium whitespace-nowrap border border-primary/20 flex-shrink-0 mt-1">
          <span class="max-w-[100px] truncate">@{{ currentSkill }}</span>
          <button
            type="button"
            @click="currentSkill = null"
            class="ml-0.5 w-3.5 h-3.5 flex items-center justify-center rounded-full hover:bg-primary/20"
          >
            <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <ChipInput
          ref="editorRef"
          v-model="inputValue"
          :placeholder="isLoading ? (t('messageInput.placeholderGenerating') || 'AI正在生成回复，可直接输入新消息...') : t('messageInput.placeholder')"
          wrapper-class="flex-1"
          @keydown="handleKeyDown"
          @compositionstart="handleCompositionStart"
          @compositionend="handleCompositionEnd"
          @paste="handlePaste"
        />
      </div>

      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex min-w-0 flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            class="h-7 w-7 rounded-full text-muted-foreground hover:text-foreground hover:bg-background flex-shrink-0"
            @click="triggerFileInput"
            :disabled="isLoading"
            :title="t('messageInput.uploadFile')"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            class="h-8 rounded-full px-3 text-xs font-medium transition-all duration-200 border"
            :class="planEnabled ? activeToggleClass : inactiveToggleClass"
            @click="planEnabled = !planEnabled"
            :disabled="isLoading"
            :title="t('messageInput.planMode')"
          >
            {{ t('messageInput.planModeLabel') || 'Plan' }}
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            class="h-8 rounded-full px-3 text-xs font-medium transition-all duration-200 border"
            :class="deepThinkingEnabled ? activeToggleClass : inactiveToggleClass"
            @click="toggleDeepThinking"
            :disabled="isLoading"
            :title="t('config.deepThinking')"
          >
            {{ t('config.deepThinking') }}
          </Button>
        </div>

        <div class="ml-auto flex items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            class="h-7 w-7 rounded-full text-muted-foreground hover:text-foreground hover:bg-background flex-shrink-0"
            :disabled="props.isLoading || (!isOptimizingInput && !inputValue.trim())"
            :title="isOptimizingInput ? (t('messageInput.cancelOptimizeTitle') || '取消优化') : (t('messageInput.optimizeTitle') || '优化输入')"
            @click="handleOptimizeInput"
          >
            <Loader2 v-if="isOptimizingInput" class="h-4 w-4 animate-spin" />
            <Sparkles v-else class="h-4 w-4" />
          </Button>

          <Button
            type="submit"
            size="icon"
            :disabled="isOptimizingInput || (!isLoading && !inputValue.trim() && uploadedFiles.length === 0)"
            class="h-7 w-7 rounded-full transition-all duration-200"
            :class="[
              !isLoading && !inputValue.trim() && uploadedFiles.length === 0 ? 'opacity-50 cursor-not-allowed' : '',
              isLoading ? 'bg-destructive hover:bg-destructive/90 text-destructive-foreground' : ''
            ]"
            :title="isLoading ? (inputValue.trim() || uploadedFiles.length > 0 ? t('messageInput.stopAndSendTitle') || '停止生成并发送' : t('messageInput.stopTitle') || '停止生成') : t('messageInput.sendTitle')"
          >
            <svg v-if="!isLoading" width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M22 2L11 13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M22 2L15 22L11 13L2 9L22 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect x="4" y="4" width="16" height="16" rx="4" fill="currentColor"/>
            </svg>
          </Button>
        </div>
      </div>

      <input ref="fileInputRef" type="file" multiple @change="handleFileSelect" style="display: none;" />
    </div>
  </form>
</template>

<script setup>
import { ref, watch, nextTick, computed, onUnmounted } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import { ossApi } from '../../api/oss.js'
import { skillAPI } from '../../api/skill.js'
import { chatAPI } from '../../api/chat.js'
import { Button } from '@/components/ui/button'
import { Loader2, Sparkles } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import ChipInput from './ChipInput.vue'
import {
  removeAttachmentPlaceholder,
  textHasAttachmentPlaceholder,
  buildOrderedMultimodalContent
} from '../../utils/multimodalContent.js'

const props = defineProps({
  isLoading: {
    type: Boolean,
    default: false
  },
  presetText: {
    type: String,
    default: ''
  },
  sessionId: {
    type: String,
    default: ''
  },
  agentId: {
    type: String,
    default: null
  },
  deliveryContextMessages: {
    type: Array,
    default: () => []
  },
  selectedAgent: {
    type: Object,
    default: null
  },
  config: {
    type: Object,
    default: () => ({})
  }
})

const emit = defineEmits(['sendMessage', 'stopGeneration', 'configChange'])

const { t } = useLanguage()

const inputValue = ref('')
const editorRef = ref(null)
const fileInputRef = ref(null)
let nextAttachmentLocalId = 0
const allocateAttachmentId = () => {
  nextAttachmentLocalId += 1
  return `${Date.now().toString(36)}-${nextAttachmentLocalId}`
}

const showSkillList = ref(false)
const loadingSkills = ref(false)
const skills = ref([])
const selectedSkillIndex = ref(0)
const skillKeyword = ref('')
const currentSkill = ref(null)
const uploadedFiles = ref([])
const isComposing = ref(false)
const isDraggingOver = ref(false)
const planEnabled = ref(false)
const isOptimizingInput = ref(false)
const optimizeAbortController = ref(null)
const deepThinkingEnabled = computed(() => props.config?.deepThinking !== false)
const activeToggleClass = 'border-primary/30 bg-primary/10 text-foreground hover:bg-primary/15 hover:border-primary/40'
const inactiveToggleClass = 'border-border bg-background text-muted-foreground hover:text-foreground hover:bg-muted/60'

watch(() => props.presetText, async (newVal) => {
  if (typeof newVal !== 'string' || !newVal) return
  if (newVal === inputValue.value) return
  inputValue.value = newVal
  await nextTick()
  editorRef.value?.focus(true)
})

watch(() => props.agentId, () => {
  skills.value = []
  currentSkill.value = null
})

const toggleDeepThinking = () => {
  emit('configChange', { deepThinking: !deepThinkingEnabled.value })
}

const applyPlanTag = (messageContent) => {
  if (!planEnabled.value) return messageContent
  return `<enable_plan>true</enable_plan>${messageContent ? ` ${messageContent}` : ''}`
}

const filteredSkills = computed(() => {
  const agentAvailableSkills = props.selectedAgent?.availableSkills || []
  let filtered = skills.value

  if (agentAvailableSkills.length > 0) {
    filtered = skills.value.filter(skill => agentAvailableSkills.includes(skill.name))
  }

  if (!skillKeyword.value) return filtered
  const lowerKeyword = skillKeyword.value.toLowerCase()
  return filtered.filter(skill => (skill.name || '').toLowerCase().startsWith(lowerKeyword))
})

const selectSkill = (skill) => {
  currentSkill.value = skill.name
  inputValue.value = ''
  showSkillList.value = false
  nextTick(() => {
    editorRef.value?.focus(true)
  })
}

const getFileFromEntry = (fileEntry) => {
  return new Promise((resolve) => {
    fileEntry.file((file) => {
      resolve(file)
    }, () => {
      resolve(null)
    })
  })
}

const handleDragEnter = (e) => {
  e.preventDefault()
  e.stopPropagation()
  if (e.dataTransfer && e.dataTransfer.types) {
    const types = Array.from(e.dataTransfer.types)
    if (types.includes('Files') || types.includes('application/x-moz-file')) {
      isDraggingOver.value = true
    }
  }
}

const handleDragOver = (e) => {
  e.preventDefault()
  e.stopPropagation()
  if (e.dataTransfer) {
    e.dataTransfer.dropEffect = 'copy'
  }
}

const handleDragLeave = (e) => {
  e.preventDefault()
  e.stopPropagation()
  isDraggingOver.value = false
}

const handleDrop = async (e) => {
  e.preventDefault()
  e.stopPropagation()
  isDraggingOver.value = false

  const files = []
  const items = e.dataTransfer?.items

  if (items && items.length > 0) {
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      const entry = item.webkitGetAsEntry?.() || item.getAsEntry?.()

      if (entry && entry.isFile) {
        const file = await getFileFromEntry(entry)
        if (file) files.push(file)
      } else if (!entry) {
        const file = item.getAsFile()
        if (file) files.push(file)
      }
    }
  }

  if (files.length === 0) {
    const dtFiles = e.dataTransfer?.files
    if (dtFiles && dtFiles.length > 0) {
      for (let i = 0; i < dtFiles.length; i++) {
        files.push(dtFiles[i])
      }
    }
  }

  for (const file of files) {
    await processFile(file)
  }
}

const LEADING_CONTROL_TAG_RE = /^\s*(?:<enable_plan>\s*(?:true|false)\s*<\/enable_plan>\s*|<enable_deep_thinking>\s*(?:true|false)\s*<\/enable_deep_thinking>\s*)+/i
const LEADING_SKILL_TAG_RE = /^<skill>(.*?)<\/skill>\s*/i

watch(inputValue, async (newVal) => {
  if (isComposing.value) return

  const normalizedInput = newVal.replace(LEADING_CONTROL_TAG_RE, '')
  const skillMatch = normalizedInput.match(LEADING_SKILL_TAG_RE)
  if (skillMatch) {
    currentSkill.value = skillMatch[1]
    inputValue.value = normalizedInput.replace(skillMatch[0], '')
    return
  }

  if (newVal.startsWith('/')) {
    skillKeyword.value = newVal.slice(1)

    if (skills.value.length === 0 && !loadingSkills.value) {
      try {
        loadingSkills.value = true
        const res = await skillAPI.getSkills({ agent_id: props.agentId })
        if (res.skills) {
          skills.value = res.skills
        }
      } catch (error) {
        console.error('获取技能列表失败:', error)
        skills.value = []
      } finally {
        loadingSkills.value = false
      }
    }

    showSkillList.value = true
    selectedSkillIndex.value = 0
  } else {
    showSkillList.value = false
  }
})

const buildHeadPrefix = () => {
  let prefix = ''
  if (currentSkill.value) {
    prefix = `<skill>${currentSkill.value}</skill> `
  }
  if (planEnabled.value) {
    prefix = `<enable_plan>true</enable_plan>` + (prefix ? ` ${prefix}` : '')
  }
  return prefix
}

const buildSubmissionPayload = () => {
  const isMultimodalEnabled = props.selectedAgent?.enableMultimodal === true
  const headPrefix = buildHeadPrefix()
  const readyFiles = uploadedFiles.value.filter(f => f.url)

  const { contentArray, plainText } = buildOrderedMultimodalContent(
    inputValue.value,
    readyFiles,
    { multimodalEnabled: isMultimodalEnabled, headPrefix }
  )

  const hasImagePart = contentArray.some(it => it.type === 'image_url')
  const useMultimodal = isMultimodalEnabled && hasImagePart
  return {
    plainText,
    multimodalContent: useMultimodal ? contentArray : null
  }
}

const hasSubmittableInput = () => {
  return Boolean(
    inputValue.value.trim() ||
    uploadedFiles.value.length > 0 ||
    currentSkill.value
  )
}

const dispatchSubmit = (needInterrupt) => {
  const { plainText, multimodalContent } = buildSubmissionPayload()
  if (!plainText && (!multimodalContent || multimodalContent.length === 0)) return

  inputValue.value = ''
  uploadedFiles.value = []
  currentSkill.value = null

  emit('sendMessage', plainText, {
    multimodalContent,
    needInterrupt
  })
}

const handleSubmit = (e) => {
  e.preventDefault()
  cancelOptimizeInput()
  if (props.isLoading) {
    if (hasSubmittableInput()) {
      dispatchSubmit(true)
    } else {
      emit('stopGeneration')
    }
    return
  }

  if (hasSubmittableInput()) {
    dispatchSubmit(false)
  }
}

const handleKeyDown = (e) => {
  const composing = isComposing.value || e.isComposing || e.keyCode === 229 || e.key === 'Process'

  if (showSkillList.value && filteredSkills.value.length > 0) {
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      selectedSkillIndex.value = (selectedSkillIndex.value - 1 + filteredSkills.value.length) % filteredSkills.value.length
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      selectedSkillIndex.value = (selectedSkillIndex.value + 1) % filteredSkills.value.length
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      selectSkill(filteredSkills.value[selectedSkillIndex.value])
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      showSkillList.value = false
      return
    }
  }

  if (!composing && e.key === 'Backspace' && inputValue.value === '' && currentSkill.value) {
    e.preventDefault()
    currentSkill.value = null
    return
  }

  if (e.key === 'Enter' && !e.shiftKey && !composing) {
    e.preventDefault()
    handleSubmit(e)
  }
}

const handleCompositionStart = () => {
  isComposing.value = true
}

const handleCompositionEnd = () => {
  isComposing.value = false
}

const handlePaste = async (e) => {
  const clipboardData = e.clipboardData || e.originalEvent?.clipboardData
  if (!clipboardData) return

  const items = clipboardData.items
  if (!items || items.length === 0) return

  let hasFiles = false

  for (let i = 0; i < items.length; i++) {
    const item = items[i]

    if (item.type.startsWith('image/')) {
      e.preventDefault()
      hasFiles = true
      const blob = item.getAsFile()
      if (blob) {
        const ext = item.type.split('/')[1] || 'png'
        const filename = `pasted_image_${Date.now()}.${ext}`
        const file = new File([blob], filename, { type: item.type })
        await processFile(file)
      }
    } else if (item.kind === 'file') {
      e.preventDefault()
      hasFiles = true
      const file = item.getAsFile()
      if (file) {
        await processFile(file)
      }
    }
  }

  if (!hasFiles) {
    return
  }
}

const cancelOptimizeInput = () => {
  if (!optimizeAbortController.value) return
  optimizeAbortController.value.abort()
  optimizeAbortController.value = null
}

const readOptimizeInputStream = async (response, handlers = {}) => {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      const trimmedLine = line.trim()
      if (!trimmedLine) continue
      const payload = JSON.parse(trimmedLine)
      if (payload.type === 'delta' && handlers.onDelta) {
        handlers.onDelta(payload)
      } else if (payload.type === 'done' && handlers.onDone) {
        handlers.onDone(payload)
      } else if (payload.type === 'error' && handlers.onError) {
        handlers.onError(payload)
      }
    }
  }
}

const handleOptimizeInput = async () => {
  if (isOptimizingInput.value) {
    cancelOptimizeInput()
    isOptimizingInput.value = false
    return
  }

  const currentInput = inputValue.value.trim()
  if (!currentInput || props.isLoading) return

  const controller = new AbortController()
  optimizeAbortController.value = controller
  isOptimizingInput.value = true

  try {
    let streamedInput = ''
    const response = await chatAPI.optimizeUserInputStream({
      current_input: currentInput,
      history_messages: props.deliveryContextMessages || [],
      session_id: props.sessionId || null,
      agent_id: props.agentId || null
    }, {
      signal: controller.signal
    })

    await readOptimizeInputStream(response, {
      onDelta: ({ content }) => {
        streamedInput += content || ''
        inputValue.value = streamedInput
      },
      onDone: async ({ optimized_input: optimizedInput }) => {
        const nextInput = (optimizedInput || streamedInput || currentInput).trim()
        if (!nextInput) return
        inputValue.value = nextInput
        await nextTick()
        editorRef.value?.focus(true)
      }
    })
  } catch (error) {
    if (controller.signal.aborted || error?.name === 'AbortError') {
      return
    }
    console.error('优化用户输入失败:', error)
    toast.error(t('messageInput.optimizeError') || '优化输入失败，请重试')
  } finally {
    if (optimizeAbortController.value === controller) {
      optimizeAbortController.value = null
    }
    isOptimizingInput.value = false
  }
}

const triggerFileInput = () => {
  if (fileInputRef.value) {
    fileInputRef.value.click()
  }
}

const handleFileSelect = async (event) => {
  const files = Array.from(event.target.files)
  if (files.length === 0) return

  for (const file of files) {
    await processFile(file)
  }
  event.target.value = ''
}

const insertChipForFile = async (fileItem) => {
  if (!fileItem) return
  await nextTick()
  if (editorRef.value?.insertPlaceholder) {
    editorRef.value.insertPlaceholder(fileItem)
  }
}

const processFile = async (file) => {
  const imageExtensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg']
  const videoExtensions = ['.mp4', '.webm', '.ogg', '.mov', '.avi']
  const fileName = file.name.toLowerCase()
  const fileExtension = fileName.substring(fileName.lastIndexOf('.'))

  const isImage = file.type.startsWith('image/') || imageExtensions.includes(fileExtension)
  const isVideo = file.type.startsWith('video/') || videoExtensions.includes(fileExtension)

  let preview = null
  if (isImage || isVideo) {
    preview = URL.createObjectURL(file)
  }

  const fileItem = {
    id: allocateAttachmentId(),
    file,
    preview,
    type: isImage ? 'image' : (isVideo ? 'video' : 'file'),
    name: file.name,
    uploading: true,
    url: null
  }

  uploadedFiles.value.push(fileItem)
  await insertChipForFile(fileItem)

  try {
    const response = await ossApi.uploadFile(file)
    fileItem.url = response.data?.url || response.url || response
    fileItem.uploading = false
  } catch (error) {
    const index = uploadedFiles.value.indexOf(fileItem)
    if (index > -1) {
      uploadedFiles.value.splice(index, 1)
      if (preview) {
        URL.revokeObjectURL(preview)
      }
    }
    inputValue.value = removeAttachmentPlaceholder(inputValue.value, fileItem.id)
    alert('文件上传失败，请重试')
  }
}

const removeFile = (index) => {
  const file = uploadedFiles.value[index]
  if (!file) return
  if (file.preview) {
    URL.revokeObjectURL(file.preview)
  }
  if (file.id != null) {
    inputValue.value = removeAttachmentPlaceholder(inputValue.value, file.id)
  }
  uploadedFiles.value.splice(index, 1)
}

// 当用户在 textarea 中手动删除某个占位符时，同步移除对应的附件项。
watch(inputValue, (text) => {
  if (uploadedFiles.value.length === 0) return
  const stale = []
  for (const f of uploadedFiles.value) {
    if (f.id == null) continue
    if (f.uploading) continue
    if (!textHasAttachmentPlaceholder(text || '', f.id)) {
      stale.push(f)
    }
  }
  if (stale.length === 0) return
  for (const f of stale) {
    if (f.preview) URL.revokeObjectURL(f.preview)
    const idx = uploadedFiles.value.indexOf(f)
    if (idx > -1) uploadedFiles.value.splice(idx, 1)
  }
})

const getInputValue = () => inputValue.value

const setInputValue = (value) => {
  inputValue.value = value
}

const appendInputValue = (text) => {
  if (inputValue.value) {
    inputValue.value += ` ${text}`
  } else {
    inputValue.value = text
  }
}

defineExpose({
  getInputValue,
  setInputValue,
  appendInputValue
})

onUnmounted(() => {
  cancelOptimizeInput()
})
</script>
