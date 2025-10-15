import { useState, useCallback } from 'react';

export const useSession = (agents) => {
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [config, setConfig] = useState({
    deepThinking: true,
    multiAgent: true,
    moreSuggest: false,
    maxLoopCount: 10
  });
  const [userConfigOverrides, setUserConfigOverrides] = useState({});

  // 创建新会话
  const createSession = useCallback(() => {
    const sessionId = `session_${Date.now()}`;
    setCurrentSessionId(sessionId);
    return sessionId;
  }, []);

  // 清空会话
  const clearSession = useCallback(() => {
    setCurrentSessionId(null);
  }, []);

  // 更新配置
  const updateConfig = useCallback((newConfig) => {
    console.log('🔧 updateConfig被调用，newConfig:', newConfig);
    setConfig(prev => {
      console.log('🔧 当前config状态(prev):', prev);
      const updatedConfig = { ...prev, ...newConfig };
      console.log('🔧 更新后的config:', updatedConfig);
      return updatedConfig;
    });
    // 记录用户手动修改的配置项，这些配置项将优先于agent配置
    setUserConfigOverrides(prev => {
      const updatedOverrides = { ...prev, ...newConfig };
      console.log('🔧 更新后的userConfigOverrides:', updatedOverrides);
      return updatedOverrides;
    });
  }, []);

  // 设置选中的智能体
  const selectAgent = useCallback((agent, forceConfigUpdate = false) => {
    const isAgentChange = !selectedAgent || selectedAgent.id !== agent?.id;
    setSelectedAgent(agent);
    if (agent && (isAgentChange || forceConfigUpdate)) {
      // 只有在agent真正改变或强制更新时才重新设置配置
      // 配置设置的优先级高于agent配置：用户手动修改的配置项优先，其次是agent配置，最后是默认值
      setConfig({
        deepThinking: userConfigOverrides.deepThinking !== undefined ? userConfigOverrides.deepThinking : agent.deepThinking,
        multiAgent: userConfigOverrides.multiAgent !== undefined ? userConfigOverrides.multiAgent : agent.multiAgent,
        moreSuggest: userConfigOverrides.moreSuggest !== undefined ? userConfigOverrides.moreSuggest : (agent.moreSuggest ?? false),
        maxLoopCount: userConfigOverrides.maxLoopCount !== undefined ? userConfigOverrides.maxLoopCount : (agent.maxLoopCount ?? 10)
      });
      localStorage.setItem('selectedAgentId', agent.id);
    }
  }, [userConfigOverrides, selectedAgent]);

  // 从localStorage恢复选中的智能体
  const restoreSelectedAgent = useCallback((agents) => {
    if (agents && agents.length > 0 && !selectedAgent) {
      const savedAgentId = localStorage.getItem('selectedAgentId');
      if (savedAgentId) {
        const savedAgent = agents.find(agent => agent.id === savedAgentId);
        if (savedAgent) {
          selectAgent(savedAgent);
        } else {
          selectAgent(agents[0]);
        }
      } else {
        selectAgent(agents[0]);
      }
    }
  }, [selectedAgent, selectAgent]);

  return {
    currentSessionId,
    setCurrentSessionId,
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