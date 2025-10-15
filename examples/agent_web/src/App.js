import React, { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatPage from './pages/ChatPage';
import AgentConfigPage from './pages/AgentConfigPage';
import ToolsPage from './pages/ToolsPage';
import HistoryPage from './pages/HistoryPage';
import AgentEditPanel from './components/AgentEditPanel';
import StorageService from './services/StorageService';
import { LanguageProvider } from './contexts/LanguageContext';
import './App.css';

function App() {
  const [currentPage, setCurrentPage] = useState('chat');
  const [agents, setAgents] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [tools, setTools] = useState([]);
  const [currentView, setCurrentView] = useState('list'); // 'list' | 'edit'
  const [editingAgent, setEditingAgent] = useState(null);
  const [selectedConversation, setSelectedConversation] = useState(null);
  const chatPageRef = useRef(null);

  useEffect(() => {
    // 加载本地存储的数据
    const loadedAgents = StorageService.getAgents();
    const loadedConversations = StorageService.getConversations();
    
    setAgents(loadedAgents);
    setConversations(loadedConversations);
    
    // 加载工具列表
    loadTools();
  }, []);

  const loadTools = async () => {
    try {
      const response = await fetch('/api/tools');
      if (response.ok) {
        const toolsData = await response.json();
        setTools(toolsData);
      }
    } catch (error) {
      console.error('Failed to load tools:', error);
    }
  };

  const handleOpenNewAgent = () => {
    setEditingAgent(null);
    setCurrentView('edit');
  };

  const handleOpenEditAgent = (agent) => {
    setEditingAgent(agent);
    setCurrentView('edit');
  };

  const handleBackToList = () => {
    setCurrentView('list');
    setEditingAgent(null);
  };

  const addAgent = (agent) => {
    const newAgent = {
      ...agent,
      id: Date.now().toString(),
      createdAt: new Date().toISOString()
    };
    const updatedAgents = [...agents, newAgent];
    setAgents(updatedAgents);
    StorageService.saveAgents(updatedAgents);
    handleBackToList();
  };

  const updateAgent = (agentId, updatedAgent) => {
    const updatedAgents = agents.map(agent => 
      agent.id === agentId ? { ...agent, ...updatedAgent } : agent
    );
    setAgents(updatedAgents);
    StorageService.saveAgents(updatedAgents);
    handleBackToList();
  };

  const deleteAgent = (agentId) => {
    const updatedAgents = agents.filter(agent => agent.id !== agentId);
    setAgents(updatedAgents);
    StorageService.saveAgents(updatedAgents);
  };

  const addConversation = (conversation) => {
    let conversationId = null;
    
    setConversations(prevConversations => {
      // 检查是否已存在相同的对话
      const existingConversation = prevConversations.find(conv => 
        conv.id === conversation.id || conv.sessionId === conversation.sessionId
      );
      
      if (existingConversation) {
        conversationId = existingConversation.id;
        
        const updatedConversations = prevConversations.map(conv => 
          conv.id === existingConversation.id 
            ? { ...conv, ...conversation, updatedAt: new Date().toISOString() }
            : conv
        );
        
        StorageService.saveConversations(updatedConversations);
        return updatedConversations;
      }
      
      // 创建新对话
      const newConversation = {
        ...conversation,
        id: conversation.id || Date.now().toString(),
        createdAt: conversation.createdAt || new Date().toISOString(),
        updatedAt: conversation.updatedAt || new Date().toISOString()
      };
      
      conversationId = newConversation.id;
      
      const updatedConversations = [newConversation, ...prevConversations];
      
      StorageService.saveConversations(updatedConversations);
      
      return updatedConversations;
    });
    
    return conversationId;
  };

  const updateConversation = (conversationId, updates) => {
    setConversations(prevConversations => {
      const updatedConversations = prevConversations.map(conv => 
        conv.id === conversationId 
          ? { ...conv, ...updates, updatedAt: new Date().toISOString() }
          : conv
      );
      
      StorageService.saveConversations(updatedConversations);
      
      return updatedConversations;
    });
  };

  const deleteConversation = (conversationId) => {
    setConversations(prevConversations => {
      const updatedConversations = prevConversations.filter(conv => conv.id !== conversationId);
      StorageService.saveConversations(updatedConversations);
      return updatedConversations;
    });
  };

  const renderPage = () => {
    switch (currentPage) {
      case 'chat':
        return (
          <ChatPage 
            ref={chatPageRef}
            agents={agents}
            onAddConversation={addConversation}
            onUpdateConversation={updateConversation}
            tools={tools}
            selectedConversation={selectedConversation}
            onClearSelectedConversation={() => setSelectedConversation(null)}
          />
        );
      case 'agents':
        return (
          <AgentConfigPage 
            agents={agents}
            onAddAgent={addAgent}
            onUpdateAgent={updateAgent}
            onDeleteAgent={deleteAgent}
            onOpenNewAgent={handleOpenNewAgent}
            onOpenEditAgent={handleOpenEditAgent}
            tools={tools}
          />
        );
      case 'tools':
        return <ToolsPage tools={tools} />;
      case 'history':
        return (
          <HistoryPage 
            conversations={conversations}
            agents={agents}
            onSelectConversation={(conv) => {
              setSelectedConversation(conv);
              setCurrentPage('chat');
            }}
            onDeleteConversation={deleteConversation}
          />
        );
      default:
        return <ChatPage agents={agents} />;
    }
  };

  return (
    <div className="app">
      <Sidebar 
        currentPage={currentPage}
        onPageChange={(page) => {
          setCurrentPage(page);
          setCurrentView('list'); // 切换页面时重置为列表视图
          setEditingAgent(null); // 清除编辑状态
        }}
        conversationCount={conversations.length}
        onNewChat={() => {
          setCurrentPage('chat');
          setCurrentView('list'); // 重置为列表视图
          setEditingAgent(null); // 清除编辑状态
          // 先清空选中的对话，然后调用ChatPage的清空方法
          setSelectedConversation(null);
          // 使用setTimeout确保状态更新完成后再调用startNewConversation
          setTimeout(() => {
            if (chatPageRef.current) {
              chatPageRef.current.startNewConversation();
            }
          }, 0);
        }}
      />
      <main className="main-content">
        {currentView === 'list' ? (
          renderPage()
        ) : (
          <AgentEditPanel
            agent={editingAgent}
            tools={tools}
            onSave={editingAgent ? updateAgent : addAgent}
            onBack={handleBackToList}
          />
        )}
      </main>
    </div>
  );
}

// 包装App组件，使其能够访问语言上下文
const AppWithLanguage = () => (
  <LanguageProvider>
    <App />
  </LanguageProvider>
);

export default AppWithLanguage;