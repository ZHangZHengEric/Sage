<template>
  <div class="sys-delegate-task-container h-full flex flex-col">
    <div v-if="!toolResult" class="flex items-center justify-center h-full text-muted-foreground p-4">
      <Loader2 class="w-5 h-5 animate-spin mr-2" />
      <span>{{ t('workbench.tool.delegatingTask') }}</span>
    </div>
    <div v-else-if="toolResult?.is_error" class="flex items-start gap-3 p-4 text-destructive">
      <XCircle class="w-5 h-5 flex-shrink-0 mt-0.5" />
      <div>
        <p class="font-medium">{{ t('workbench.tool.delegateFailed') }}</p>
        <p class="text-sm opacity-80 mt-1">{{ delegationError }}</p>
      </div>
    </div>
    <div v-else class="flex flex-col h-full overflow-hidden">
      <div class="flex items-center justify-center gap-6 py-4 border-b border-border/30 bg-muted/20 flex-shrink-0">
        <div class="flex flex-col items-center gap-2 w-[100px]">
          <div class="relative">
            <img
              :src="currentAgentAvatar"
              :alt="currentAgentName"
              class="w-12 h-12 rounded-xl bg-muted object-cover border-2 border-primary/30"
            />
            <div class="absolute -bottom-1 -right-1 w-5 h-5 rounded-full bg-primary flex items-center justify-center">
              <User class="w-3 h-3 text-primary-foreground" />
            </div>
          </div>
          <span class="text-xs text-muted-foreground">{{ t('workbench.tool.delegator') }}</span>
        </div>

        <div class="flex flex-col items-center gap-1">
          <ArrowRight class="w-5 h-5 text-muted-foreground" />
          <span class="text-xs text-muted-foreground">{{ delegateTasks.length }} {{ t('workbench.tool.tasks') }}</span>
        </div>

        <div class="flex flex-col items-center gap-2 w-[100px]">
          <div class="flex -space-x-2">
            <img
              v-for="(task, idx) in delegateTasks.slice(0, 3)"
              :key="idx"
              :src="getAgentAvatar(task.agent_id)"
              :alt="task.agent_id"
              class="w-10 h-10 rounded-xl bg-muted object-cover border-2 border-background"
            />
            <div v-if="delegateTasks.length > 3" class="w-10 h-10 rounded-xl bg-muted flex items-center justify-center border-2 border-background text-xs font-medium">
              +{{ delegateTasks.length - 3 }}
            </div>
          </div>
          <span class="text-sm font-medium truncate w-full text-center">{{ delegateTasks.length }} {{ t('workbench.tool.targetAgents') }}</span>
        </div>
      </div>

      <div class="flex-1 overflow-auto p-4 space-y-3 custom-scrollbar">
        <div
          v-for="(task, index) in delegateTasks"
          :key="index"
          class="border rounded-lg p-3 hover:bg-muted/30 transition-colors"
        >
          <div class="flex items-start gap-3">
            <img
              :src="getAgentAvatar(task.agent_id)"
              :alt="task.agent_id"
              class="w-10 h-10 rounded-lg bg-muted object-cover flex-shrink-0"
            />
            <div class="flex-1 min-w-0">
              <div class="flex items-center justify-between mb-1">
                <p class="text-sm font-medium truncate">{{ task.task_name || task.original_task || t('workbench.tool.untitledTask') }}</p>
                <Badge v-if="task.session_id" variant="outline" class="text-xs flex-shrink-0 ml-2">
                  {{ t('workbench.tool.hasSession') }}
                </Badge>
              </div>
              <p class="text-xs text-muted-foreground truncate mb-2">{{ getAgentName(task.agent_id) }}</p>
              <div class="bg-muted/30 rounded p-2 max-h-[150px] overflow-y-auto custom-scrollbar">
                <pre class="text-xs whitespace-pre-wrap font-mono">{{ task.content }}</pre>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!toolResult" class="flex items-center justify-center p-4 border-t border-border/30 bg-muted/10">
        <Loader2 class="w-5 h-5 animate-spin mr-2 text-primary" />
        <span class="text-sm text-muted-foreground">{{ t('workbench.tool.delegatingTasks') }}</span>
      </div>

      <div v-else-if="toolResult?.is_error" class="flex items-start gap-3 p-4 border-t border-border/30 bg-destructive/5">
        <XCircle class="w-5 h-5 flex-shrink-0 mt-0.5 text-destructive" />
        <div>
          <p class="font-medium text-destructive">{{ t('workbench.tool.delegationFailed') }}</p>
          <p class="text-sm opacity-80 mt-1">{{ delegationError }}</p>
        </div>
      </div>

      <div v-else-if="delegationResult" class="border-t border-border/30 p-4 bg-green-500/5">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center gap-2">
            <CheckCircle class="w-4 h-4 text-green-600" />
            <span class="text-sm font-medium text-green-700">{{ t('workbench.tool.delegationCompleted') }}</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            class="h-6 text-xs gap-1"
            @click="showDelegationResult = !showDelegationResult"
          >
            <Eye v-if="!showDelegationResult" class="w-3.5 h-3.5" />
            <EyeOff v-else class="w-3.5 h-3.5" />
            {{ showDelegationResult ? t('workbench.tool.hideResult') : t('workbench.tool.viewResult') }}
          </Button>
        </div>
        <div v-if="showDelegationResult" class="max-h-[200px] overflow-auto custom-scrollbar bg-background rounded p-2">
          <MarkdownRenderer :content="delegationResult" class="text-xs" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { Loader2, XCircle, ArrowRight, CheckCircle, Eye, EyeOff, User } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import { agentAPI } from '@/api/agent.js'
