import { ref, watch } from 'vue';

export const useSession = (agents) => {
  const currentSessionId = ref(null);
  const selectedAgent = ref(null);
  const config = ref({
    deepThinking: true,
    multiAgent: true,
    moreSuggest: false,
    maxLoopCount: 10
  });
  const userConfigOverrides = ref({});

  // 创建新会话
  const createSession = () => {
    const sessionId = `session_${Date.now()}`;
    currentSessionId.value = sessionId;
    return sessionId;
  };

  // 清空会话
  const clearSession = () => {
    currentSessionId.value = null;
  };

  // 更新配置
  const updateConfig = (newConfig) => {
    console.log('🔧 updateConfig被调用，newConfig:', newConfig);
    console.log('🔧 当前config状态(prev):', config.value);
    const updatedConfig = { ...config.value, ...newConfig };
    console.log('🔧 更新后的config:', updatedConfig);
    config.value = updatedConfig;
    
    // 记录用户手动修改的配置项，这些配置项将优先于agent配置
    const updatedOverrides = { ...userConfigOverrides.value, ...newConfig };
    console.log('🔧 更新后的userConfigOverrides:', updatedOverrides);
    userConfigOverrides.value = updatedOverrides;
  };

  // 设置选中的智能体
  const selectAgent = (agent, forceConfigUpdate = false) => {
    const isAgentChange = !selectedAgent.value || selectedAgent.value.id !== agent?.id;
    selectedAgent.value = agent;
    if (agent && (isAgentChange || forceConfigUpdate)) {
      // 只有在agent真正改变或强制更新时才重新设置配置
      // 配置设置的优先级高于agent配置：用户手动修改的配置项优先，其次是agent配置，最后是默认值
      config.value = {
        deepThinking: userConfigOverrides.value.deepThinking !== undefined ? userConfigOverrides.value.deepThinking : agent.deepThinking,
        multiAgent: userConfigOverrides.value.multiAgent !== undefined ? userConfigOverrides.value.multiAgent : agent.multiAgent,
        moreSuggest: userConfigOverrides.value.moreSuggest !== undefined ? userConfigOverrides.value.moreSuggest : (agent.moreSuggest ?? false),
        maxLoopCount: userConfigOverrides.value.maxLoopCount !== undefined ? userConfigOverrides.value.maxLoopCount : (agent.maxLoopCount ?? 10)
      };
      localStorage.setItem('selectedAgentId', agent.id);
    }
  };

  // 从localStorage恢复选中的智能体
  const restoreSelectedAgent = (agentsList) => {
    if (agentsList && agentsList.length > 0 && !selectedAgent.value) {
      const savedAgentId = localStorage.getItem('selectedAgentId');
      if (savedAgentId) {
        const savedAgent = agentsList.find(agent => agent.id === savedAgentId);
        if (savedAgent) {
          selectAgent(savedAgent);
        } else {
          selectAgent(agentsList[0]);
        }
      } else {
        selectAgent(agentsList[0]);
      }
    }
  };

  // 监听agents变化，自动恢复选中的智能体
  watch(() => agents, (newAgents) => {
    if (newAgents) {
      restoreSelectedAgent(newAgents);
    }
  }, { immediate: true });

  return {
    currentSessionId,
    selectedAgent,
    config,
    userConfigOverrides,
    createSession,
    clearSession,
    updateConfig,
    selectAgent,
    restoreSelectedAgent
  };
};