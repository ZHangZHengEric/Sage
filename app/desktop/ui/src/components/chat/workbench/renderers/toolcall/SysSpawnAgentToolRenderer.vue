<template>
  <div class="sys-spawn-agent-container h-full flex flex-col">
    <div v-if="!toolResult" class="flex items-center justify-center h-full text-muted-foreground p-4">
      <Loader2 class="w-5 h-5 animate-spin mr-2" />
      <span>{{ t('workbench.tool.creatingAgent') }}</span>
    </div>
    <div v-else-if="toolResult?.is_error" class="flex items-start gap-3 p-4 text-destructive">
      <XCircle class="w-5 h-5 flex-shrink-0 mt-0.5" />
      <div>
        <p class="font-medium">{{ t('workbench.tool.createFailed') }}</p>
        <p class="text-sm opacity-80 mt-1">{{ spawnAgentError }}</p>
      </div>
    </div>
    <div v-else class="flex flex-col h-full">
      <div class="flex items-start gap-3 p-4 pb-3 border-b border-border/30">
        <img :src="spawnAgentAvatarUrl" :alt="spawnAgentName" class="w-10 h-10 rounded-lg bg-muted object-cover flex-shrink-0" />
        <div class="flex-1 min-w-0">
          <h4 class="font-medium text-sm text-foreground">{{ spawnAgentName || t('workbench.tool.untitledAgent') }}</h4>
          <p class="text-xs text-muted-foreground mt-0.5">{{ spawnAgentDescription || t('workbench.tool.noDescription') }}</p>
        </div>
        <Button variant="ghost" size="sm" class="h-7 text-xs" @click="openSpawnedAgentChat">
          <MessageSquare class="w-3.5 h-3.5 mr-1" />
          {{ t('workbench.tool.startChat') }}
        </Button>
      </div>
      <div v-if="spawnAgentSystemPrompt" class="flex-1 min-h-0 overflow-hidden">
        <div class="h-full overflow-auto custom-scrollbar p-4">
          <MarkdownRenderer :content="spawnAgentSystemPrompt" class="text-xs" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Loader2, XCircle, MessageSquare } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import { useLanguage } from '@/utils/i18n'

const { t } = useLanguage()
const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null }
})

const spawnAgentName = computed(() => props.toolArgs.name || '')
const spawnAgentDescription = computed(() => props.toolArgs.description || '')
const spawnAgentSystemPrompt = computed(() => props.toolArgs.system_prompt || '')
const spawnAgentId = computed(() => {
  if (!props.toolResult) return null
  const message = typeof props.toolResult.content === 'string'
    ? props.toolResult.content
    : JSON.stringify(props.toolResult.content)
  const match = message.match(/agent_[a-zA-Z0-9]+/)
  return match ? match[0] : null
})
const spawnAgentError = computed(() => {
  if (!props.toolResult?.is_error) return ''
  return typeof props.toolResult.content === 'string' ? props.toolResult.content : JSON.stringify(props.toolResult.content)
})
const spawnAgentAvatarUrl = computed(() => {
  const seed = spawnAgentId.value || spawnAgentName.value || 'default'
  return `https://api.dicebear.com/7.x/bottts/svg?seed=${encodeURIComponent(seed)}&backgroundColor=b6e3f4,c0aede,d1d4f9`
})
const openSpawnedAgentChat = () => {
  if (!spawnAgentId.value) return
  localStorage.setItem('selectedAgentId', spawnAgentId.value)
  window.location.href = `/chat?agent=${spawnAgentId.value}`
}
</script>
