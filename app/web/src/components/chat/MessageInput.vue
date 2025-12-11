<template>
  <form @submit="handleSubmit" class="message-form">
    <!-- 图片预览区域 -->
    <div v-if="uploadedImages.length > 0" class="image-preview-container">
      <div class="image-preview-list">
        <div v-for="(image, index) in uploadedImages" :key="index" class="image-preview-item">
          <img :src="image.preview" :alt="`预览图 ${index + 1}`" class="preview-image" />
          <button type="button" @click="removeImage(index)" class="remove-image-btn"
            :title="t('messageInput.removeImage')">
            ✕
          </button>

        </div>
      </div>
    </div>
    <div v-if="uploadedVideos.length > 0" class="image-preview-container">
      <div class="image-preview-list">
        <div v-for="(video, index) in uploadedVideos" :key="'v-' + index" class="image-preview-item">
          <video :src="video.preview || video.url" class="preview-video" muted playsinline></video>
          <button type="button" @click="removeVideo(index)" class="remove-image-btn"
            :title="t('messageInput.removeImage')">
            ✕
          </button>
        </div>
      </div>
    </div>

    <div class="input-wrapper">
      <!-- 图片上传按钮 -->
      <button type="button" @click="triggerFileInput" class="upload-button" :disabled="isLoading"
        :title="t('messageInput.uploadImage')">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M21 19V5C21 3.9 20.1 3 19 3H5C3.9 3 3 3.9 3 5V19C3 20.1 3.9 21 5 21H19C20.1 21 21 20.1 21 19ZM8.5 13.5L11 16.51L14.5 12L19 18H5L8.5 13.5Z"
            fill="currentColor" />
        </svg>
      </button>

      <textarea ref="textareaRef" v-model="inputValue" @keydown="handleKeyDown"
        :placeholder="t('messageInput.placeholder')" class="message-textarea" :disabled="isLoading" rows="1" />

      <div class="button-group">
        <button v-if="isLoading" type="button" @click="handleStop" class="stop-button"
          :title="t('messageInput.stopTitle')">
          ⏹️ {{ t('messageInput.stop') }}
        </button>
        <button v-else type="submit" :disabled="!inputValue.trim() && uploadedImages.length === 0" class="send-button"
          :title="t('messageInput.sendTitle')">
          {{ t('messageInput.send') }}
        </button>
      </div>

      <!-- 隐藏的文件输入框 -->
      <input ref="fileInputRef" type="file" accept="image/*,video/*" multiple @change="handleFileSelect"
        style="display: none;" />
    </div>
  </form>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import { ossApi } from '../../api/oss.js'

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

// 图片上传相关状态
const uploadedImages = ref([])
const uploadedVideos = ref([])

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
  if ((inputValue.value.trim() || uploadedImages.value.length > 0 || uploadedVideos.value.length > 0) && !props.isLoading) {
    let messageContent = inputValue.value.trim()
    if (uploadedImages.value.length > 0 || uploadedVideos.value.length > 0) {
      const imageUrls = uploadedImages.value.filter(img => img.url).map(img => img.url)
      const videoUrls = uploadedVideos.value.filter(v => v.url).map(v => v.url)
      const urls = [...imageUrls, ...videoUrls]
      if (urls.length > 0) {
        if (messageContent) {
          messageContent += '\n\n'
        }
        messageContent += urls.join('\n')
      }
    }
    if (messageContent) {
      emit('sendMessage', messageContent)
      inputValue.value = ''
      uploadedImages.value = []
      uploadedVideos.value = []
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
  const imageFiles = files.filter(f => f.type.startsWith('image/'))
  const videoFiles = files.filter(f => f.type.startsWith('video/'))
  if (imageFiles.length === 0 && videoFiles.length === 0) {
    alert('请选择有效的图片或视频文件')
    return
  }
  for (const file of imageFiles) {
    await processImageFile(file)
  }
  for (const file of videoFiles) {
    await processVideoFile(file)
  }
  event.target.value = ''
}

// 处理单个图片文件
const processImageFile = async (file) => {
  // 创建预览URL
  const preview = URL.createObjectURL(file)

  // 添加到上传列表，直接标记为上传成功状态
  const imageItem = {
    file,
    preview,
    uploading: false,
    url: null
  }

  uploadedImages.value.push(imageItem)

  try {
    // 调用OSS API上传
    const imageUrl = await ossApi.uploadImage(file)

    // 更新图片URL
    imageItem.url = imageUrl

    console.log('图片上传成功:', imageUrl)

  } catch (error) {
    console.error('图片上传失败:', error)

    // 移除失败的图片
    const index = uploadedImages.value.indexOf(imageItem)
    if (index > -1) {
      uploadedImages.value.splice(index, 1)
      URL.revokeObjectURL(preview)
    }
    alert('图片上传失败，请重试')
  }
}

const processVideoFile = async (file) => {
  const preview = URL.createObjectURL(file)
  const videoItem = {
    file,
    preview,
    uploading: false,
    url: null
  }
  uploadedVideos.value.push(videoItem)
  try {
    const videoUrl = await ossApi.uploadVideo(file)
    videoItem.url = videoUrl
    console.log('视频上传成功:', videoUrl)
  } catch (error) {
    console.error('视频上传失败:', error)
    const index = uploadedVideos.value.indexOf(videoItem)
    if (index > -1) {
      uploadedVideos.value.splice(index, 1)
      URL.revokeObjectURL(preview)
    }
    alert('视频上传失败，请重试')
  }
}

// 移除图片
const removeImage = (index) => {
  const image = uploadedImages.value[index]
  if (image.preview) {
    URL.revokeObjectURL(image.preview)
  }
  uploadedImages.value.splice(index, 1)
}
const removeVideo = (index) => {
  const video = uploadedVideos.value[index]
  if (video && video.preview) {
    URL.revokeObjectURL(video.preview)
  }
  uploadedVideos.value.splice(index, 1)
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
}
</style>
