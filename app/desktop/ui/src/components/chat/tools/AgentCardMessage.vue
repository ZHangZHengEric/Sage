<template>
  <div class="agent-card-message w-full max-w-[600px] mb-3 rounded-2xl border bg-card overflow-hidden transition-all hover:shadow-lg hover:border-primary/20">
    <!-- Header with Avatar and Basic Info -->
    <div class="relative bg-gradient-to-br from-primary/5 via-primary/10 to-primary/5 p-5">
      <!-- Background Pattern -->
      <div class="absolute inset-0 opacity-30">
        <div class="absolute top-0 right-0 w-32 h-32 bg-primary/10 rounded-full blur-3xl"></div>
        <div class="absolute bottom-0 left-0 w-24 h-24 bg-primary/5 rounded-full blur-2xl"></div>
      </div>
      
      <div class="relative flex items-start gap-4">
        <!-- Avatar - Auto-generated from API -->
        <div class="relative flex-shrink-0">
          <img 
            :src="avatarUrl" 
            :alt="args.name"
            class="w-20 h-20 rounded-2xl shadow-lg object-cover bg-muted"
          />
          <!-- Status Indicator -->
          <div 
            class="absolute -bottom-1 -right-1 w-6 h-6 rounded-full border-2 border-white flex items-center justify-center"
            :class="isError ? 'bg-destructive' : isCompleted ? 'bg-green-500' : 'bg-blue-500'"
          >
            <div class="w-2 h-2 rounded-full bg-white animate-pulse"></div>
          </div>
        </div>
        
        <!-- Basic Info -->
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 mb-1">
            <h3 class="text-xl font-bold text-foreground">{{ args.name || '未命名智能体' }}</h3>
          </div>
          <p class="text-sm text-muted-foreground leading-relaxed line-clamp-2">{{ args.description || '暂无描述' }}</p>
          
          <!-- Status Badge -->
          <div class="flex items-center gap-2 mt-3">
            <div class="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium"
              :class="[
                isError ? 'bg-destructive/10 text-destructive' : 
                isCompleted ? 'bg-green-500/10 text-green-600' : 
                'bg-blue-500/10 text-blue-600'
              ]">
              <AlertCircle v-if="isError" class="w-3.5 h-3.5" />
              <Check v-else-if="isCompleted" class="w-3.5 h-3.5" />
              <Loader2 v-else class="w-3.5 h-3.5 animate-spin" />
              <span>{{ statusText }}</span>
            </div>
            
            <!-- Agent Type Tag -->
            <div class="flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-primary/10 text-primary">
              <Bot class="w-3 h-3" />
              <span>AI 智能体</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Content Section -->
    <div class="px-5 pb-4">
      <!-- System Prompt Preview - Scrollable with Markdown -->
      <div v-if="args.system_prompt" class="mt-3 pt-3 border-t border-border/30">
        <div class="max-h-[200px] overflow-y-auto custom-scrollbar bg-muted/20 rounded-lg p-3">
          <MarkdownRenderer :content="args.system_prompt" class="text-xs text-muted-foreground" />
        </div>
      </div>

      <!-- Error Message -->
      <div v-if="isError" class="flex items-start gap-3 p-3 mt-3 rounded-lg bg-destructive/5 border border-destructive/20">
        <div class="p-1 rounded-lg bg-destructive/10 text-destructive flex-shrink-0">
          <AlertCircle class="w-3.5 h-3.5" />
        </div>
        <div class="flex-1">
          <p class="text-xs font-medium text-destructive mb-0.5">创建失败</p>
          <p class="text-xs text-destructive/80">{{ resultMessage }}</p>
        </div>
      </div>
    </div>

    <!-- Footer -->
    <div class="px-5 py-3 bg-muted/30 border-t flex items-center justify-between">
      <div class="flex items-center gap-2 text-xs text-muted-foreground">
        <Sparkles class="w-3.5 h-3.5" />
        <span>由 Sage AI 系统创建</span>
      </div>
      <div class="flex items-center gap-2">
        <Button 
          v-if="agentId && isCompleted"
          variant="default" 
          size="sm"
          class="h-8 text-xs"
          @click="openAgentChat"
        >
          <MessageSquare class="w-3.5 h-3.5 mr-1.5" />
          开始对话
        </Button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { 
  Bot, 
  Check, 
  Loader2, 
  AlertCircle,
  Sparkles,
  MessageSquare
} from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'
import { Button } from '@/components/ui/button'
import MarkdownRenderer from '../MarkdownRenderer.vue'

const props = defineProps({
  toolCall: {
    type: Object,
    required: true
  },
  toolResult: {
    type: [Object, String],
    default: null
  },
  isLatest: {
    type: Boolean,
    default: false
  }
})

const { t } = useLanguage()
const router = useRouter()

const args = computed(() => {
  try {
    if (typeof props.toolCall.function.arguments === 'string') {
        return JSON.parse(props.toolCall.function.arguments)
    }
    return props.toolCall.function.arguments
  } catch (e) {
    console.error('Failed to parse agent arguments', e)
    return {}
  }
})

const isCompleted = computed(() => !!props.toolResult)

const isError = computed(() => {
  if (!props.toolResult) return false
  if (typeof props.toolResult === 'object' && (props.toolResult.is_error || props.toolResult.status === 'error')) {
    return true
  }
  if (typeof props.toolResult === 'string' && props.toolResult.toLowerCase().startsWith('error:')) {
    return true
  }
  return false
})

const statusText = computed(() => {
  if (isError.value) return t('common.fail')
  if (isCompleted.value) return t('common.success')
  return t('common.creating')
})

const resultMessage = computed(() => {
  if (!props.toolResult) return ''
  if (typeof props.toolResult === 'string') return props.toolResult
  return props.toolResult.content || ''
})

// Extract agent ID from result message
const agentId = computed(() => {
  if (!props.toolResult) return null
  const message = typeof props.toolResult === 'string' ? props.toolResult : props.toolResult.content || ''
  // Match pattern like "agent_360ab10e" from "Agent spawned successfully. ID: agent_360ab10e."
  const match = message.match(/agent_[a-f0-9]+/)
  return match ? match[0] : null
})

// Generate avatar URL using dicebear API
const avatarUrl = computed(() => {
  const seed = agentId.value || args.value.name || 'default'
  // Use dicebear API to generate avatar
  // Style: bottts (robot avatars) or adventurer (human-like)
  return `https://api.dicebear.com/7.x/bottts/svg?seed=${encodeURIComponent(seed)}&backgroundColor=b6e3f4,c0aede,d1d4f9`
})

const openAgentChat = () => {
  if (!agentId.value) return
  // 先更新 localStorage，确保跳转后能被正确选中
  localStorage.setItem('selectedAgentId', agentId.value)
  console.log('[AgentCardMessage] Saved agent to localStorage:', agentId.value)
  // 使用 window.location.href 强制刷新页面，确保 onMounted 执行
  window.location.href = `/chat?agent=${agentId.value}`
}
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 4px;
  height: 4px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.3);
  border-radius: 4px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: hsl(var(--muted-foreground) / 0.5);
}
</style>
