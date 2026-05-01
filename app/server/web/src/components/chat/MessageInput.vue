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

          <div
            v-if="file.uploading"
            class="absolute inset-0 z-10 flex items-center justify-center bg-background/60 backdrop-blur-[1px]"
            aria-hidden="true"
            role="status"
            :aria-label="t('messageInput.uploadingAttachment')"
          >
            <Loader2 class="h-6 w-6 animate-spin text-primary" />
          </div>

          <button
            v-if="!file.uploading"
            type="button"
            @click="removeFile(index)"
            class="absolute top-1 right-1 z-20 w-5 h-5 flex items-center justify-center rounded-full bg-background/90 text-destructive hover:bg-destructive hover:text-destructive-foreground transition-colors shadow-sm opacity-0 group-hover:opacity-100"
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
            @mousedown.prevent
            @click="selectSkill(skill)"
          >
            <div class="flex flex-col overflow-hidden">
              <span class="font-medium truncate">{{ skill.name }}</span>
              <span v-if="skill.description" class="text-xs text-muted-foreground truncate">{{ skill.description }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="flex flex-col gap-2">
        <div
          v-if="currentSkills.length > 0"
          class="flex items-center gap-2 flex-wrap"
        >
          <div
            v-for="(name, idx) in currentSkills"
            :key="`skill-${idx}-${name}`"
            class="flex items-center gap-1 h-7 px-2.5 bg-primary/10 text-primary rounded-full text-xs font-medium whitespace-nowrap border border-primary/20 flex-shrink-0"
          >
            <span class="max-w-[160px] truncate">@{{ name }}</span>
            <button
              type="button"
              @click="removeSkillAt(idx)"
              class="ml-0.5 w-3.5 h-3.5 flex items-center justify-center rounded-full hover:bg-primary/20"
            >
              <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          </div>
        </div>

        <ChipInput
          ref="editorRef"
          v-model="inputValue"
          :placeholder="isLoading ? (t('messageInput.placeholderGenerating') || 'AI正在生成回复，可直接输入新消息...') : t('messageInput.placeholder')"
          wrapper-class="w-full"
          @keydown="handleKeyDown"
          @compositionstart="handleCompositionStart"
          @compositionend="handleCompositionEnd"
          @paste="handlePaste"
          @caret-update="handleCaretUpdate"
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
            :disabled="isOptimizingInput || (!isLoading && !canSubmitNow)"
            class="h-7 w-7 rounded-full transition-all duration-200"
            :class="[
              !isLoading && !canSubmitNow ? 'opacity-50 cursor-not-allowed' : '',
              isLoading ? 'bg-destructive hover:bg-destructive/90 text-destructive-foreground' : ''
            ]"
            :title="sendButtonTitle"
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
  buildOrderedMultimodalContent,
  cleanupAttachmentName,
  extractAttachmentName,
} from '../../utils/multimodalContent.js'
import { flattenMessageForComposerRebuild } from '../../utils/composerFromMessageFlatten.js'

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
// 已选中的技能列表（按选择顺序），提交时全部以 <skill> 形式串联到头部。
const currentSkills = ref([])
// 当前命中的 slash 查询：{ keyword, deleteLength } —— deleteLength 用于在选中技能后从光标前删掉 `/keyword`。
const activeSkillQuery = ref(null)
const uploadedFiles = ref([])
const isComposing = ref(false)
const isDraggingOver = ref(false)
const planEnabled = ref(false)
const isOptimizingInput = ref(false)
const optimizeAbortController = ref(null)
const deepThinkingEnabled = computed(() => props.config?.deepThinking !== false)
const activeToggleClass = 'border-primary/30 bg-primary/10 text-foreground hover:bg-primary/15 hover:border-primary/40'
const inactiveToggleClass = 'border-border bg-background text-muted-foreground hover:text-foreground hover:bg-muted/60'

const canSubmitNow = computed(() => {
  const hasContent = Boolean(
    inputValue.value.trim() ||
    uploadedFiles.value.length > 0 ||
    currentSkills.value.length > 0
  )
  if (!hasContent) return false
  if (uploadedFiles.value.some((f) => f.uploading || !f.url)) return false
  return true
})

const sendButtonTitle = computed(() => {
  if (!props.isLoading && uploadedFiles.value.some((f) => f.uploading)) {
    return t('messageInput.waitForUpload')
  }
  if (props.isLoading) {
    return inputValue.value.trim() || uploadedFiles.value.length > 0
      ? (t('messageInput.stopAndSendTitle') || '停止生成并发送')
      : (t('messageInput.stopTitle') || '停止生成')
  }
  return t('messageInput.sendTitle')
})

