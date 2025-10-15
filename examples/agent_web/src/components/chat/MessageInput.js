import React, { useState, useRef, useEffect } from 'react';
import './MessageInput.css';
import { useLanguage } from '../../contexts/LanguageContext';

const MessageInput = ({ onSendMessage, isLoading, onStopGeneration }) => {
  const { t } = useLanguage();
  const [inputValue, setInputValue] = useState('');
  const textareaRef = useRef(null);

  // 自动调整文本区域高度
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [inputValue]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (inputValue.trim() && !isLoading) {
      onSendMessage(inputValue.trim());
      setInputValue('');
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleStop = () => {
    onStopGeneration();
  };

  return (
    <div className="message-input-container">
      <form onSubmit={handleSubmit} className="message-form">
        <div className="input-wrapper">
          <textarea
            ref={textareaRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('messageInput.placeholder')}
            className="message-textarea"
            disabled={isLoading}
            rows={1}
          />
          <div className="button-group">
            {isLoading ? (
              <button
                type="button"
                onClick={handleStop}
                className="stop-button"
                title={t('messageInput.stopTitle')}
              >
                ⏹️ {t('messageInput.stop')}
              </button>
            ) : (
              <button
                type="submit"
                disabled={!inputValue.trim()}
                className="send-button"
                title={t('messageInput.sendTitle')}
              >
                📤 {t('messageInput.send')}
              </button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
};

export default MessageInput;