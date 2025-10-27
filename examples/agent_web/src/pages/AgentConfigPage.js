import React, { useState } from 'react';
import { Plus, Edit, Trash2, Save, X, Bot, Settings, Download, Upload } from 'lucide-react';
import './AgentConfigPage.css';
import { useLanguage } from '../contexts/LanguageContext';
import AgentCreationModal from '../components/AgentCreationModal';

const AgentConfigPage = ({ agents, onAddAgent, onUpdateAgent, onDeleteAgent, onOpenNewAgent, onOpenEditAgent, tools }) => {
  const { t } = useLanguage();
  const [showCreationModal, setShowCreationModal] = useState(false);
  const [loading, setLoading] = useState(false);  // 控制加载状态
  
  const handleDelete = (agent) => {
    if (agent.id === 'default') {
      alert(t('agent.defaultCannotDelete'));
      return;
    }
    
    if (window.confirm(t('agent.deleteConfirm').replace('{name}', agent.name))) {
      onDeleteAgent(agent.id);
    }
  };

  const handleExport = (agent) => {
    // 创建导出的配置对象
    const exportConfig = {
      id: agent.id,
      name: agent.name,
      description: agent.description,
      systemPrefix: agent.systemPrefix,
      deepThinking: agent.deepThinking,
      multiAgent: agent.multiAgent,
      moreSupport: agent.moreSupport,
      maxLoopCount: agent.maxLoopCount,
      llmConfig: agent.llmConfig,
      availableTools: agent.availableTools,
      systemContext: agent.systemContext,
      availableWorkflows: agent.availableWorkflows,
      exportTime: new Date().toISOString(),
      version: '1.0'
    };

    // 创建下载链接
    const dataStr = JSON.stringify(exportConfig, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    
    // 创建下载链接并触发下载
    const link = document.createElement('a');
    link.href = url;
    link.download = `agent_${agent.name}_${new Date().toISOString().split('T')[0]}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    
    // 清理URL对象
    URL.revokeObjectURL(url);
  };

  const handleImport = () => {
    // 创建文件输入元素
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.style.display = 'none';
    
    input.onchange = (event) => {
      const file = event.target.files[0];
      if (!file) return;
      
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const importedConfig = JSON.parse(e.target.result);
          
          // 验证必要字段
          if (!importedConfig.name) {
            alert(t('agent.importMissingName'));
            return;
          }
          
          // 生成新的ID，避免冲突
          const newId = `imported_${Date.now()}`;
          
          // 创建新的Agent配置
          const newAgent = {
            id: newId,
            name: importedConfig.name + t('agent.importSuffix'),
            description: importedConfig.description || '',
            systemPrefix: importedConfig.systemPrefix || '',
            deepThinking: importedConfig.deepThinking || false,
            multiAgent: importedConfig.multiAgent || false,
            moreSupport: importedConfig.moreSupport || false,
            maxLoopCount: importedConfig.maxLoopCount || 10,
            llmConfig: importedConfig.llmConfig || {},
            availableTools: importedConfig.availableTools || [],
            systemContext: importedConfig.systemContext || '',
            availableWorkflows: importedConfig.availableWorkflows || []
          };
          
          // 调用添加Agent的回调
          onAddAgent(newAgent);
          alert(t('agent.importSuccess').replace('{name}', newAgent.name));
          
        } catch (error) {
          alert(t('agent.importError'));
          console.error('Import error:', error);
        }
      };
      
      reader.readAsText(file);
    };
    
    // 添加到DOM并触发点击
    document.body.appendChild(input);
    input.click();
    document.body.removeChild(input);
  };

  const handleCreateAgent = () => {
    setShowCreationModal(true);
  };

  const handleCreationModalClose = () => {
    setShowCreationModal(false);
  };

  const handleBlankConfig = () => {
    setShowCreationModal(false);
    onOpenNewAgent();
  };

  const handleSmartConfig = async (description, selectedTools) => {
    setLoading(true);
    try {
      const startTime = Date.now();
      console.log('🚀 开始智能配置生成，描述:', description, '工具:', selectedTools);
      
      // 创建AbortController用于超时控制
      const controller = new AbortController();
      const timeoutId = setTimeout(() => {
        console.log('⏰ 5分钟超时触发，中止请求');
        controller.abort();
      }, 300000); // 300秒超时（5分钟）

      console.log('📡 发送auto-generate请求...');
      
      const body = { agent_description: description };
      if (selectedTools && selectedTools.length > 0) {
        body.available_tools = selectedTools;
      }

      // 调用后端API生成Agent配置
      const response = await fetch('/api/agent/auto-generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Cache-Control': 'no-cache',
          'Pragma': 'no-cache',
          'Connection': 'keep-alive',
          'Keep-Alive': 'timeout=300, max=1000',
          'Accept': 'application/json',
          'User-Agent': 'AgentDevWeb/1.0'
        },
        body: JSON.stringify(body),
        signal: controller.signal,
        // 明确设置不使用缓存
        cache: 'no-cache',
        // 启用keep-alive连接
        keepalive: true
      });

      clearTimeout(timeoutId);
      const duration = Date.now() - startTime;
      console.log(`📨 收到响应，耗时: ${duration}ms, 状态: ${response.status}`);

      if (!response.ok) {
        const errorText = await response.text();
        console.error('❌ 响应错误:', response.status, errorText);
        throw new Error(`Failed to generate agent configuration: ${response.status} ${errorText}`);
      }

      const result = await response.json();
      console.log('✅ 解析响应成功:', result.success ? '成功' : '失败');
      
      if (!result.success) {
        throw new Error(result.message || 'Failed to generate agent configuration');
      }
      
      // 使用后端返回的agent_config
      const newAgent = {
        ...result.agent_config,
        id: result.agent_config.id || `smart_${Date.now()}`,
      };

      console.log('🎉 智能配置生成完成，总耗时:', Date.now() - startTime, 'ms');
      setShowCreationModal(false);
      // 添加生成的Agent到列表并自动保存
      onAddAgent(newAgent);
      // 不再自动打开编辑界面，Agent已自动保存到列表中
    } catch (error) {
      const duration = Date.now() - startTime;
      console.error('❌ 智能配置生成失败，耗时:', duration, 'ms');
      console.error('❌ 错误详情:', {
        name: error.name,
        message: error.message,
        stack: error.stack
      });
      
      // 处理超时错误
      if (error.name === 'AbortError') {
        throw new Error(`请求超时（耗时${Math.round(duration/1000)}秒），Agent配置生成需要较长时间，请稍后重试`);
      }
      
      // 处理网络错误
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        throw new Error(`网络连接错误（耗时${Math.round(duration/1000)}秒），请检查网络连接后重试`);
      }
      
      throw error; // 重新抛出错误，让AgentCreationModal处理
    } finally {
      // 无论成功还是失败，都要重置 loading 状态
      setLoading(false);
    }
  };

  const handleCreateBlank = () => {
    onOpenEditAgent({
      id: `agent_${Date.now()}`,
      name: 'New Agent',
      description: '',
      system_prompt: '',
      tools: [],
      llm_config: {
        model: 'gpt-4',
        temperature: 0.7,
      },
    });
    setShowCreationModal(false);
  };

  return (
    <div className="agent-config-page">
      <div className="page-header">
        <div className="page-title">
          <h2>{t('agent.title')}</h2>
          <p>{t('agent.subtitle')}</p>
        </div>
        <div className="page-actions">
          <button className="btn btn-ghost" onClick={handleImport}>
            <Upload size={16} />
            {t('agent.import')}
          </button>
          <button className="btn btn-primary" onClick={handleCreateAgent}>
            <Plus size={16} />
            {t('agent.create')}
          </button>
        </div>
      </div>
      
      <div className="agents-grid">
        {agents.map(agent => (
          <div key={agent.id} className="agent-card">
            <div className="agent-header">
              <div className="agent-avatar">
                <Bot size={24} />
              </div>
              <div className="agent-info">
                <h3 className="agent-name">{agent.name}</h3>
                <p className="agent-description">{agent.description}</p>
              </div>
            </div>
            
            <div className="agent-config">
              <div className="config-item">
                <span className="config-label">{t('agent.model')}:</span>
                <span className="config-value">
                  {agent.llmConfig?.model || t('agent.defaultModel')}
                </span>
              </div>
              <div className="config-item">
                <span className="config-label">{t('agent.deepThinking')}:</span>
                <span className={`config-badge ${
                  agent.deepThinking === null ? 'auto' : 
                  agent.deepThinking ? 'enabled' : 'disabled'
                }`}>
                  {agent.deepThinking === null ? t('common.auto') : 
                   agent.deepThinking ? t('agent.enabled') : t('agent.disabled')}
                </span>
              </div>
              <div className="config-item">
                <span className="config-label">{t('agent.multiAgent')}:</span>
                <span className={`config-badge ${
                  agent.multiAgent === null ? 'auto' : 
                  agent.multiAgent ? 'enabled' : 'disabled'
                }`}>
                  {agent.multiAgent === null ? t('common.auto') : 
                   agent.multiAgent ? t('agent.enabled') : t('agent.disabled')}
                </span>
              </div>
              <div className="config-item">
                <span className="config-label">{t('agent.availableTools')}:</span>
                <span className="config-value">
                  {agent.availableTools?.length || 0} {t('agent.toolsCount')}
                </span>
              </div>
            </div>
            
            <div className="agent-actions">
              {agent.id === 'default' ? (
                <button 
                  className="btn btn-ghost"
                  onClick={() => onOpenEditAgent(agent)}
                >
                  <Settings size={16} />
                  {t('agent.view')}
                </button>
              ) : (
                <button 
                  className="btn btn-ghost"
                  onClick={() => onOpenEditAgent(agent)}
                >
                  <Edit size={16} />
                  {t('agent.edit')}
                </button>
              )}
              <button 
                className="btn btn-ghost"
                onClick={() => handleExport(agent)}
                title={t('agent.export')}
              >
                <Download size={16} />
                {t('agent.export')}
              </button>
              {agent.id !== 'default' && (
                <button 
                  className="btn btn-danger"
                  onClick={() => handleDelete(agent)}
                >
                  <Trash2 size={16} />
                  {t('agent.delete')}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Agent创建模态框 */}
      <AgentCreationModal
        isOpen={showCreationModal}
        onClose={handleCreationModalClose}
        onCreateBlank={handleBlankConfig}
        onCreateSmart={handleSmartConfig}
        tools={tools}
        isGenerating={loading}
      />
    </div>
  );
};

export default AgentConfigPage;