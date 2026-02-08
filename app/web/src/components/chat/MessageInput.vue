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

    <div class="relative flex items-end gap-2 p-3 bg-muted/30 border border-input rounded-3xl focus-within:ring-2 focus-within:ring-ring focus-within:border-primary transition-all shadow-sm">
      <!-- 文件上传按钮 -->
      <Button 
        type="button" 
        variant="ghost" 
        size="icon" 
        class="h-9 w-9 rounded-full text-muted-foreground hover:text-foreground hover:bg-background"
        @click="triggerFileInput" 
        :disabled="isLoading"
        :title="t('messageInput.uploadFile')"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"
            stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </Button>

      <Textarea 
        ref="textareaRef" 
        v-model="inputValue" 
        @keydown="handleKeyDown"
        :placeholder="t('messageInput.placeholder')" 
        class="flex-1 min-h-[24px] max-h-[200px] py-2 px-0 bg-transparent border-0 focus-visible:ring-0 resize-none shadow-none text-base"
        :disabled="isLoading" 
        rows="1" 
      />

      <div class="flex items-center gap-2 pb-0.5">
        <Button 
          v-if="isLoading" 
          type="button" 
          variant="destructive"
          size="sm"
          @click="handleStop" 
          class="h-8 rounded-full px-3"
          :title="t('messageInput.stopTitle')"
        >
          <span class="mr-1">⏹️</span> {{ t('messageInput.stop') }}
        </Button>
        <Button 
          v-else 
          type="submit" 
          size="icon"
          :disabled="!inputValue.trim() && uploadedFiles.length === 0" 
          class="h-9 w-9 rounded-full transition-all duration-200"
          :class="{ 'opacity-50 cursor-not-allowed': !inputValue.trim() && uploadedFiles.length === 0 }"
          :title="t('messageInput.sendTitle')"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M22 2L11 13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M22 2L15 22L11 13L2 9L22 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </Button>
      </div>

      <!-- 隐藏的文件输入框 -->
      <input ref="fileInputRef" type="file" multiple @change="handleFileSelect" style="display: none;" />
    </div>
  </form>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import { ossApi } from '../../api/oss.js'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

const props = defineProps({
  isLoading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['sendMessage', 'stopGeneration'])

const { t } = useLanguage()

const inputValue = ref('')
const textareaRef = ref(null)
const fileInputRef = ref(null)

// 文件上传相关状态
const uploadedFiles = ref([])

// 自动调整文本区域高度
const adjustTextareaHeight = async () => {
  await nextTick()
  const el = textareaRef.value?.$el || textareaRef.value
  if (el && el.style) {
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }
}

// 监听输入值变化，自动调整高度
watch(inputValue, () => {
  adjustTextareaHeight()
})

// 处理表单提交
const handleSubmit = (e) => {
  e.preventDefault()
  if ((inputValue.value.trim() || uploadedFiles.value.length > 0) && !props.isLoading) {
    let messageContent = inputValue.value.trim()
    if (uploadedFiles.value.length > 0) {
      const fileUrls = uploadedFiles.value.filter(f => f.url).map(f => f.url)

      if (fileUrls.length > 0) {
        if (messageContent) {
          messageContent += '\n\n'
        }
        messageContent += fileUrls.join('\n')
      }
    }
    if (messageContent) {
      emit('sendMessage', messageContent)
      inputValue.value = ''
      uploadedFiles.value = []
    }
  }
}

// 处理键盘事件
const handleKeyDown = (e) => {
  // 检查是否在输入法组合状态中，如果是则不处理回车键
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    handleSubmit(e)
  }
}

// 处理停止生成
const handleStop = () => {
  emit('stopGeneration')
}

// 触发文件选择
const triggerFileInput = () => {
  if (fileInputRef.value) {
    fileInputRef.value.click()
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
  const isImage = file.type.startsWith('image/')
  const isVideo = file.type.startsWith('video/')

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

    console.log('文件上传成功:', url)

  } catch (error) {
    console.error('文件上传失败:', error)

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


