import React, { useState } from 'react';
import { X, Bot, Sparkles, FileText, Loader } from 'lucide-react';
import './AgentCreationModal.css';
import { useLanguage } from '../contexts/LanguageContext';

const AgentCreationModal = ({ isOpen, onClose, onCreateBlank, onCreateSmart }) => {
  const { t } = useLanguage();
  const [selectedType, setSelectedType] = useState('');
  const [description, setDescription] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);

  const handleTypeSelect = (type) => {
    setSelectedType(type);
    if (type === 'blank') {
      setDescription('');
    }
  };

  const handleCreateBlank = () => {
    onCreateBlank();
    handleClose();
  };

  const handleCreateSmart = async () => {
    if (!description.trim()) {
      alert(t('agentCreation.error'));
      return;
    }

    setIsGenerating(true);
    try {
      await onCreateSmart(description.trim());
      handleClose();
    } catch (error) {
      console.error('Smart creation failed:', error);
      alert(t('agentCreation.error'));
    } finally {
      setIsGenerating(false);
    }
  };

  const handleClose = () => {
    setSelectedType('');
    setDescription('');
    setIsGenerating(false);
    onClose();
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
          {!selectedType && (
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

          {selectedType === 'blank' && (
            <div className="blank-config-section">
              <div className="section-icon">
                <FileText size={24} />
              </div>
              <h4>{t('agentCreation.blankConfig')}</h4>
              <p>确认创建空白配置的Agent？</p>
              <div className="action-buttons">
                <button className="btn btn-ghost" onClick={() => setSelectedType('')}>
                  返回
                </button>
                <button className="btn btn-primary" onClick={handleCreateBlank}>
                  <Bot size={16} />
                  创建空白Agent
                </button>
              </div>
            </div>
          )}

          {selectedType === 'smart' && (
            <div className="smart-config-section">
              <div className="section-icon">
                <Sparkles size={24} />
              </div>
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

              <div className="action-buttons">
                <button 
                  className="btn btn-ghost" 
                  onClick={() => setSelectedType('')}
                  disabled={isGenerating}
                >
                  返回
                </button>
                <button 
                  className="btn btn-primary" 
                  onClick={handleCreateSmart}
                  disabled={!description.trim() || isGenerating}
                >
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
    </div>
  );
};

export default AgentCreationModal;