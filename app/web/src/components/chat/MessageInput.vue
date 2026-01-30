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
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto'
    textareaRef.value.style.height = `${textareaRef.value.scrollHeight}px`
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

<style scoped>
.message-form {
  max-width: 800px;
  margin: 0 auto;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  background: #f8f9fa;
  border: 2px solid #e1e5e9;
  border-radius: 24px;
  padding: 12px 16px;
  transition: all 0.2s ease;
}

.input-wrapper:focus-within {
  border-color: #4facfe;
  box-shadow: 0 0 0 3px rgba(79, 172, 254, 0.1);
}

.message-textarea {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  resize: none;
  font-size: 16px;
  line-height: 1.5;
  color: #333;
  font-family: inherit;
  min-height: 24px;
  max-height: 200px;
  overflow-y: auto;
}

.message-textarea::placeholder {
  color: #999;
}

.message-textarea:disabled {
  color: #999;
  cursor: not-allowed;
}

.button-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.send-button,
.stop-button,
.upload-button {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  border-radius: 16px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.send-button {
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  color: white;
}

.send-button:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(79, 172, 254, 0.3);
}

.send-button:disabled {
  background: #e1e5e9;
  color: #999;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.stop-button {
  background: linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%);
  color: white;
}

.stop-button:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(255, 107, 107, 0.3);
}

.upload-button {
  background: #f1f3f4;
  color: #5f6368;
  padding: 8px;
  border-radius: 12px;
  min-width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #e8eaed;
}

.upload-button:hover:not(:disabled) {
  background: #e8f0fe;
  color: #1a73e8;
  border-color: #dadce0;
  transform: none;
  box-shadow: none;
}

.upload-button:disabled {
  background: #f8f9fa;
  color: #9aa0a6;
  cursor: not-allowed;
  border-color: #f1f3f4;
}

/* 滚动条样式 */
.message-textarea::-webkit-scrollbar {
  width: 6px;
}

.message-textarea::-webkit-scrollbar-track {
  background: transparent;
}

.message-textarea::-webkit-scrollbar-thumb {
  background: #ccc;
  border-radius: 3px;
}

.message-textarea::-webkit-scrollbar-thumb:hover {
  background: #999;
}

/* 图片预览样式 */
.image-preview-container {
  margin-bottom: 12px;
}

.image-preview-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 12px;
  border: 1px solid #e1e5e9;
}

.image-preview-item {
  position: relative;
  width: 80px;
  height: 80px;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
  border: 1px solid #ddd;
}

.preview-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.preview-video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.remove-image-btn {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.9);
  color: #ff4757;
  font-size: 12px;
  font-weight: bold;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.remove-image-btn:hover {
  background: #ff4757;
  color: white;
  transform: scale(1.1);
}

/* File preview specific styles */
.file-preview-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  padding: 8px;
  background: #f0f0f0;
  color: #5f6368;
}

.file-icon {
  width: 24px;
  height: 24px;
  margin-bottom: 4px;
  flex-shrink: 0;
}

.file-name {
  font-size: 10px;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: 1.2;
  width: 100%;
  word-break: break-all;
}

/* 深色模式支持 */
@media (prefers-color-scheme: dark) {
  .message-input-container {
    background: #1a1a1a;
    border-top-color: #333;
  }

  .input-wrapper {
    background: #2d2d2d;
    border-color: #444;
  }

  .input-wrapper:focus-within {
    border-color: #4facfe;
  }

  .message-textarea {
    color: #fff;
  }

  .message-textarea::placeholder {
    color: #888;
  }

  .upload-button {
    background: #3c4043;
    color: #9aa0a6;
    border-color: #5f6368;
  }

  .upload-button:hover:not(:disabled) {
    background: #1a73e8;
    color: #e8f0fe;
    border-color: #1a73e8;
  }

  .upload-button:disabled {
    background: #2d2d2d;
    color: #5f6368;
    border-color: #3c4043;
  }

  .image-preview-list {
    background: #2d2d2d;
    border-color: #444;
  }

  .image-preview-item {
    background: #3d3d3d;
    border-color: #555;
  }

  .file-preview-content {
    background: #3d3d3d;
    color: #9aa0a6;
  }
}
</style>
