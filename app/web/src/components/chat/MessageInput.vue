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

      <!-- 选中的技能展示 -->
      <div v-if="currentSkill" class="flex items-center gap-1 h-9 px-3 bg-primary/10 text-primary rounded-full text-sm font-medium whitespace-nowrap border border-primary/20">
        <span class="max-w-[120px] truncate">@{{ currentSkill }}</span>
        <button 
          type="button" 
          @click="currentSkill = null"
          class="ml-1 w-4 h-4 flex items-center justify-center rounded-full hover:bg-primary/20"
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

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
  if (!skillKeyword.value) return skills.value
  const lowerKeyword = skillKeyword.value.toLowerCase()
  return skills.value.filter(skill => 
    (skill.name || '').toLowerCase().startsWith(lowerKeyword)
  )
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
  if ((inputValue.value.trim() || uploadedFiles.value.length > 0 || currentSkill.value) && !props.isLoading) {
    let messageContent = inputValue.value.trim()
    
    // 如果有选中的技能，添加到消息头部
    if (currentSkill.value) {
      messageContent = `<skill>${currentSkill.value}</skill> ${messageContent}`
    }

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
      currentSkill.value = null
    }
  }
}

// 处理键盘事件
const handleKeyDown = (e) => {
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