const normalizedSkillsKey = (names) =>
  [...(names || [])].map((s) => String(s || '').trim()).filter(Boolean).sort().join('\u0001')

// 来自能力预设：第二次 Enter 才发送；点此发送不受影响（快照与剥离头部 <skill> 后的正文及 chips 对齐）
const guidedPresetFirstEnterPending = ref(false)
const guidedPresetSnapshot = ref('')
const guidedPresetSkillsKey = ref('')

const clearGuidedPresetGate = () => {
  guidedPresetFirstEnterPending.value = false
  guidedPresetSnapshot.value = ''
  guidedPresetSkillsKey.value = ''
}

watch(
  [inputValue, uploadedFiles, currentSkills],
  () => {
    if (!guidedPresetFirstEnterPending.value) return
    const snap = guidedPresetSnapshot.value
    const skillSnap = guidedPresetSkillsKey.value
    if (
      inputValue.value.trim() !== snap ||
      uploadedFiles.value.length > 0 ||
      normalizedSkillsKey(currentSkills.value) !== skillSnap
    ) {
      clearGuidedPresetGate()
    }
  },
  { deep: true },
)

const tryConsumeGuidedPresetFirstEnter = () => {
  if (!guidedPresetFirstEnterPending.value || props.isLoading) return false
  const snap = guidedPresetSnapshot.value
  const skillSnap = guidedPresetSkillsKey.value
  const textOk = inputValue.value.trim() === snap
  const skillsOk = normalizedSkillsKey(currentSkills.value) === skillSnap
  if (
    uploadedFiles.value.length > 0 ||
    !textOk ||
    !skillsOk ||
    (!snap && !skillSnap)
  ) {
    return false
  }
  guidedPresetFirstEnterPending.value = false
  toast.message(t('messageInput.guidedPresetPressEnterAgain'))
  return true
}

watch(() => props.presetText, async (newVal) => {
  if (typeof newVal !== 'string' || !newVal) {
    clearGuidedPresetGate()
    return
  }
  if (newVal === inputValue.value) return
  inputValue.value = newVal
  await nextTick()
  guidedPresetSnapshot.value = inputValue.value.trim()
  guidedPresetSkillsKey.value = normalizedSkillsKey(currentSkills.value)
  guidedPresetFirstEnterPending.value = Boolean(
    guidedPresetSnapshot.value || guidedPresetSkillsKey.value,
  )
  editorRef.value?.focus(true)
})

