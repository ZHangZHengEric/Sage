import { ref, computed } from 'vue'
import { agentAPI } from '@/api/agent.js'
import { isLoggedIn } from '@/utils/auth.js'

export const useChatAgentConfig = ({
  t,
  toast,
  clearMessages,
  createSession
}) => {
  const agents = ref([])
  const selectedAgent = ref(null)
  const config = ref({
    deepThinking: true,
    agentMode: 'simple',
    moreSuggest: false,
    maxLoopCount: 50
  })
  const userConfigOverrides = ref({})

  const selectedAgentId = computed(() => selectedAgent.value?.id)

  const selectAgent = (agent, forceConfigUpdate = false) => {
    const isAgentChange = !selectedAgent.value || selectedAgent.value.id !== agent?.id
    selectedAgent.value = agent
    if (agent && (isAgentChange || forceConfigUpdate)) {
      // 如果后端返回的 agentMode 是 'multi'，自动改为 'simple'
      const agentMode = agent.agentMode === 'multi' ? 'simple' : (agent.agentMode || 'simple')
      config.value = {
        deepThinking: userConfigOverrides.value.deepThinking !== undefined ? userConfigOverrides.value.deepThinking : agent.deepThinking,
        agentMode: userConfigOverrides.value.agentMode !== undefined ? userConfigOverrides.value.agentMode : agentMode,
        moreSuggest: userConfigOverrides.value.moreSuggest !== undefined ? userConfigOverrides.value.moreSuggest : (agent.moreSuggest ?? false),
        maxLoopCount: userConfigOverrides.value.maxLoopCount !== undefined ? userConfigOverrides.value.maxLoopCount : (agent.maxLoopCount ?? 50)
      }
      localStorage.setItem('selectedAgentId', agent.id)
    }
  }

  const updateConfig = (newConfig) => {
    const updatedConfig = { ...config.value, ...newConfig }
    config.value = updatedConfig
    const updatedOverrides = { ...userConfigOverrides.value, ...newConfig }
    userConfigOverrides.value = updatedOverrides
  }

  const restoreSelectedAgent = (agentsList) => {
    if (!agentsList || agentsList.length === 0) return
    if (selectedAgent.value) {
      const currentAgentExists = agentsList.find(agent => agent.id === selectedAgent.value.id)
      if (currentAgentExists) return
    }
    const savedAgentId = localStorage.getItem('selectedAgentId')
    if (savedAgentId) {
      const savedAgent = agentsList.find(agent => agent.id === savedAgentId)
      if (savedAgent) {
        selectAgent(savedAgent)
        return
      }
    }
    if (agentsList[0]) {
      selectAgent(agentsList[0])
    }
  }

  const loadAgents = async () => {
    if (!isLoggedIn()) {
      agents.value = []
      return
    }
    try {
      const response = await agentAPI.getAgents()
      agents.value = response || []
    } catch (error) {
      if (isLoggedIn()) {
        toast.error(t('chat.loadAgentsError'))
      }
    }
  }

  const handleAgentChange = async (agentId) => {
    if (agentId !== selectedAgentId.value) {
      const agent = agents.value.find(a => a.id === agentId)
      if (agent) {
        selectAgent(agent)
        await createSession(agentId)
        clearMessages()
      }
    }
  }

  return {
    agents,
    selectedAgent,
    selectedAgentId,
    config,
    selectAgent,
    updateConfig,
    restoreSelectedAgent,
    loadAgents,
    handleAgentChange
  }
}
