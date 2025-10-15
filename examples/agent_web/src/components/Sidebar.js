import React from 'react';
import { MessageSquare, Settings, Wrench, History, Plus, Globe } from 'lucide-react';
import './Sidebar.css';
import { useLanguage } from '../contexts/LanguageContext';

const Sidebar = ({ currentPage, onPageChange, conversationCount = 0, onNewChat }) => {
  const { t, language, toggleLanguage } = useLanguage();
  
  const menuItems = [
    {
      id: 'chat',
      label: t('sidebar.newChat'),
      icon: MessageSquare,
      badge: null
    },
    {
      id: 'agents',
      label: t('sidebar.agentConfig'),
      icon: Settings,
      badge: null
    },
    {
      id: 'tools',
      label: t('sidebar.tools'),
      icon: Wrench,
      badge: null
    },
    {
      id: 'history',
      label: t('sidebar.history'),
      icon: History,
      badge: conversationCount > 0 ? conversationCount : null
    }
  ];

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <div className="logo">
          <div className="logo-icon">
            <Plus size={24} />
          </div>
          <h1 className="logo-text">Agent Platform</h1>
        </div>
      </div>
      
      <nav className="sidebar-nav">
        {menuItems.map((item) => {
          const Icon = item.icon;
          const isActive = currentPage === item.id;
          
          return (
            <button
              key={item.id}
              className={`nav-item ${isActive ? 'active' : ''}`}
              onClick={() => {
                if (item.id === 'chat' && onNewChat) {
                  onNewChat();
                }
                onPageChange(item.id);
              }}
            >
              <Icon size={20} className="nav-icon" />
              <span className="nav-label">{item.label}</span>
              {item.badge && (
                <span className="nav-badge">{item.badge}</span>
              )}
            </button>
          );
        })}
      </nav>
      
      <div className="sidebar-footer">
        <div className="status-indicator">
          <div className="status-dot"></div>
          <span className="status-text">{t('sidebar.online')}</span>
        </div>
        <button className="language-toggle" onClick={toggleLanguage}>
          <Globe size={16} />
          <span>{language === 'zh-CN' ? '中 / En' : 'En / 中'}</span>
        </button>
      </div>
    </div>
  );
};

export default Sidebar;