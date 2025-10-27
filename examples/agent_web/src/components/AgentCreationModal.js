import React, { useState } from 'react';
import { X, Wand2, Bot, Search, FileText, Sparkles, Check, Loader, Plus, Trash2, AlertCircle } from 'lucide-react';
import './AgentCreationModal.css';
import { useLanguage } from '../contexts/LanguageContext';
import ToolSelectorModal from './ToolSelectorModal';

const AgentCreationModal = ({ isOpen, onClose, onCreateBlank, onCreateSmart, tools, isGenerating = false }) => {
  const { t } = useLanguage();
  const [type, setType] = useState(''); // 默认空，等用户选择
  const [description, setDescription] = useState('');
  const [selectedTools, setSelectedTools] = useState([]);
  const [showToolSelector, setShowToolSelector] = useState(false);
  const [error, setError] = useState(''); // 添加错误状态

  const handleTypeSelect = (selectedType) => {
    setType(selectedType);
    setError(''); // 清除错误
    if (selectedType === 'blank') {
      setDescription('');
      setSelectedTools([]);
    }
  };

  const handleCreateBlank = () => {
    onCreateBlank();
    handleClose();
  };

  const handleCreateSmart = async () => {
    if (description.trim()) {
      try {
        setError(''); // 清除之前的错误
        await onCreateSmart(description, selectedTools);
        // 成功后不需要手动关闭，父组件会处理
      } catch (err) {
        // 捕获并显示错误
        setError(err.message || '生成失败，请重试');
      }
    }
  };

  const handleClose = () => {
    setType('');
    setDescription('');
    setSelectedTools([]);
    setError(''); // 清除错误
    onClose();
  };

  const handleToolToggle = (toolName) => {
    setSelectedTools(prev =>
      prev.includes(toolName)
        ? prev.filter(t => t !== toolName)
        : [...prev, toolName]
    );
  };

  const handleRemoveTool = (toolName) => {
    setSelectedTools(prev => prev.filter(t => t !== toolName));
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="agent-creation-modal">
        <div className="modal-header">
          <h3>{t('agentCreation.title')}</h3>
          <button className="close-btn" onClick={handleClose} disabled={isGenerating}>
            <X size={20} />
          </button>
        </div>

        <div className="modal-content">
          {!type && (
            <div className="creation-options">
              <div className="option-card" onClick={() => handleTypeSelect('blank')}>
                <div className="option-icon">
                  <FileText size={32} />
                </div>
                <h4>{t('agentCreation.blankConfig')}</h4>
                <p>{t('agentCreation.blankConfigDesc')}</p>
              </div>

              <div className="option-card" onClick={() => handleTypeSelect('smart')}>
                <div className="option-icon">
                  <Sparkles size={32} />
                </div>
                <h4>{t('agentCreation.smartConfig')}</h4>
                <p>{t('agentCreation.smartConfigDesc')}</p>
              </div>
            </div>
          )}

          {type === 'blank' && (
            <div className="blank-config-section">
              <div className="section-icon">
                <FileText size={24} />
              </div>
              <h4>{t('agentCreation.blankConfig')}</h4>
              <p>确认创建空白配置的Agent？</p>
              <div className="action-buttons">
                <button className="btn btn-ghost" onClick={() => setType('')}>
                  返回
                </button>
                <button className="btn btn-primary" onClick={handleCreateBlank}>
                  <Bot size={16} />
                  创建空白Agent
                </button>
              </div>
            </div>
          )}

          {type === 'smart' && (
            <div className="smart-config-section">
              <div className="smart-config-scroll">
                <div className="section-icon"><Sparkles size={24} /></div>
                <h4>{t('agentCreation.smartConfig')}</h4>
                <p>请描述您希望创建的Agent功能，我们将自动生成配置</p>
              
                <div className="description-input">
                  <label>Agent描述</label>
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder={t('agentCreation.descriptionPlaceholder')}
                    rows={4}
                    disabled={isGenerating}
                  />
                </div>
              
                <div className="tool-selection-section">
                  <label>可用工具 (可选)</label>
                  <p className="tool-selection-desc">选择Agent可以使用的工具，留空则自动选择合适的工具</p>
              
                  <div className="selected-tools-list">
                    {selectedTools.length === 0 ? (
                      <div className="selected-tools-empty">未选择任何工具</div>
                    ) : (
                      selectedTools.map(name => (
                        <div className="selected-tool-tag" key={name}>
                          <span>{name}</span>
                          <button
                            className="remove-tool-btn"
                            onClick={() => handleRemoveTool(name)}
                            disabled={isGenerating}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      ))
                    )}
                  </div>
              
                  <button
                    className="btn btn-ghost add-tool-btn"
                    onClick={() => setShowToolSelector(true)}
                    disabled={isGenerating}
                  >
                    <Plus size={16} />
                    增加工具
                  </button>
                </div>
              
              </div>
              {/* 错误信息显示 */}
              {error && (
                <div className="error-message">
                  <AlertCircle size={16} />
                  <span>{error}</span>
                </div>
              )}
              {/* 按钮区移出滚动容器，永远贴底 */}
              <div className="action-buttons">
                <button className="btn btn-ghost" onClick={() => setType('')} disabled={isGenerating}>
                  返回
                </button>
                <button className="btn btn-primary" onClick={handleCreateSmart} disabled={!description.trim() || isGenerating}>
                  {isGenerating ? (
                    <>
                      <Loader size={16} className="spinning" />
                      {t('agentCreation.generating')}
                    </>
                  ) : (
                    <>
                      <Sparkles size={16} />
                      {t('agentCreation.generate')}
                    </>
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <ToolSelectorModal
        isOpen={showToolSelector}
        onClose={() => setShowToolSelector(false)}
        tools={tools}
        selectedTools={selectedTools}
        onToggle={handleToolToggle}
      />
    </div>
  );
};

export default AgentCreationModal;