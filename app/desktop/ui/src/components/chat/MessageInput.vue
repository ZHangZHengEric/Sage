<template>
  <form @submit="handleSubmit" class="w-full max-w-[800px] mx-auto">
    <!-- 文件预览区域 -->
    <div v-if="uploadedFiles.length > 0" class="mb-3">
      <div class="flex flex-wrap gap-2 p-3 bg-muted/50 rounded-xl border border-border">
        <div v-for="(file, index) in uploadedFiles" :key="index" class="relative w-20 h-20 rounded-lg overflow-hidden bg-background border border-border group">
          <!-- 图片预览 -->
          <img v-if="file.type === 'image'" :src="file.preview" :alt="`预览图 ${index + 1}`" class="w-full h-full object-cover" />
          <!-- 视频预览 -->
          <video v-else-if="file.type === 'video'" :src="file.preview || file.url" class="w-full h-full object-cover" muted
            playsinline></video>
          <!-- 其他文件预览 -->
          <div v-else class="flex flex-col items-center justify-center w-full h-full p-2 text-muted-foreground" :title="file.name">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mb-1">
              <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
              <polyline points="13 2 13 9 20 9"></polyline>
            </svg>
            <span class="text-[10px] truncate w-full text-center">{{ file.name }}</span>
          </div>

          <button type="button" @click="removeFile(index)" class="absolute top-1 right-1 w-5 h-5 flex items-center justify-center rounded-full bg-background/90 text-destructive hover:bg-destructive hover:text-destructive-foreground transition-colors shadow-sm opacity-0 group-hover:opacity-100"
            :title="t('messageInput.removeFile')">
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
      <!-- 技能列表弹窗 -->
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
            :class="{'bg-accent text-accent-foreground': index === selectedSkillIndex}"
            @click="selectSkill(skill)"
          >
            <div class="flex flex-col overflow-hidden">
              <span class="font-medium truncate">{{ skill.name }}</span>
              <span class="text-xs text-muted-foreground truncate" v-if="skill.description">{{ skill.description }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区域：包含技能标签和文本框 -->
      <div class="flex items-start gap-2">
        <!-- 选中的技能展示 -->
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
          :placeholder="isLoading ? t('messageInput.placeholderGenerating') || 'AI正在生成回复，可直接输入新消息...' : t('messageInput.placeholder')"
          class="flex-1 min-h-[44px] max-h-[200px] py-1.5 px-1 bg-transparent border-0 focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:outline-none resize-none shadow-none text-sm leading-relaxed outline-none !ring-0 !ring-offset-0 !border-0"
          rows="2"
          style="box-shadow: none; outline: none;"
        />
      </div>

      <!-- 底部区域：附件按钮在左下角，发送按钮在右下角 -->
      <div class="flex items-center justify-between">
        <!-- 文件上传按钮 - 左下角 -->
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
              stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </Button>

        <!-- 发送按钮 - 右下角 -->
        <Button
          type="submit"
          size="icon"
          :disabled="!isLoading && !inputValue.trim() && uploadedFiles.length === 0"
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

      <!-- 隐藏的文件输入框 -->
      <input ref="fileInputRef" type="file" multiple @change="handleFileSelect" style="display: none;" />
    </div>
  </form>
</template>

<script setup>
import { ref, watch, nextTick, computed, onMounted, onUnmounted } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import { ossApi } from '../../api/oss.js'
import { skillAPI } from '../../api/skill.js'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { listen } from '@tauri-apps/api/event'

const props = defineProps({
  isLoading: {
    type: Boolean,
    default: false
  },
  presetText: {
    type: String,
    default: ''
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

// 技能列表相关状态
const showSkillList = ref(false)
const loadingSkills = ref(false)
const skills = ref([])
const selectedSkillIndex = ref(0)
const skillKeyword = ref('')
const currentSkill = ref(null)

const filteredSkills = computed(() => {
  // 获取 agent 配置的可用技能列表
  const agentAvailableSkills = props.selectedAgent?.availableSkills || []
  
  // 先根据 agent 配置过滤技能
  let filtered = skills.value
  if (agentAvailableSkills.length > 0) {
    filtered = skills.value.filter(skill =>
      agentAvailableSkills.includes(skill.name)
    )
  }
  
  // 再根据关键词过滤
  if (!skillKeyword.value) return filtered
  const lowerKeyword = skillKeyword.value.toLowerCase()
  return filtered.filter(skill =>
    (skill.name || '').toLowerCase().startsWith(lowerKeyword)
  )
})

// 监听 presetText 变化，预填输入框
watch(() => props.presetText, async (newVal) => {
  if (typeof newVal !== 'string' || !newVal) return
  if (newVal === inputValue.value) return
  inputValue.value = newVal
  await nextTick()
  const el = textareaRef.value?.$el || textareaRef.value
  if (el && el.focus) {
    el.focus()
    // 将光标移动到末尾
    const length = el.value?.length ?? 0
    try {
      el.setSelectionRange(length, length)
    } catch {
      // ignore
    }
  }
  adjustTextareaHeight()
})

// 选中技能
const selectSkill = (skill) => {
  currentSkill.value = skill.name
  inputValue.value = ''
  showSkillList.value = false
  nextTick(() => {
    // 聚焦并调整高度
    const el = textareaRef.value?.$el || textareaRef.value
    if (el) el.focus()
    adjustTextareaHeight()
  })
}

// 文件上传相关状态
const uploadedFiles = ref([])
const isComposing = ref(false)
const isDraggingOver = ref(false)

// 拖拽事件处理
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

  // 方式1: 使用dataTransfer.items
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

  // 方式2: 使用dataTransfer.files
  if (files.length === 0) {
    const dtFiles = e.dataTransfer?.files
    if (dtFiles && dtFiles.length > 0) {
      for (let i = 0; i < dtFiles.length; i++) {
        files.push(dtFiles[i])
      }
    }
  }

  // 处理所有文件
  for (const file of files) {
    await processFile(file)
  }
}

// 从FileEntry获取File对象
const getFileFromEntry = (fileEntry) => {
  return new Promise((resolve) => {
    fileEntry.file((file) => {
      resolve(file)
    }, () => {
      resolve(null)
    })
  })
}

// Tauri 桌面端文件拖拽处理
let tauriDropListener = null
let tauriEnterListener = null
let tauriLeaveListener = null

onMounted(() => {
  // 监听 Tauri 的文件拖拽事件（桌面端）
  if (window.__TAURI__) {
    listen('tauri-drag-enter', () => {
      isDraggingOver.value = true
    }).then(unlisten => { tauriEnterListener = unlisten })
    
    listen('tauri-drag-drop', async (event) => {
      isDraggingOver.value = false
      const filePaths = event.payload
      if (filePaths && filePaths.length > 0) {
        // 处理拖拽的文件
        for (const filePath of filePaths) {
          await processTauriFile(filePath)
        }
      }
    }).then(unlisten => { tauriDropListener = unlisten })
    
    listen('tauri-drag-leave', () => {
      isDraggingOver.value = false
    }).then(unlisten => { tauriLeaveListener = unlisten })
  }
})

onUnmounted(() => {
  // 清理 Tauri 事件监听
  if (tauriEnterListener) tauriEnterListener()
  if (tauriDropListener) tauriDropListener()
  if (tauriLeaveListener) tauriLeaveListener()
})

// 处理 Tauri 拖拽的文件
const processTauriFile = async (filePath) => {
  try {
    // 使用 Tauri 的 fs API 读取文件
    const { readFile } = await import('@tauri-apps/plugin-fs')
    const { basename } = await import('@tauri-apps/api/path')
    
    const fileName = await basename(filePath)
    const fileData = await readFile(filePath)
    
    // 创建 File 对象
    const file = new File([fileData], fileName, { type: 'application/octet-stream' })
    
    // 使用现有的 processFile 处理
    await processFile(file)
  } catch (error) {
    console.error('Failed to process Tauri file:', filePath, error)
  }
}

// 自动调整文本区域高度
const adjustTextareaHeight = async () => {
  await nextTick()
  const el = textareaRef.value?.$el || textareaRef.value
  if (el && el.style) {
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }
}

// 监听输入值变化
watch(inputValue, async (newVal) => {
  // 检查是否包含技能标签（粘贴或手动输入）
  const skillMatch = newVal.match(/^<skill>(.*?)<\/skill>\s*/)
  if (skillMatch) {
    currentSkill.value = skillMatch[1]
    inputValue.value = newVal.replace(skillMatch[0], '')
    return
  }

  adjustTextareaHeight()

  if (newVal.startsWith('/')) {
    const keyword = newVal.slice(1)
    skillKeyword.value = keyword

    // 如果技能列表为空，则获取
    if (skills.value.length === 0 && !loadingSkills.value) {
      try {
        loadingSkills.value = true
        console.log('Fetching skills...')
        const res = await skillAPI.getSkills()
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

// 处理表单提交
const handleSubmit = (e) => {
  e.preventDefault()
  
  // 如果正在生成，处理中断逻辑
  if (props.isLoading) {
    // 有内容时：中断并发送；无内容时：仅中断
    const hasContent = inputValue.value.trim() || uploadedFiles.value.length > 0 || currentSkill.value
    
    if (hasContent) {
      // 有内容：中断并发送新消息
      let messageContent = inputValue.value.trim()

      // 如果有选中的技能，添加到消息头部
      if (currentSkill.value) {
        messageContent = `<skill>${currentSkill.value}</skill> ${messageContent}`
      }

      // 构建多模态内容格式
      const multimodalContent = []

      // 添加文本内容
      if (messageContent) {
        multimodalContent.push({ type: 'text', text: messageContent })
      }

      // 处理文件引用链接（包括图片和非图片文件）
      const isMultimodalEnabled = props.selectedAgent?.enableMultimodal === true

      if (isMultimodalEnabled) {
        // 添加图片内容到 multimodalContent（用于多模态模式）
        const imageFiles = uploadedFiles.value.filter(f => f.url && f.type === 'image')
        for (const img of imageFiles) {
          multimodalContent.push({
            type: 'image_url',
            image_url: { url: img.url }
          })
        }
      }

      // 所有文件（包括图片）都添加 Markdown 链接到 messageContent
      const allFiles = uploadedFiles.value.filter(f => f.url)
      if (allFiles.length > 0) {
        const fileInfos = allFiles.map(f => {
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

        // 更新 multimodalContent 中的文本（如果存在）
        if (multimodalContent.length > 0 && multimodalContent[0].type === 'text') {
          multimodalContent[0].text = messageContent
        }
      }

      // 发送消息，同时传递普通格式和多模态格式
      if (messageContent || multimodalContent.length > 0) {
        const pendingMessage = messageContent
        const pendingMultimodal = multimodalContent.length > 0 ? multimodalContent : null
        
        // 清空输入框，准备发送
        inputValue.value = ''
        uploadedFiles.value = []
        currentSkill.value = null
        
        // 发送消息，传入 needInterrupt 标志
        emit('sendMessage', pendingMessage, {
          multimodalContent: pendingMultimodal,
          needInterrupt: true
        })
      }
    } else {
      // 无内容：仅中断
      emit('stopGeneration')
    }
    return
  }
  
  // 正常发送消息逻辑
  if ((inputValue.value.trim() || uploadedFiles.value.length > 0 || currentSkill.value)) {
    let messageContent = inputValue.value.trim()

    // 如果有选中的技能，添加到消息头部
    if (currentSkill.value) {
      messageContent = `<skill>${currentSkill.value}</skill> ${messageContent}`
    }

    // 构建多模态内容格式
    const multimodalContent = []

    // 添加文本内容
    if (messageContent) {
      multimodalContent.push({ type: 'text', text: messageContent })
    }

    // 处理文件引用链接（包括图片和非图片文件）
    const isMultimodalEnabled = props.selectedAgent?.enableMultimodal === true

    if (isMultimodalEnabled) {
      // 添加图片内容到 multimodalContent（用于多模态模式）
      const imageFiles = uploadedFiles.value.filter(f => f.url && f.type === 'image')
      for (const img of imageFiles) {
        multimodalContent.push({
          type: 'image_url',
          image_url: { url: img.url }
        })
      }
    }

    // 所有文件（包括图片）都添加 Markdown 链接到 messageContent
    const allFiles = uploadedFiles.value.filter(f => f.url)
    if (allFiles.length > 0) {
      const fileInfos = allFiles.map(f => {
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

      // 更新 multimodalContent 中的文本（如果存在）
      if (multimodalContent.length > 0 && multimodalContent[0].type === 'text') {
        multimodalContent[0].text = messageContent
      }
    }

    // 发送消息，同时传递普通格式和多模态格式
    if (messageContent || multimodalContent.length > 0) {
      const pendingMessage = messageContent
      const pendingMultimodal = multimodalContent.length > 0 ? multimodalContent : null
      
      // 清空输入框，准备发送
      inputValue.value = ''
      uploadedFiles.value = []
      currentSkill.value = null
      
      // 发送消息
      emit('sendMessage', pendingMessage, {
        multimodalContent: pendingMultimodal,
        needInterrupt: false
      })
    }
  }
}

// 处理键盘事件
const handleKeyDown = (e) => {
  const composing = isComposing.value || e.isComposing || e.keyCode === 229 || e.key === 'Process'
  if (composing) {
    return
  }

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

  // Backspace 删除技能
  if (e.key === 'Backspace' && inputValue.value === '' && currentSkill.value) {
    e.preventDefault()
    currentSkill.value = null
    return
  }

  // 检查是否在输入法组合状态中，如果是则不处理回车键
  if (e.key === 'Enter' && !e.shiftKey) {
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

// 处理粘贴事件
const handlePaste = async (e) => {
  const clipboardData = e.clipboardData || e.originalEvent?.clipboardData
  if (!clipboardData) return

  const items = clipboardData.items
  if (!items || items.length === 0) return

  let hasFiles = false

  // 遍历剪贴板项目
  for (let i = 0; i < items.length; i++) {
    const item = items[i]

    // 处理图片
    if (item.type.startsWith('image/')) {
      e.preventDefault()
      hasFiles = true
      const blob = item.getAsFile()
      if (blob) {
        // 生成默认文件名
        const ext = item.type.split('/')[1] || 'png'
        const filename = `pasted_image_${Date.now()}.${ext}`
        const file = new File([blob], filename, { type: item.type })
        await processFile(file)
      }
    }
    // 处理其他文件类型
    else if (item.kind === 'file') {
      e.preventDefault()
      hasFiles = true
      const file = item.getAsFile()
      if (file) {
        await processFile(file)
      }
    }
  }

  // 如果没有文件，允许默认粘贴行为（文本）
  if (!hasFiles) {
    return
  }
}

// 处理停止生成
const handleStop = () => {
  emit('stopGeneration')
}

// 获取文件MIME类型
const getMimeType = (filename) => {
  const ext = filename.split('.').pop().toLowerCase()
  const mimeMap = {
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'webp': 'image/webp',
    'svg': 'image/svg+xml',
    'mp4': 'video/mp4',
    'webm': 'video/webm',
    'pdf': 'application/pdf',
    'txt': 'text/plain',
    'json': 'application/json',
    'zip': 'application/zip',
    'md': 'text/markdown',
    'csv': 'text/csv',
    'doc': 'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xls': 'application/vnd.ms-excel',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'ppt': 'application/vnd.ms-powerpoint',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
  }
  return mimeMap[ext] || 'application/octet-stream'
}

// 触发文件选择
const triggerFileInput = async () => {
  if (window.__TAURI__) {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const { readFile } = await import('@tauri-apps/plugin-fs')

      const selected = await open({
        multiple: true
      })

      if (selected) {
        const paths = Array.isArray(selected) ? selected : [selected]
        for (const path of paths) {
          try {
            const contents = await readFile(path)
            // Extract filename from path (handles both Windows and Unix separators)
            const filename = path.split(/[\\/]/).pop()
            const mimeType = getMimeType(filename)
            const file = new File([contents], filename, { type: mimeType })
            await processFile(file)
          } catch (err) {
            console.error('Failed to read file:', path, err)
          }
        }
      }
    } catch (e) {
      console.warn('Tauri file selection failed, falling back to web input', e)
      if (fileInputRef.value) {
        fileInputRef.value.click()
      }
    }
  } else {
    if (fileInputRef.value) {
      fileInputRef.value.click()
    }
  }
}

// 处理文件选择
const handleFileSelect = async (event) => {
  const files = Array.from(event.target.files)
  if (files.length === 0) return

  for (const file of files) {
    await processFile(file)
  }
  event.target.value = ''
}

// 处理单个文件
const processFile = async (file) => {
  // 通过 MIME type 或文件扩展名判断类型
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

  // 添加到上传列表，初始状态
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
    // 调用OSS API上传
    const url = await ossApi.uploadFile(file)

    // 更新文件URL
    fileItem.url = url
    fileItem.uploading = false
  } catch (error) {

    // 移除失败的文件
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

// 移除文件
const removeFile = (index) => {
  const file = uploadedFiles.value[index]
  if (file.preview) {
    URL.revokeObjectURL(file.preview)
  }
  uploadedFiles.value.splice(index, 1)
}
</script>