watch(() => props.agentId, () => {
  skills.value = []
  currentSkills.value = []
  activeSkillQuery.value = null
  showSkillList.value = false
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
  if (!skill || !skill.name) return
  if (!currentSkills.value.includes(skill.name)) {
    currentSkills.value = [...currentSkills.value, skill.name]
  }
  const query = activeSkillQuery.value
  if (query && editorRef.value?.deleteCharsBeforeCaret) {
    editorRef.value.deleteCharsBeforeCaret(query.deleteLength)
  }
  activeSkillQuery.value = null
  showSkillList.value = false
  skillKeyword.value = ''
  nextTick(() => {
    editorRef.value?.focus(false)
  })
}

const removeSkillAt = (idx) => {
  if (idx < 0 || idx >= currentSkills.value.length) return
  const next = currentSkills.value.slice()
  next.splice(idx, 1)
  currentSkills.value = next
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
const LEADING_SKILL_TAGS_RE = /^(?:\s*<skill>(.*?)<\/skill>\s*)+/i
const SINGLE_SKILL_TAG_RE = /<skill>(.*?)<\/skill>/gi

const ensureSkillsLoaded = async () => {
  if (skills.value.length > 0 || loadingSkills.value) return
  try {
    loadingSkills.value = true
    const res = await skillAPI.getSkills({ agent_id: props.agentId })
    skills.value = Array.isArray(res?.skills) ? res.skills : []
  } catch (error) {
    console.error('获取技能列表失败:', error)
    skills.value = []
  } finally {
    loadingSkills.value = false
  }
}

watch(inputValue, (newVal) => {
  if (isComposing.value) return
  // 头部如果出现一段连续的 <skill>xxx</skill>，自动剥离并并入 currentSkills（顺序保留、去重）
  const normalizedInput = newVal.replace(LEADING_CONTROL_TAG_RE, '')
  const skillBlock = normalizedInput.match(LEADING_SKILL_TAGS_RE)
  if (!skillBlock) return
  const names = []
  let m
  SINGLE_SKILL_TAG_RE.lastIndex = 0
  while ((m = SINGLE_SKILL_TAG_RE.exec(skillBlock[0])) !== null) {
    const name = (m[1] || '').trim()
    if (name) names.push(name)
  }
  if (names.length === 0) return
  const merged = currentSkills.value.slice()
  for (const n of names) {
    if (!merged.includes(n)) merged.push(n)
  }
  currentSkills.value = merged
  inputValue.value = normalizedInput.replace(skillBlock[0], '')
})

const handleCaretUpdate = async () => {
  if (isComposing.value) return
  const editor = editorRef.value
  if (!editor || typeof editor.getSkillQuery !== 'function') {
    activeSkillQuery.value = null
    showSkillList.value = false
    return
  }
  const query = editor.getSkillQuery()
  if (!query) {
    activeSkillQuery.value = null
    showSkillList.value = false
    return
  }
  // 只有 keyword 真的变了才重置选中项；否则会被 ArrowUp/Down 的 keyup 反复重置回 0，
  // 导致用户感觉「方向键不能切换可选技能」。
  const keywordChanged = skillKeyword.value !== query.keyword
  activeSkillQuery.value = query
  skillKeyword.value = query.keyword
  if (keywordChanged) {
    selectedSkillIndex.value = 0
  }
  showSkillList.value = true
  await ensureSkillsLoaded()
}

watch(filteredSkills, (list) => {
  if (!list || list.length === 0) {
    selectedSkillIndex.value = 0
    return
  }
  if (selectedSkillIndex.value >= list.length) {
    selectedSkillIndex.value = list.length - 1
  }
  if (selectedSkillIndex.value < 0) selectedSkillIndex.value = 0
})

const buildHeadPrefix = () => {
  let prefix = ''
  if (currentSkills.value.length > 0) {
    prefix = currentSkills.value.map(name => `<skill>${name}</skill>`).join(' ') + ' '
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

const hasSubmittableInput = () => canSubmitNow.value

const dispatchSubmit = (needInterrupt) => {
  if (uploadedFiles.value.some((f) => f.uploading || !f.url)) {
    return
  }
  const { plainText, multimodalContent } = buildSubmissionPayload()
  if (!plainText && (!multimodalContent || multimodalContent.length === 0)) return

  inputValue.value = ''
  uploadedFiles.value = []
  currentSkills.value = []
  activeSkillQuery.value = null
  showSkillList.value = false

  emit('sendMessage', plainText, {
    multimodalContent,
    needInterrupt
  })
}

const handleSubmit = (e) => {
  e.preventDefault()
  cancelOptimizeInput()
  clearGuidedPresetGate()
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

  // Backspace：当输入为空时，删除最后一个已选技能
  if (!composing && e.key === 'Backspace' && inputValue.value === '' && currentSkills.value.length > 0) {
    e.preventDefault()
    currentSkills.value = currentSkills.value.slice(0, -1)
    return
  }

  if (e.key === 'Enter' && !e.shiftKey && !composing) {
    e.preventDefault()
    if (!props.isLoading && tryConsumeGuidedPresetFirstEnter()) return
    handleSubmit(e)
  }
}

const handleCompositionStart = () => {
  isComposing.value = true
}

const handleCompositionEnd = () => {
  isComposing.value = false
}

const unwrapOssImportPayload = (res) => (res?.data ?? res)

const urlKeyForDedup = (u) => {
  try {
    const x = new URL(String(u))
    x.hash = ''
    return x.href
  } catch {
    return String(u || '').trim()
  }
}

const clipboardPlainFromData = (clipboardData) => {
  if (!clipboardData) return ''
  const plain = clipboardData.getData('text/plain')
  if (plain) return plain
  const html = clipboardData.getData('text/html')
  if (!html) return ''
  const div = document.createElement('div')
  div.innerHTML = html
  return div.innerText || div.textContent || ''
}

const pasteMarkdownRemoteImagesIntoEditor = async (segments) => {
  const inflightMirrors = new Map()

  const mirrorOnce = (remoteUrl) => {
    const k = urlKeyForDedup(remoteUrl)
    if (!inflightMirrors.has(k)) {
      inflightMirrors.set(k, ossApi.importFromUrl(remoteUrl, null).then(unwrapOssImportPayload))
    }
    return inflightMirrors.get(k)
  }

  const mirrorSandboxOnce = (agentId, filename) => {
    const k = `sandbox:${String(agentId)}:${String(filename)}`
    if (!inflightMirrors.has(k)) {
      inflightMirrors.set(k, ossApi.importSandboxUpload(agentId, filename).then(unwrapOssImportPayload))
    }
    return inflightMirrors.get(k)
  }

  for (const seg of segments) {
    if (seg.kind === 'text') {
      const txt = seg.text ?? ''
      if (txt) {
        editorRef.value?.insertText(txt)
      }
      continue
    }

    if (seg.kind !== 'remoteImage' && seg.kind !== 'sageSandboxImage') continue

    let mirrorPromise
    let previewSeed = ''
    if (seg.kind === 'remoteImage') {
      previewSeed = /^https?:\/\//i.test(seg.url) ? seg.url : ''
      mirrorPromise = mirrorOnce(seg.url)
    } else {
      mirrorPromise = mirrorSandboxOnce(seg.agentId, seg.filename)
    }

    const id = allocateAttachmentId()
    const nameHint = cleanupAttachmentName(seg.preferredName || '图片')
    const fileItem = {
      id,
      file: null,
      preview: previewSeed,
      type: 'image',
      name: nameHint,
      uploading: true,
      url: null,
    }

    uploadedFiles.value.push(fileItem)
    await insertChipForFile(fileItem)

    try {
      const payload = await mirrorPromise

      if (uploadedFiles.value.indexOf(fileItem) < 0) {
        continue
      }

      fileItem.url = payload?.url || (typeof payload === 'string' ? payload : '')
      const serverFilename = (payload && typeof payload === 'object') ? payload.filename : ''
      if (serverFilename) {
        fileItem.name = cleanupAttachmentName(serverFilename)
        try {
          editorRef.value?.updateChipName?.(fileItem.id, serverFilename)
        } catch (_) { /* noop */ }
      }
      fileItem.uploading = false
      if (/^https?:\/\//i.test(fileItem.preview) && /^https?:\/\//i.test(fileItem.url)) {
        fileItem.preview = fileItem.url
      }
      if ((payload && typeof payload === 'object') && payload.http_url && !/^https?:\/\//i.test(String(fileItem.url || ''))) {
        fileItem.preview = payload.http_url
      }
      if (/^https?:\/\//i.test(String(fileItem.url || '')) && (!fileItem.preview || !/^https?:\/\//i.test(String(fileItem.preview)))) {
        fileItem.preview = fileItem.url
      }
    } catch (err) {
      const index = uploadedFiles.value.indexOf(fileItem)
      if (index > -1) {
        uploadedFiles.value.splice(index, 1)
      }
      inputValue.value = removeAttachmentPlaceholder(inputValue.value, fileItem.id)
      console.error('[MessageInput] import_url paste failed:', err)
      throw err
    }
  }

  await nextTick()
  editorRef.value?.focus(false)
}

const handlePaste = async (e) => {
  const clipboardData = e.clipboardData || e.originalEvent?.clipboardData
  if (!clipboardData) return

  let hasFiles = false
  const items = clipboardData.items

  if (items && items.length > 0) {
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
  }

  if (hasFiles) {
    return
  }

  const plain = clipboardPlainFromData(clipboardData)
  const segments = flattenMessageForComposerRebuild(plain || '')
  if (!segments.some((s) => s.kind === 'remoteImage' || s.kind === 'sageSandboxImage')) {
    return
  }

  e.preventDefault()
  try {
    await pasteMarkdownRemoteImagesIntoEditor(segments)
  } catch {
    toast.error(t('messageInput.pasteUploadFailed'))
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
    const payload = response?.data ?? response

    if (uploadedFiles.value.indexOf(fileItem) < 0) {
      if (preview) URL.revokeObjectURL(preview)
      return
    }

    fileItem.url = payload?.url || (typeof payload === 'string' ? payload : '')
    const serverFilename = (payload && typeof payload === 'object') ? payload.filename : ''
    if (serverFilename) {
      fileItem.name = serverFilename
      try {
        editorRef.value?.updateChipName?.(fileItem.id, serverFilename)
      } catch (_) { /* noop */ }
    }
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
  if (file.preview && typeof file.preview === 'string' && file.preview.startsWith('blob:')) {
    try {
      URL.revokeObjectURL(file.preview)
    } catch (_) { /* noop */ }
  }
  if (file.id != null) {
    inputValue.value = removeAttachmentPlaceholder(inputValue.value, file.id)
  }
  uploadedFiles.value.splice(index, 1)
}

// 当用户在 textarea 中手动删除某个占位符（或点击 chip 删除）时，同步移除对应的附件项。
watch(inputValue, (text) => {
  if (uploadedFiles.value.length === 0) return
  const stale = []
  for (const f of uploadedFiles.value) {
    if (f.id == null) continue
    if (!textHasAttachmentPlaceholder(text || '', f.id)) {
      stale.push(f)
    }
  }
  if (stale.length === 0) return
  for (const f of stale) {
    if (f.preview && typeof f.preview === 'string' && f.preview.startsWith('blob:')) {
      try {
        URL.revokeObjectURL(f.preview)
      } catch (_) { /* noop */ }
    }
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
