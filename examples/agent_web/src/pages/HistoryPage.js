import React, { useState } from 'react';
import { MessageCircle, Search, Trash2, Calendar, User, Bot, Clock, Filter, Share } from 'lucide-react';
import { exportToHTML } from '../utils/htmlExporter';
import './HistoryPage.css';
import { useLanguage } from '../contexts/LanguageContext';

const HistoryPage = ({ conversations, agents, onDeleteConversation, onSelectConversation }) => {
  const { t, language } = useLanguage();
  const [searchTerm, setSearchTerm] = useState('');
  const [filterAgent, setFilterAgent] = useState('all');
  const [sortBy, setSortBy] = useState('date');
  const [selectedConversations, setSelectedConversations] = useState(new Set());
  const [showShareModal, setShowShareModal] = useState(false);
  const [shareConversation, setShareConversation] = useState(null);
  
  const formatDate = (timestamp) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffTime = Math.abs(now - date);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    
    if (diffDays === 1) {
      return t('history.today');
    } else if (diffDays === 2) {
      return t('history.yesterday');
    } else if (diffDays <= 7) {
      return t('history.daysAgo').replace('{days}', diffDays - 1);
    } else {
      const locale = language === 'en-US' ? 'en-US' : 'zh-CN';
      return date.toLocaleDateString(locale, {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      });
    }
  };
  
  const formatTime = (timestamp) => {
    const locale = language === 'en-US' ? 'en-US' : 'zh-CN';
    return new Date(timestamp).toLocaleTimeString(locale, {
      hour: '2-digit',
      minute: '2-digit'
    });
  };
  
  const getConversationPreview = (messages) => {
    if (!messages || messages.length === 0) {
      return t('history.noMessages');
    }
    
    const userMessages = messages.filter(msg => msg.role === 'user');
    if (userMessages.length === 0) {
      return t('history.noUserMessages');
    }
    
    const firstUserMessage = userMessages[0].content;
    return firstUserMessage.length > 100 
      ? firstUserMessage.substring(0, 100) + '...' 
      : firstUserMessage;
  };
  
  const getMessageCount = (messages) => {
    if (!messages) return { user: 0, assistant: 0 };
    
    return messages.reduce((count, msg) => {
      if (msg.role === 'user') count.user++;
      else if (msg.role === 'assistant') count.assistant++;
      return count;
    }, { user: 0, assistant: 0 });
  };
  
  const filteredConversations = conversations
    .filter(conv => {
      const matchesSearch = conv.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
                           getConversationPreview(conv.messages).toLowerCase().includes(searchTerm.toLowerCase());
      const matchesAgent = filterAgent === 'all' || conv.agentId === filterAgent;
      return matchesSearch && matchesAgent;
    })
    .sort((a, b) => {
      switch (sortBy) {
        case 'date':
          return new Date(b.updatedAt) - new Date(a.updatedAt);
        case 'title':
          return a.title.localeCompare(b.title);
        case 'messages':
          return (b.messages?.length || 0) - (a.messages?.length || 0);
        default:
          return 0;
      }
    });
  
  const handleSelectConversation = (convId) => {
    const newSelected = new Set(selectedConversations);
    if (newSelected.has(convId)) {
      newSelected.delete(convId);
    } else {
      newSelected.add(convId);
    }
    setSelectedConversations(newSelected);
  };
  
  const handleDeleteSelected = () => {
    if (window.confirm(t('history.deleteSelectedConfirm').replace('{count}', selectedConversations.size))) {
      selectedConversations.forEach(convId => {
        onDeleteConversation(convId);
      });
      setSelectedConversations(new Set());
    }
  };
  
  const handleDeleteAll = () => {
    if (window.confirm('确定要删除所有对话记录吗？此操作不可恢复。')) {
      conversations.forEach(conv => {
        onDeleteConversation(conv.id);
      });
    }
  };
  
  const getAgentName = (agentId) => {
    const agent = agents.find(a => a.id === agentId);
    return agent ? agent.name : '未知Agent';
  };

  const handleShareConversation = (conversation) => {
    setShareConversation(conversation);
    setShowShareModal(true);
  };

  const formatMessageForExport = (messages) => {
    if (!messages || !Array.isArray(messages)) return [];
    
    return messages.map(message => {
      if (message.role === 'user') {
        return {
          role: 'user',
          content: message.content
        };
      } else if (message.role === 'assistant') {
        if (message.tool_calls && message.tool_calls.length > 0) {
          return {
            role: 'assistant',
            tool_calls: message.tool_calls
          };
        } else if (message.show_content && message.show_content !== '' && message.show_content !== false) {
          return {
            role: 'assistant',
            show_content: message.show_content
          };
        }
      } else if (message.role === 'tool') {
        return {
          role: 'tool',
          name: message.name,
          content: message.content
        };
      }
      return null;
    }).filter(msg => msg !== null);
  };

  const exportToMarkdown = (conversation) => {
    const agentName = getAgentName(conversation.agentId);
    const date = new Date(conversation.updatedAt).toLocaleString('zh-CN');
    
    let markdown = `# ${conversation.title}\n\n`;
    markdown += `**Agent:** ${agentName}\n`;
    markdown += `**时间:** ${date}\n\n`;
    markdown += `---\n\n`;
    
    const visibleMessages = formatMessageForExport(conversation.messages);
    
    visibleMessages.forEach((message, index) => {
      if (message.role === 'user') {
        markdown += `## 用户\n\n${message.content}\n\n`;
      } else if (message.role === 'assistant') {
        if (message.tool_calls) {
          message.tool_calls.forEach(toolCall => {
            const toolName = toolCall.function?.name || '未知工具';
            const toolArgs = toolCall.function?.arguments || '{}';
            markdown += `## 工具调用: ${toolName}\n\n\`\`\`json\n${toolArgs}\n\`\`\`\n\n`;
          });
        } else if (message.show_content) {
          markdown += `## AI助手\n\n${message.show_content}\n\n`;
        }
      } else if (message.role === 'tool') {
        const toolName = message.name || '工具结果';
        markdown += `## 工具结果: ${toolName}\n\n\`\`\`\n${message.content}\n\`\`\`\n\n`;
      }
    });
    
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${conversation.title}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleExportToHTML = () => {
    if (!shareConversation) {
      console.log('❌ shareConversation 为空，退出函数');
      return;
    }
    
    const visibleMessages = formatMessageForExport(shareConversation.messages);
    exportToHTML(shareConversation, visibleMessages);
  };
  
  return (
    <div className="history-page">
      <div className="page-header">
        <div className="page-title">
          <h2>{t('history.title')}</h2>
          <p>{t('history.subtitle')}</p>
        </div>
        
        <div className="history-stats">
          <div className="stat-item">
            <span className="stat-number">{conversations.length}</span>
            <span className="stat-label">{t('history.totalConversations')}</span>
          </div>
          <div className="stat-item">
            <span className="stat-number">
              {conversations.reduce((sum, conv) => sum + (conv.messages?.length || 0), 0)}
            </span>
            <span className="stat-label">{t('history.totalMessages')}</span>
          </div>
        </div>
      </div>
      
      <div className="history-controls">
        <div className="search-filter-row">
          <div className="search-box">
            <Search size={16} className="search-icon" />
            <input
              type="text"
              className="input search-input"
              placeholder={t('history.search')}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          
          <div className="filter-controls">
            <select 
              className="select filter-select"
              value={filterAgent}
              onChange={(e) => setFilterAgent(e.target.value)}
            >
              <option value="all">{t('history.all')}</option>
              {agents.map(agent => (
                <option key={agent.id} value={agent.id}>{agent.name}</option>
              ))}
            </select>
            
            <select 
              className="select sort-select"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
            >
              <option value="date">{t('history.sortByDate')}</option>
              <option value="title">{t('history.sortByTitle')}</option>
              <option value="messages">{t('history.sortByMessages')}</option>
            </select>
            
            {conversations.length > 0 && (
              <button 
                className="btn btn-outline btn-danger"
                onClick={handleDeleteAll}
              >
                <Trash2 size={16} />
                {t('history.clearAll')}
              </button>
            )}
          </div>
        </div>
        
        {selectedConversations.size > 0 && (
          <div className="bulk-actions">
            <span className="selected-count">
              {t('history.selectedCount')} {selectedConversations.size} 个对话
            </span>
            <button 
              className="btn btn-danger"
              onClick={handleDeleteSelected}
            >
              <Trash2 size={16} />
              {t('history.deleteSelected')}
            </button>
          </div>
        )}
        

      </div>
      
      <div className="conversations-container">
        <div className="conversations-list">
        {filteredConversations.map(conversation => {
          const messageCount = getMessageCount(conversation.messages);
          const isSelected = selectedConversations.has(conversation.id);
          
          return (
            <div 
              key={conversation.id} 
              className={`conversation-card ${isSelected ? 'selected' : ''}`}
            >
              <div className="conversation-header">
                <div className="conversation-select">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => handleSelectConversation(conversation.id)}
                    onClick={(e) => e.stopPropagation()}
                  />
                </div>
                
                <div className="conversation-info" onClick={() => onSelectConversation(conversation)}>
                  <div className="conversation-title-row">
                    <h3 className="conversation-title">{conversation.title}</h3>
                    <div className="conversation-meta">
                      <span className="conversation-date">
                        <Calendar size={12} />
                        {formatDate(conversation.updatedAt)}
                      </span>
                      <span className="conversation-time">
                        <Clock size={12} />
                        {formatTime(conversation.updatedAt)}
                      </span>
                    </div>
                  </div>
                  
                  <p className="conversation-preview">
                    {getConversationPreview(conversation.messages)}
                  </p>
                  
                  <div className="conversation-stats">
                    <div className="stat-group">
                      <div className="stat-item-small">
                        <User size={12} />
                        <span>{messageCount.user}</span>
                      </div>
                      <div className="stat-item-small">
                        <Bot size={12} />
                        <span>{messageCount.assistant}</span>
                      </div>
                    </div>
                    
                    <div className="agent-info">
                      <span className="agent-name">{getAgentName(conversation.agentId)}</span>
                    </div>
                  </div>
                </div>
                
                <div className="conversation-actions">
                  <button 
                    className="btn-icon btn-primary"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleShareConversation(conversation);
                    }}
                    title={t('history.share')}
                  >
                    <Share size={16} />
                  </button>
                  <button 
                    className="btn-icon btn-danger"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (window.confirm(t('history.deleteConfirm'))) {
                        onDeleteConversation(conversation.id);
                      }
                    }}
                    title={t('history.delete')}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            </div>
          );
        })}
        </div>
      </div>
      
      {filteredConversations.length === 0 && conversations.length > 0 && (
        <div className="empty-state">
          <Filter size={48} className="empty-icon" />
          <h3>{t('history.noMatchingConversations')}</h3>
          <p>{t('history.noMatchingDesc')}</p>
        </div>
      )}
      
      {conversations.length === 0 && (
        <div className="empty-state">
          <MessageCircle size={48} className="empty-icon" />
          <h3>{t('history.noConversations')}</h3>
          <p>{t('history.noConversationsDesc')}</p>
          <button 
            className="btn btn-primary"
            onClick={() => onSelectConversation(null)}
          >
            {t('history.startNewChat')}
          </button>
        </div>
      )}
      
      {/* 分享模态框 */}
      {showShareModal && shareConversation && (
        <div className="modal-overlay" onClick={() => setShowShareModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{t('history.shareTitle')}</h3>
              <button 
                className="modal-close"
                onClick={() => setShowShareModal(false)}
              >
                ×
              </button>
            </div>
            <div className="modal-body">
              <p>{t('history.exportFormat')}</p>
              <div className="export-options">
                <button 
                  className="btn btn-primary export-btn"
                  onClick={() => {
                    exportToMarkdown(shareConversation);
                    setShowShareModal(false);
                  }}
                >
                  {t('history.exportMarkdown')}
                </button>
                <button 
                  className="btn btn-secondary export-btn"
                  onClick={() => {
                    handleExportToHTML();
                    setShowShareModal(false);
                  }}
                >
                  {t('history.exportHTML')}
                </button>
              </div>
              <div className="export-info">
                <p><strong>{t('history.conversationTitle')}</strong>{shareConversation.title}</p>
                <p><strong>{t('history.messageCount')}</strong>{shareConversation.messages?.filter(msg => 
                  msg.role === 'user' || (msg.role === 'assistant' && msg.show_content && msg.show_content !== '' && msg.show_content !== false)
                ).length || 0} {t('history.visibleMessages')}</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default HistoryPage;