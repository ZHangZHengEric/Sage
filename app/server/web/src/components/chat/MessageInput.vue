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

        <Textarea
          ref="textareaRef"
          v-model="inputValue"
          @keydown="handleKeyDown"
          @compositionstart="handleCompositionStart"
          @compositionend="handleCompositionEnd"
          @paste="handlePaste"
          :placeholder="isLoading ? (t('messageInput.placeholderGenerating') || 'AI正在生成回复，请稍候...') : t('messageInput.placeholder')"
          class="flex-1 min-h-[44px] max-h-[200px] py-1.5 px-1 bg-transparent border-0 focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:outline-none resize-none shadow-none text-sm leading-relaxed outline-none !ring-0 !ring-offset-0 !border-0"
          rows="2"
          :disabled="isLoading"
        />
      </div>

      <div class="flex items-center justify-between">
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
          :type="isLoading ? 'button' : 'submit'"
          size="icon"
          :disabled="!isLoading && !inputValue.trim() && uploadedFiles.length === 0"
          class="h-7 w-7 rounded-full transition-all duration-200"
          :class="[
            !isLoading && !inputValue.trim() && uploadedFiles.length === 0 ? 'opacity-50 cursor-not-allowed' : '',
            isLoading ? 'bg-destructive hover:bg-destructive/90 text-destructive-foreground' : ''
          ]"
          :title="isLoading ? (t('messageInput.stopTitle') || '停止生成') : t('messageInput.sendTitle')"
          @click="isLoading ? handleStop() : undefined"
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

      <input ref="fileInputRef" type="file" multiple @change="handleFileSelect" style="display: none;" />
    </div>
  </form>
</template>

<script setup>
import { ref, watch, nextTick, computed } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import { ossApi } from '../../api/oss.js'
import { skillAPI } from '../../api/skill.js'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

const props = defineProps({
  isLoading: {
    type: Boolean,
    default: false
  },
  agentId: {
    type: String,
    default: null
  },
  selectedAgent: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['sendMessage', 'stopGeneration'])

const { t } = useLanguage()

const inputValue = ref('')
const textareaRef = ref(null)
const fileInputRef = ref(null)

const showSkillList = ref(false)
const loadingSkills = ref(false)
const skills = ref([])
const selectedSkillIndex = ref(0)
const skillKeyword = ref('')
const currentSkill = ref(null)
const uploadedFiles = ref([])
const isComposing = ref(false)
const isDraggingOver = ref(false)

watch(() => props.agentId, () => {
  skills.value = []
  currentSkill.value = null
})

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
    const el = textareaRef.value?.$el || textareaRef.value
    if (el) el.focus()
    adjustTextareaHeight()
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

const adjustTextareaHeight = async () => {
  await nextTick()
  const el = textareaRef.value?.$el || textareaRef.value
  if (el && el.style) {
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }
}

watch(inputValue, async (newVal) => {
  if (isComposing.value) {
    adjustTextareaHeight()
    return
  }

  const skillMatch = newVal.match(/^<skill>(.*?)<\/skill>\s*/)
  if (skillMatch) {
    currentSkill.value = skillMatch[1]
    inputValue.value = newVal.replace(skillMatch[0], '')
    return
  }

  adjustTextareaHeight()

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

const handleSubmit = (e) => {
  e.preventDefault()
  if ((inputValue.value.trim() || uploadedFiles.value.length > 0 || currentSkill.value) && !props.isLoading) {
    let messageContent = inputValue.value.trim()

    if (currentSkill.value) {
      messageContent = `<skill>${currentSkill.value}</skill> ${messageContent}`
    }

    const multimodalContent = []

    if (messageContent) {
      multimodalContent.push({ type: 'text', text: messageContent })
    }

    const isMultimodalEnabled = props.selectedAgent?.enableMultimodal === true

    if (isMultimodalEnabled) {
      const imageFiles = uploadedFiles.value.filter(f => f.url && f.type === 'image')
      for (const img of imageFiles) {
        multimodalContent.push({
          type: 'image_url',
          image_url: { url: img.url }
        })
      }
    }

    const nonImageFiles = uploadedFiles.value.filter(f => f.url && (isMultimodalEnabled ? f.type !== 'image' : true))
    if (nonImageFiles.length > 0) {
      const fileInfos = nonImageFiles.map(f => {
        let cleanName = f.name || '文件'
        cleanName = cleanName.replace(/_\d{14}\.([^.]+)$/, '.$1')
        cleanName = cleanName.replace(/_\d{14}_/, '_')
        return { url: f.url, name: cleanName }
      })

      if (messageContent && fileInfos.length > 0) {
        messageContent += '\n\n'
      }
      const markdownLinks = fileInfos.map(f => `[${f.name}](${f.url})`)
      messageContent += markdownLinks.join('\n')

      if (multimodalContent.length > 0 && multimodalContent[0].type === 'text') {
        multimodalContent[0].text = messageContent
      }
    }

    if (messageContent || multimodalContent.length > 0) {
      emit('sendMessage', messageContent, {
        multimodalContent: multimodalContent.length > 0 ? multimodalContent : null
      })
      inputValue.value = ''
      uploadedFiles.value = []
      currentSkill.value = null
    }
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

const handleStop = () => {
  emit('stopGeneration')
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
    file,
    preview,
    type: isImage ? 'image' : (isVideo ? 'video' : 'file'),
    name: file.name,
    uploading: true,
    url: null
  }

  uploadedFiles.value.push(fileItem)

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
    alert('文件上传失败，请重试')
  }
}

const removeFile = (index) => {
  const file = uploadedFiles.value[index]
  if (file.preview) {
    URL.revokeObjectURL(file.preview)
  }
  uploadedFiles.value.splice(index, 1)
}
</script>