import { useLanguage } from '@/utils/i18n'

const { t } = useLanguage()
const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null },
  item: { type: Object, default: null }
})

const showDelegationResult = ref(false)
const delegateTasks = computed(() => props.toolArgs.tasks || [])
const delegationError = computed(() => {
  if (!props.toolResult?.is_error) return ''
  return typeof props.toolResult.content === 'string' ? props.toolResult.content : JSON.stringify(props.toolResult.content)
})
const delegationResult = computed(() => {
  if (!props.toolResult || props.toolResult.is_error) return null
  return typeof props.toolResult.content === 'string' ? props.toolResult.content : JSON.stringify(props.toolResult.content, null, 2)
})
const generateAvatarUrl = (agentId) => agentId ? `https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=${encodeURIComponent(agentId)}` : ''
const agentList = ref([])
const getAgentNameById = (agentIdOrName) => {
  if (!agentIdOrName) return t('workbench.tool.unknownAgent')
  let agent = agentList.value.find(a => a.id === agentIdOrName)
  if (!agent) agent = agentList.value.find(a => a.name === agentIdOrName)
  return agent?.name || agentIdOrName
}
const getAgentAvatarUrl = (agentIdOrName) => {
  if (!agentIdOrName) return ''
  let agent = agentList.value.find(a => a.id === agentIdOrName)
  if (!agent) agent = agentList.value.find(a => a.name === agentIdOrName)
  if (agent?.avatar_url) return agent.avatar_url
  return generateAvatarUrl(agentIdOrName)
}
const loadAgentList = async () => {
  if (agentList.value.length) return
  try {
    agentList.value = await agentAPI.getAgents() || []
  } catch {
    agentList.value = []
  }
}
const currentAgentId = computed(() => props.item?.agent_id || props.item?.data?.agent_id || props.item?.data?.source_agent_id || '')
const currentAgentName = computed(() => props.item?.agent_name || props.item?.data?.agent_name || props.item?.data?.source_agent_name || props.item?.role || t('workbench.tool.delegator'))
const currentAgentAvatar = computed(() => getAgentAvatarUrl(currentAgentId.value || currentAgentName.value || 'current'))
const getAgentAvatar = (agentId) => getAgentAvatarUrl(agentId)
const getAgentName = (agentId) => getAgentNameById(agentId)

onMounted(() => {
  loadAgentList()
})
</script>
