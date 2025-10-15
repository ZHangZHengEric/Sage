import React, { useState, useEffect } from 'react';
import { Save, X, Plus, Search, ChevronDown, ChevronRight, ChevronLeft, Edit, ArrowRight, Zap } from 'lucide-react';
import './AgentEditPanel.css';
import { useLanguage } from '../contexts/LanguageContext';
import ThreeOptionSwitch from './ThreeOptionSwitch';
import WorkflowEditModal from './WorkflowEditModal';

const AgentEditPanel = ({ agent, tools, onSave, onBack }) => {
  const { t } = useLanguage();
  const isReadOnly = agent && agent.id === 'default';
  
  // 调试日志：检查 isReadOnly 状态
  console.log('[DEBUG] AgentEditPanel - agent:', agent);
  console.log('[DEBUG] AgentEditPanel - isReadOnly:', isReadOnly);
  console.log('[DEBUG] AgentEditPanel - agent.id:', agent?.id);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    systemPrefix: 'You are a helpful AI assistant.',
    deepThinking: null,
    multiAgent: null,
    moreSuggest: false,
    maxLoopCount: 10,
    llmConfig: {
      model: '',
      maxTokens: '',
      temperature: ''
    },
    systemContext: {},
    availableWorkflows: {},
    availableTools: ['complete_task'] // complete_task 必须包含
  });
  
  const [systemContextText, setSystemContextText] = useState('{}');
  const [workflowsText, setWorkflowsText] = useState('{}');
  const [systemContextPairs, setSystemContextPairs] = useState([{ key: '', value: '' }]);
  const [workflowPairs, setWorkflowPairs] = useState([{ key: '', steps: [''] }]);
  const [showToolSearch, setShowToolSearch] = useState(false);
  const [toolSearchQuery, setToolSearchQuery] = useState('');
  const [selectedTools, setSelectedTools] = useState([]);
  const [selectAllChecked, setSelectAllChecked] = useState(false);
  const [expandedSections, setExpandedSections] = useState({
    basic: true,
    features: true,
    llm: false,
    tools: true,
    advanced: false
  });
  const [showWorkflowModal, setShowWorkflowModal] = useState(false);
  const [editingWorkflow, setEditingWorkflow] = useState(null);
  const [editingWorkflowIndex, setEditingWorkflowIndex] = useState(-1);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [showOptimizeModal, setShowOptimizeModal] = useState(false);
  const [optimizationGoal, setOptimizationGoal] = useState('');
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [optimizedResult, setOptimizedResult] = useState('');

  useEffect(() => {
    console.log('[DEBUG] useEffect - agent changed:', agent);
    if (agent) {
      // 确保 complete_task 始终在可用工具列表中
      const availableTools = agent.availableTools || [];
      if (!availableTools.includes('complete_task')) {
        availableTools.unshift('complete_task');
      }
      
      setFormData({ ...agent, availableTools });
      setSystemContextText(JSON.stringify(agent.systemContext || {}, null, 2));
      setWorkflowsText(JSON.stringify(agent.availableWorkflows || {}, null, 2));
      
      // 初始化系统上下文键值对
      const contextEntries = Object.entries(agent.systemContext || {});
      const initialSystemContextPairs = contextEntries.length > 0 ? contextEntries.map(([key, value]) => ({ key, value })) : [{ key: '', value: '' }];
      console.log('[DEBUG] useEffect - 初始化系统上下文键值对:', initialSystemContextPairs);
      setSystemContextPairs(initialSystemContextPairs);
      
      // 初始化工作流键值对
      const workflowEntries = Object.entries(agent.availableWorkflows || {});
      const initialWorkflowPairs = workflowEntries.length > 0 ? workflowEntries.map(([key, value]) => ({ 
        key, 
        steps: Array.isArray(value) ? value : (typeof value === 'string' ? value.split(',').map(s => s.trim()).filter(s => s) : [''])
      })) : [{ key: '', steps: [''] }];
      console.log('[DEBUG] useEffect - 初始化工作流键值对:', initialWorkflowPairs);
      setWorkflowPairs(initialWorkflowPairs);
    }
  }, [agent]);

  const toggleSection = (section) => {
    setExpandedSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }));
  };

  const handleToolToggle = (toolName) => {
    if (toolName === 'complete_task') return; // 不允许取消 complete_task
    
    setFormData(prev => ({
      ...prev,
      availableTools: prev.availableTools.includes(toolName)
        ? prev.availableTools.filter(t => t !== toolName)
        : [...prev.availableTools, toolName]
    }));
  };

  const handleAddTool = (toolName) => {
    if (!formData.availableTools.includes(toolName)) {
      setFormData(prev => ({
        ...prev,
        availableTools: [...prev.availableTools, toolName]
      }));
    }
    setShowToolSearch(false);
    setToolSearchQuery('');
  };

  // 系统上下文键值对处理
  const addSystemContextPair = () => {
    console.log('[DEBUG] addSystemContextPair - current pairs:', systemContextPairs);
    setSystemContextPairs([...systemContextPairs, { key: '', value: '' }]);
  };

  const removeSystemContextPair = (index) => {
    console.log('[DEBUG] removeSystemContextPair - index:', index, 'current pairs:', systemContextPairs);
    console.log('[DEBUG] removeSystemContextPair - pairs length:', systemContextPairs.length);
    
    if (systemContextPairs.length > 1) {
      console.log('[DEBUG] removeSystemContextPair - removing pair at index:', index);
      setSystemContextPairs(systemContextPairs.filter((_, i) => i !== index));
    } else {
      console.log('[DEBUG] removeSystemContextPair - removing last pair, resetting to empty pair');
      setSystemContextPairs([{ key: '', value: '' }]);
    }
  };

  const updateSystemContextPair = (index, field, value) => {
    console.log('[DEBUG] updateSystemContextPair - index:', index, 'field:', field, 'value:', value);
    const newPairs = [...systemContextPairs];
    newPairs[index][field] = value;
    setSystemContextPairs(newPairs);
  };

  // 工作流键值对处理
  const addWorkflowPair = () => {
    setWorkflowPairs([...workflowPairs, { key: '', steps: [''] }]);
  };

  const removeWorkflowPair = (index) => {
    console.log('[DEBUG] removeWorkflowPair - index:', index, 'current pairs:', workflowPairs);
    console.log('[DEBUG] removeWorkflowPair - pairs length:', workflowPairs.length);
    
    console.log('[DEBUG] removeWorkflowPair - removing pair at index:', index);
    const newPairs = workflowPairs.filter((_, i) => i !== index);
    
    if (newPairs.length === 0) {
      console.log('[DEBUG] removeWorkflowPair - no pairs left, adding empty pair');
      setWorkflowPairs([{ key: '', steps: [''] }]);
    } else {
      setWorkflowPairs(newPairs);
    }
  };

  const updateWorkflowPair = (index, field, value) => {
    const newPairs = [...workflowPairs];
    newPairs[index][field] = value;
    setWorkflowPairs(newPairs);
  };

  // 工作流步骤处理
  const addWorkflowStep = (workflowIndex) => {
    const newPairs = [...workflowPairs];
    newPairs[workflowIndex].steps.push('');
    setWorkflowPairs(newPairs);
  };

  const removeWorkflowStep = (workflowIndex, stepIndex) => {
    const newPairs = [...workflowPairs];
    if (newPairs[workflowIndex].steps.length > 1) {
      newPairs[workflowIndex].steps.splice(stepIndex, 1);
      setWorkflowPairs(newPairs);
    }
  };

  const updateWorkflowStep = (workflowIndex, stepIndex, value) => {
    const newPairs = [...workflowPairs];
    newPairs[workflowIndex].steps[stepIndex] = value;
    setWorkflowPairs(newPairs);
  };

  // 工作流编辑弹窗相关函数
  const handleCreateWorkflow = () => {
    setEditingWorkflow(null);
    setEditingWorkflowIndex(-1);
    setShowWorkflowModal(true);
  };

  const handleEditWorkflow = (index) => {
    const workflow = workflowPairs[index];
    setEditingWorkflow(workflow);
    setEditingWorkflowIndex(index);
    setShowWorkflowModal(true);
  };

  const handleWorkflowSave = (workflowData) => {
    console.log('[DEBUG] AgentEditPanel handleWorkflowSave - 接收到的数据:', workflowData);
    console.log('[DEBUG] AgentEditPanel handleWorkflowSave - editingWorkflowIndex:', editingWorkflowIndex);
    console.log('[DEBUG] AgentEditPanel handleWorkflowSave - 当前workflowPairs:', workflowPairs);
    
    if (editingWorkflowIndex >= 0) {
      // 编辑现有工作流
      const newPairs = [...workflowPairs];
      newPairs[editingWorkflowIndex] = {
        key: workflowData.key || workflowData.name, // 兼容两种字段名
        steps: workflowData.steps
      };
      console.log('[DEBUG] AgentEditPanel handleWorkflowSave - 编辑后的newPairs:', newPairs);
      setWorkflowPairs(newPairs);
    } else {
      // 创建新工作流
      const newWorkflow = {
        key: workflowData.key || workflowData.name, // 兼容两种字段名
        steps: workflowData.steps
      };
      const newPairs = [...workflowPairs, newWorkflow];
      console.log('[DEBUG] AgentEditPanel handleWorkflowSave - 创建后的newPairs:', newPairs);
      setWorkflowPairs(newPairs);
    }
    setShowWorkflowModal(false);
    setEditingWorkflow(null);
    setEditingWorkflowIndex(-1);
  };

  const handleWorkflowModalClose = () => {
    setShowWorkflowModal(false);
    setEditingWorkflow(null);
    setEditingWorkflowIndex(-1);
  };

  // 优化相关函数
  const handleOptimizeStart = async () => {
    if (!formData.systemPrefix.trim()) {
      alert('请先输入系统提示词');
      return;
    }

    setIsOptimizing(true);
    try {
      const response = await fetch('http://localhost:23232/api/system-prompt/optimize', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          original_prompt: formData.systemPrefix,
          optimization_goal: optimizationGoal.trim() || undefined
        }),
      });

      if (response.ok) {
        const result = await response.json();
        if (result.success) {
          setOptimizedResult(result.optimized_prompt);
          // 不再直接替换，而是显示结果让用户选择
        } else {
          alert(`优化失败: ${result.message || result.error}`);
        }
      } else {
        const error = await response.text();
        alert(`优化失败: ${error}`);
      }
    } catch (error) {
      console.error('优化请求失败:', error);
      alert('优化请求失败，请检查网络连接');
    } finally {
      setIsOptimizing(false);
    }
  };

  const handleOptimizeCancel = () => {
    setShowOptimizeModal(false);
    setOptimizationGoal('');
    setIsOptimizing(false);
    setOptimizedResult('');
  };

  const handleApplyOptimization = () => {
    setFormData(prev => ({ ...prev, systemPrefix: optimizedResult }));
    setShowOptimizeModal(false);
    setOptimizationGoal('');
    setOptimizedResult('');
  };

  const handleResetOptimization = () => {
    setOptimizedResult('');
    setOptimizationGoal('');
  };

  const filteredTools = tools.filter(tool => 
    !formData.availableTools.includes(tool.name) &&
    (tool.name.toLowerCase().includes(toolSearchQuery.toLowerCase()) ||
     tool.description?.toLowerCase().includes(toolSearchQuery.toLowerCase()))
  );

  const handleToolSelect = (tool) => {
    setSelectedTools(prev => {
      if (prev.includes(tool.name)) {
        return prev.filter(name => name !== tool.name);
      } else {
        return [...prev, tool.name];
      }
    });
  };

  const handleSelectAll = () => {
    if (selectAllChecked) {
      setSelectedTools([]);
    } else {
      const allToolNames = filteredTools.map(tool => tool.name);
      setSelectedTools(allToolNames);
    }
    setSelectAllChecked(!selectAllChecked);
  };

  // 更新全选状态
  useEffect(() => {
    const hasAllFilteredTools = filteredTools.length > 0 && 
      filteredTools.every(tool => selectedTools.includes(tool.name));
    setSelectAllChecked(hasAllFilteredTools);
  }, [filteredTools, selectedTools]);

  // 重置选中工具当弹窗关闭时
  useEffect(() => {
    if (!showToolSearch) {
      setSelectedTools([]);
    }
  }, [showToolSearch]);

  const handleSave = async () => {
    console.log('[DEBUG] handleSave - 开始保存');
    console.log('[DEBUG] handleSave - formData:', formData);
    console.log('[DEBUG] handleSave - systemContextPairs:', systemContextPairs);
    console.log('[DEBUG] handleSave - workflowPairs:', workflowPairs);
    
    if (!formData.name.trim()) {
      alert('请输入Agent名称');
      return;
    }
    
    setIsSaving(true);
    setSaveSuccess(false);
    
    try {
      // 从键值对构建系统上下文对象
      const systemContext = {};
      systemContextPairs.forEach(pair => {
        if (pair.key.trim() && pair.value.trim()) {
          systemContext[pair.key.trim()] = pair.value.trim();
        }
      });
      console.log('[DEBUG] handleSave - 从键值对构建的systemContext:', systemContext);
      console.log('[DEBUG] handleSave - systemContextText内容:', systemContextText);
      
      // 检查是否所有键值对都为空（用户想要清空所有数据）
      const hasValidPairs = systemContextPairs.some(pair => pair.key.trim() || pair.value.trim());
      console.log('[DEBUG] handleSave - hasValidPairs:', hasValidPairs);
      
      // 新逻辑：键值对数据完全替换文本框数据
      if (hasValidPairs) {
        console.log('[DEBUG] handleSave - 使用键值对数据，完全替换文本框数据');
        console.log('[DEBUG] handleSave - 最终的systemContext:', systemContext);
        // systemContext 已经从键值对构建完成，不需要与文本框数据合并
      } else {
        console.log('[DEBUG] handleSave - 用户清空了所有键值对，systemContext为空对象');
        // systemContext 保持为空对象 {}
      }
      
      // 从键值对构建工作流对象
      const availableWorkflows = {};
      workflowPairs.forEach(pair => {
        if (pair.key && pair.key.trim() && pair.steps && pair.steps.some(step => step && step.trim())) {
          // 过滤掉空步骤，确保step存在且不为空
          const steps = pair.steps
            .filter(step => step && typeof step === 'string')
            .map(step => step.trim())
            .filter(step => step);
          if (steps.length > 0) {
            availableWorkflows[pair.key.trim()] = steps;
          }
        }
      });
      console.log('[DEBUG] handleSave - 从键值对构建的availableWorkflows:', availableWorkflows);
      console.log('[DEBUG] handleSave - workflowsText内容:', workflowsText);
      
      // 检查是否所有工作流键值对都为空（用户想要清空所有数据）
      console.log('[DEBUG] handleSave - workflowPairs详细检查:', workflowPairs.map((pair, index) => ({
        index,
        key: pair.key,
        keyTrimmed: pair.key && pair.key.trim(),
        steps: pair.steps,
        hasValidSteps: pair.steps && pair.steps.some(step => step && step.trim()),
        stepsDetail: pair.steps && pair.steps.map(step => ({ step, trimmed: step && step.trim() }))
      })));
      
      const hasValidWorkflowPairs = workflowPairs.some(pair => 
        (pair.key && pair.key.trim()) || 
        (pair.steps && pair.steps.some(step => step && step.trim()))
      );
      console.log('[DEBUG] handleSave - hasValidWorkflowPairs:', hasValidWorkflowPairs);
      
      // 新逻辑：键值对数据完全替换文本框数据
      if (hasValidWorkflowPairs) {
        console.log('[DEBUG] handleSave - 使用工作流键值对数据，完全替换文本框数据');
        console.log('[DEBUG] handleSave - 最终的availableWorkflows:', availableWorkflows);
        // availableWorkflows 已经从键值对构建完成，不需要与文本框数据合并
      } else {
        console.log('[DEBUG] handleSave - 用户清空了所有工作流键值对，availableWorkflows为空对象');
        // availableWorkflows 保持为空对象 {}
      }
      
      const agentData = {
        ...formData,
        systemContext,
        availableWorkflows,
        // 确保高级配置字段被正确保存
        deepThinking: formData.deepThinking,
        multiAgent: formData.multiAgent,
        moreSuggest: formData.moreSuggest,
        maxLoopCount: formData.maxLoopCount,
        llmConfig: formData.llmConfig
      };
      
      // 添加调试信息
      console.log('保存前的数据:', {
        systemContextPairs,
        systemContext,
        agentData
      });
      
      if (agent) {
        onSave(agent.id, agentData);
      } else {
        onSave(agentData);
      }
      
      // 显示成功状态
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2000);
      
    } catch (error) {
      console.error('保存失败:', error);
      alert(t('agentEdit.saveError'));
    } finally {
      setIsSaving(false);
    }
  };

  const SectionHeader = ({ title, section, children }) => (
    <div className="section-header" onClick={() => toggleSection(section)}>
      <div className="section-title">
        {expandedSections[section] ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span>{title}</span>
      </div>
      {children}
    </div>
  );

  return (
    <div className="agent-edit-panel">
      <div className="panel-header">
        <div className="breadcrumb">
          <button className="breadcrumb-back" onClick={onBack}>
            <ChevronLeft size={16} />
            {t('agent.title')}
          </button>
          <span className="breadcrumb-separator">/</span>
          <span className="breadcrumb-current">{agent ? (isReadOnly ? t('agentEdit.viewAgent') : t('agentEdit.editAgent')) : t('agentEdit.newAgent')}</span>
        </div>
        <div className="header-actions">
          {!isReadOnly && (
            <button 
              className={`save-btn ${isSaving ? 'saving' : ''} ${saveSuccess ? 'success' : ''}`} 
              onClick={handleSave} 
              disabled={!formData.name.trim() || isSaving}
            >
              {isSaving ? (
                <>
                  <div className="spinner"></div>
                  保存中...
                </>
              ) : saveSuccess ? (
                <>
                  <Save size={20} />
                  已保存
                </>
              ) : (
                <Save size={20} />
              )}
            </button>
          )}
          <button className="close-btn" onClick={onBack}>
            <X size={20} />
          </button>
        </div>
      </div>

      <div className="panel-content">
        <div className="content-layout">
          <div className="left-column">
            {/* 基本信息 - 左侧 */}
            <div className="form-section basic-info-section">
              <div className="section-content">
                <div className="form-group inline-form-group">
                  <label className="form-label">{t('agentEdit.nameRequired')}</label>
                  <input
                    type="text"
                    className="input"
                    value={formData.name}
                    onChange={e => setFormData(prev => ({ ...prev, name: e.target.value }))}
                    placeholder={t('agentEdit.namePlaceholder')}
                    disabled={isReadOnly}
                  />
                </div>
                <div className="form-group inline-form-group">
                  <label className="form-label">{t('agentEdit.description')}</label>
                  <input
                    type="text"
                    className="input"
                    value={formData.description}
                    onChange={e => setFormData(prev => ({ ...prev, description: e.target.value }))}
                    placeholder={t('agentEdit.descriptionPlaceholder')}
                    disabled={isReadOnly}
                  />
                </div>
                <div className="form-group system-prompt-group">
                  <div className="system-prompt-header">
                    <label className="form-label">{t('agentEdit.systemPrompt')}</label>
                    {!isReadOnly && (
                      <button
                        type="button"
                        className="optimize-btn"
                        onClick={() => setShowOptimizeModal(true)}
                        title="优化系统提示词"
                      >
                        <Zap size={16} />
                        优化
                      </button>
                    )}
                  </div>
                  <textarea
                    className="textarea system-prompt-textarea"
                    value={formData.systemPrefix}
                    onChange={e => setFormData(prev => ({ ...prev, systemPrefix: e.target.value }))}
                    disabled={isReadOnly}
                  />
                </div>
              </div>
            </div>
          </div>
          
          <div className="right-column">
            {/* 功能特性 - 右侧 */}
            <div className="form-section">
              <SectionHeader title={t('agentEdit.features')} section="features" />
              {expandedSections.features && (
                <div className="section-content">
                  <div className="switches-grid">
                    <ThreeOptionSwitch
                      value={formData.deepThinking}
                      onChange={(value) => setFormData(prev => ({ ...prev, deepThinking: value }))}
                      disabled={isReadOnly}
                      label={t('agentEdit.deepThinking')}
                      description={t('agentEdit.deepThinkingDesc')}
                    />
                    
                    <ThreeOptionSwitch
                      value={formData.multiAgent}
                      onChange={(value) => setFormData(prev => ({ ...prev, multiAgent: value }))}
                      disabled={isReadOnly}
                      label={t('agentEdit.multiAgent')}
                      description={t('agentEdit.multiAgentDesc')}
                    />
                    
                  </div>
                  
                  <div className="features-bottom-row">
                    <div className="switch-item">
                      <label className="switch">
                        <input
                          type="checkbox"
                          checked={formData.moreSuggest}
                          onChange={e => setFormData(prev => ({ ...prev, moreSuggest: e.target.checked }))}
                          disabled={isReadOnly}
                        />
                        <span className="slider"></span>
                      </label>
                      <span className="switch-label">{t('agentEdit.moreSuggest')}</span>
                    </div>
                    
                    <div className="max-loop-group">
                      <label className="form-label">{t('agentEdit.maxLoopCount')}</label>
                      <input
                        type="number"
                        className="input narrow-input"
                        value={formData.maxLoopCount}
                        onChange={e => setFormData(prev => ({ ...prev, maxLoopCount: parseInt(e.target.value) || 0 }))}
                        min="0"
                        max="100"
                        disabled={isReadOnly}
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* LLM配置 */}
            <div className="form-section">
              <SectionHeader title={t('agentEdit.llmConfig')} section="llm" />
              {expandedSections.llm && (
                <div className="section-content">
                  <div className="inline-form-group">
                    <label className="form-label">{t('agentEdit.model')}</label>
                    <input
                      type="text"
                      className="input"
                      value={formData.model || ''}
                      onChange={e => setFormData(prev => ({ ...prev, model: e.target.value }))}
                      placeholder="请输入模型名称"
                      disabled={isReadOnly}
                    />
                  </div>
                  
                  <div className="inline-form-group">
                    <label className="form-label">API Key</label>
                    <input
                      type="text"
                      className="input"
                      value={formData.llmConfig?.apiKey || ''}
                      onChange={e => setFormData(prev => ({
                        ...prev,
                        llmConfig: { ...prev.llmConfig, apiKey: e.target.value }
                      }))}
                      placeholder="请输入API Key"
                      disabled={isReadOnly}
                    />
                  </div>
                  
                  <div className="inline-form-group">
                    <label className="form-label">Base URL</label>
                    <input
                      type="text"
                      className="input"
                      value={formData.llmConfig?.baseUrl || ''}
                      onChange={e => setFormData(prev => ({
                        ...prev,
                        llmConfig: { ...prev.llmConfig, baseUrl: e.target.value }
                      }))}
                      placeholder="请输入Base URL"
                      disabled={isReadOnly}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* 可用工具 */}
            <div className="form-section">
              <SectionHeader title={t('agentEdit.availableTools')} section="tools" />
              {expandedSections.tools && (
                <div className="section-content">
                  <div className="tools-container">
                    <div className="tools-header">
                      <button
                        className="btn btn-secondary"
                        onClick={() => setShowToolSearch(true)}
                        disabled={isReadOnly}
                      >
                        <Plus size={16} />
                        {t('agentEdit.addTool')}
                      </button>
                    </div>
                    
                    <div className="tools-tags">
                      {formData.availableTools.map((toolName, index) => {
                        const tool = tools.find(t => t.name === toolName);
                        return (
                          <div key={index} className="tool-tag">
                            <span className="tool-tag-name">{tool?.name || toolName}</span>
                            {!isReadOnly && (
                              <button
                                className="tool-tag-remove"
                                onClick={() => {
                                  const newTools = formData.availableTools.filter((_, i) => i !== index);
                                  setFormData(prev => ({ ...prev, availableTools: newTools }));
                                }}
                              >
                                <X size={12} />
                              </button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* 高级配置 */}
            <div className="form-section">
              <SectionHeader title={t('agentEdit.advanced')} section="advanced" />
              {expandedSections.advanced && (
                <div className="section-content">
                  {/* 系统上下文键值对 */}
                  <div className="form-group">
                    <div className="form-label-with-action">
                      <label className="form-label">{t('agentEdit.systemContext')}</label>
                      {!isReadOnly && (
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={addSystemContextPair}
                        >
                          <Plus size={14} />
                          {t('agentEdit.addContextPair')}
                        </button>
                      )}
                    </div>
                    <div className="key-value-pairs">
                      {systemContextPairs.map((pair, index) => (
                        <div key={index} className="key-value-pair">
                          <input
                            type="text"
                            className="input key-input"
                            placeholder={t('agentEdit.key')}
                            value={pair.key}
                            onChange={e => updateSystemContextPair(index, 'key', e.target.value)}
                            disabled={isReadOnly}
                          />
                          <input
                            type="text"
                            className="input value-input"
                            placeholder={t('agentEdit.value')}
                            value={pair.value}
                            onChange={e => updateSystemContextPair(index, 'value', e.target.value)}
                            disabled={isReadOnly}
                          />
                          {(() => {
                            const shouldShowRemoveBtn = !isReadOnly;
                            console.log('[DEBUG] 删除按钮渲染条件 - index:', index, 'isReadOnly:', isReadOnly, 'systemContextPairs.length:', systemContextPairs.length, 'shouldShow:', shouldShowRemoveBtn);
                            return shouldShowRemoveBtn;
                          })() && (
                            <button
                              type="button"
                              className="remove-btn"
                              onClick={() => removeSystemContextPair(index)}
                            >
                              <X size={12} />
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                  
                  {/* 工作流列表 */}
                  <div className="form-group">
                    <div className="form-label-with-action">
                      <label className="form-label">{t('agentEdit.workflows')}</label>
                      {!isReadOnly && (
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={handleCreateWorkflow}
                        >
                          <Plus size={14} />
                          {t('agentEdit.addWorkflow')}
                        </button>
                      )}
                    </div>
                    <div className="workflow-list">
                      {workflowPairs.map((workflow, workflowIndex) => (
                        <div key={workflowIndex} className="workflow-item">
                          <div className="workflow-info">
                            <div className="workflow-name">{workflow.key || t('agentEdit.workflowName')}</div>
                            <div className="workflow-steps-preview">
                              <div className="steps-count">
                                {workflow.steps.filter(step => step.trim()).length} {t('agentEdit.workflowStepsCount')}
                              </div>
                              <div className="steps-flow">
                                {workflow.steps.filter(step => step.trim()).slice(0, 3).map((step, index) => (
                                  <React.Fragment key={index}>
                                    <div className="step-dot">{index + 1}</div>
                                    {index < Math.min(workflow.steps.filter(step => step.trim()).length - 1, 2) && (
                                      <ArrowRight size={12} className="step-connector" />
                                    )}
                                  </React.Fragment>
                                ))}
                                {workflow.steps.filter(step => step.trim()).length > 3 && (
                                  <div className="step-more">...</div>
                                )}
                              </div>
                            </div>
                          </div>
                          <div className="workflow-actions">
                            {!isReadOnly && (
                              <>
                                <button
                                  type="button"
                                  className="btn btn-secondary btn-xs"
                                  onClick={() => handleEditWorkflow(workflowIndex)}
                                  title={t('agentEdit.editWorkflow')}
                                >
                                  <Edit size={12} />
                                </button>
                                {!isReadOnly && (
                                  <button
                                    type="button"
                                    className="remove-btn"
                                    onClick={() => removeWorkflowPair(workflowIndex)}
                                  >
                                    <X size={12} />
                                  </button>
                                )}
                              </>
                            )}
                          </div>
                        </div>
                      ))}
                      {workflowPairs.length === 0 && (
                        <div className="workflow-empty">
                          <p>{t('agentEdit.workflows')} 暂无工作流</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 工具搜索对话框 */}
      {showToolSearch && (
        <div className="tool-search-modal">
          <div className="tool-search-content">
            <div className="tool-search-header">
              <h3>添加工具</h3>
              <button onClick={() => setShowToolSearch(false)}>
                <X size={20} />
              </button>
            </div>
            <div className="tool-search-input">
              <Search size={16} />
              <input
                type="text"
                placeholder="搜索工具名称或描述..."
                value={toolSearchQuery}
                onChange={e => setToolSearchQuery(e.target.value)}
                autoFocus
              />
            </div>
            
            {filteredTools.length > 0 && (
              <div className="tool-search-actions">
                <button 
                  className={`select-all-btn ${selectAllChecked ? 'selected' : ''}`}
                  onClick={handleSelectAll}
                >
                  <input
                    type="checkbox"
                    checked={selectAllChecked}
                    readOnly
                  />
                  <span className="select-all-label">
                    {selectAllChecked ? '取消全选' : `全选 (${filteredTools.length}个工具)`}
                  </span>
                </button>
              </div>
            )}
            
            <div className="tool-table">
              <div className="tool-table-header">
                <div className="header-cell header-select">选择</div>
                <div className="header-cell header-name">工具名称</div>
                <div className="header-cell header-type">类型</div>
                <div className="header-cell header-description">描述</div>
              </div>
              <div className="tool-search-results">
                {filteredTools.map((tool, index) => (
                  <div 
                    key={index} 
                    className={`tool-search-item ${selectedTools.includes(tool.name) ? 'selected' : ''}`}
                    onClick={() => handleToolSelect(tool)}
                  >
                    <div className="tool-cell tool-select">
                      <input
                        type="checkbox"
                        checked={selectedTools.includes(tool.name)}
                        onChange={() => handleToolSelect(tool)}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </div>
                    <div className="tool-cell tool-name">{tool.name}</div>
                    <div className="tool-cell tool-type">{tool.type}</div>
                    <div className="tool-cell tool-description">
                      {tool.description || '暂无描述'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
            
            <div className="tool-search-footer">
              <button 
                className="btn btn-ghost"
                onClick={() => {
                  setSelectedTools([]);
                  setShowToolSearch(false);
                }}
              >
                取消
              </button>
              <button 
                className="btn btn-primary"
                onClick={() => {
                  const newTools = [...new Set([...formData.availableTools, ...selectedTools])];
                  setFormData(prev => ({ ...prev, availableTools: newTools }));
                  setSelectedTools([]);
                  setShowToolSearch(false);
                }}
                disabled={selectedTools.length === 0}
              >
                确认添加 ({selectedTools.length}个工具)
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 优化对话框 */}
      {showOptimizeModal && (
        <div className="modal-overlay">
          <div className="modal-content optimize-modal">
            <div className="modal-header">
              <h3>优化系统提示词</h3>
              <button 
                className="close-btn"
                onClick={handleOptimizeCancel}
                disabled={isOptimizing}
              >
                <X size={20} />
              </button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label className="form-label">
                  优化目标 <span className="optional-text">(可选)</span>
                </label>
                <textarea
                  className="textarea"
                  value={optimizationGoal}
                  onChange={(e) => setOptimizationGoal(e.target.value)}
                  placeholder="例如：提高专业性和准确性，增强工具使用能力..."
                  rows={3}
                  disabled={isOptimizing || optimizedResult}
                />
                <div className="help-text">
                  如果不填写优化目标，系统将进行通用优化
                </div>
              </div>
              
              {/* 优化结果预览区域 */}
              {optimizedResult && (
                <div className="form-group">
                  <label className="form-label">
                    优化结果预览
                    <span className="help-text-inline">（可编辑）</span>
                  </label>
                  <textarea
                    className="textarea optimization-result"
                    value={optimizedResult}
                    onChange={(e) => setOptimizedResult(e.target.value)}
                    rows={8}
                    placeholder="优化结果将显示在这里，您可以直接编辑..."
                  />
                  <div className="help-text">
                    您可以直接编辑优化结果，确认无误后点击"应用优化"按钮
                  </div>
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button 
                className="btn btn-secondary"
                onClick={handleOptimizeCancel}
                disabled={isOptimizing}
              >
                取消
              </button>
              
              {optimizedResult ? (
                <>
                  <button 
                    className="btn btn-ghost"
                    onClick={handleResetOptimization}
                  >
                    重新优化
                  </button>
                  <button 
                    className="btn btn-primary"
                    onClick={handleApplyOptimization}
                  >
                    应用优化
                  </button>
                </>
              ) : (
                <button 
                  className="btn btn-primary"
                  onClick={handleOptimizeStart}
                  disabled={isOptimizing}
                >
                  {isOptimizing ? (
                    <>
                      <div className="loading-spinner"></div>
                      优化中...
                    </>
                  ) : (
                    <>
                      <Zap size={16} />
                      开始优化
                    </>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 工作流编辑弹窗 */}
      <WorkflowEditModal
        isOpen={showWorkflowModal}
        workflow={editingWorkflow}
        onSave={handleWorkflowSave}
        onClose={handleWorkflowModalClose}
      />
    </div>
  );
};

export default AgentEditPanel;