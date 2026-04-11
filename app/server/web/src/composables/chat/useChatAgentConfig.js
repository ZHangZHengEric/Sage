import { ref, computed } from 'vue'
import { agentAPI } from '@/api/agent.js'
import { isLoggedIn } from '@/utils/auth.js'
import { normalizeAgentMode } from '@/utils/agentMode.js'

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
    maxLoopCount: null,
    availableSubAgentIds: []
  })
  const userConfigOverrides = ref({})

  const selectedAgentId = computed(() => selectedAgent.value?.id)

  const getDefaultAgent = (agentsList) => {
    if (!Array.isArray(agentsList) || agentsList.length === 0) return null
    return agentsList.find(agent => agent.is_default) || agentsList[0]
  }

  const selectAgent = async (agent, forceConfigUpdate = false) => {
    const isAgentChange = !selectedAgent.value || selectedAgent.value.id !== agent?.id

    if (isAgentChange) {
      userConfigOverrides.value = {}
    }

    // 如果有agent且是切换或强制更新，获取完整详情
    if (agent && (isAgentChange || forceConfigUpdate)) {
      try {
        const response = await agentAPI.getAgentDetail(agent.id)
        // API返回格式: {...}
        const agentDetail = response
        // 合并详情数据
        agent = { ...agent, ...agentDetail }
      } catch (error) {
        console.warn('获取Agent详情失败:', error)
        // 继续使用传入的agent数据
      }
    }

    selectedAgent.value = agent
    if (agent && (isAgentChange || forceConfigUpdate)) {
      const agentMode = normalizeAgentMode(agent.agentMode)
      config.value = {
        deepThinking: userConfigOverrides.value.deepThinking !== undefined ? userConfigOverrides.value.deepThinking : agent.deepThinking,
        agentMode: userConfigOverrides.value.agentMode !== undefined ? normalizeAgentMode(userConfigOverrides.value.agentMode) : agentMode,
        moreSuggest: userConfigOverrides.value.moreSuggest !== undefined ? userConfigOverrides.value.moreSuggest : (agent.moreSuggest ?? false),
        maxLoopCount: userConfigOverrides.value.maxLoopCount !== undefined ? userConfigOverrides.value.maxLoopCount : agent.maxLoopCount,
        availableSubAgentIds: userConfigOverrides.value.availableSubAgentIds !== undefined
          ? userConfigOverrides.value.availableSubAgentIds
          : (agent.availableSubAgentIds ?? [])
      }
      localStorage.setItem('selectedAgentId', agent.id)
    }
  }

  const updateConfig = (newConfig) => {
    const normalizedConfig = newConfig.agentMode !== undefined
      ? { ...newConfig, agentMode: normalizeAgentMode(newConfig.agentMode) }
      : newConfig
    const updatedConfig = { ...config.value, ...normalizedConfig }
    config.value = updatedConfig
    const updatedOverrides = { ...userConfigOverrides.value, ...normalizedConfig }
    userConfigOverrides.value = updatedOverrides
  }

  const restoreSelectedAgent = async (agentsList) => {
    if (!agentsList || agentsList.length === 0) return
    if (selectedAgent.value) {
      const currentAgentExists = agentsList.find(agent => agent.id === selectedAgent.value.id)
      if (currentAgentExists) return
    }
    const savedAgentId = localStorage.getItem('selectedAgentId')
    if (savedAgentId) {
      const savedAgent = agentsList.find(agent => agent.id === savedAgentId)
      if (savedAgent) {
        await selectAgent(savedAgent)
        return
      }
    }
    const defaultAgent = getDefaultAgent(agentsList)
    if (defaultAgent) {
      await selectAgent(defaultAgent)
    }
  }

  const loadAgents = async () => {
    if (!isLoggedIn()) {
      agents.value = []
      return
    }
    try {
      const response = await agentAPI.getAgents()
      // 后端返回格式: [...]
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
        await selectAgent(agent)
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
