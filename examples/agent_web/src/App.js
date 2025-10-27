import React, { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatPage from './pages/ChatPage';
import AgentConfigPage from './pages/AgentConfigPage';
import ToolsPage from './pages/ToolsPage';
import HistoryPage from './pages/HistoryPage';
import AgentEditPanel from './components/AgentEditPanel';
import StorageService from './services/StorageService';
import { LanguageProvider } from './contexts/LanguageContext';
import useStrictModeEffect from './hooks/useStrictModeEffect';
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

  // 使用自定义 Hook 来处理 StrictMode 下的数据加载
  useStrictModeEffect(() => {
    const loadedAgents = StorageService.getAgents();
    const loadedConversations = StorageService.getConversations();
    
    console.log('📊 App.js: 加载的对话数据', {
      conversationsCount: loadedConversations.length,
      conversations: loadedConversations.map(conv => ({
        id: conv.id,
        sessionId: conv.sessionId,
        title: conv.title,
        hasTokenUsage: !!conv.tokenUsage,
        tokenUsage: conv.tokenUsage,
        messagesCount: conv.messages?.length || 0
      }))
    });
    
    // 直接设置状态，避免触发保存逻辑
    console.log('📂 App.js: 直接设置存储数据到状态，不触发保存');
    React.startTransition(() => {
      setAgents(loadedAgents);
      setConversations(loadedConversations);
    });
    
    // 加载工具列表
    loadTools();
  }, [], 'App.js数据加载');

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

  const addConversation = (conversation, fromStorage = false, shouldAccumulate = true) => {
    // 添加调用栈信息来追踪调用来源
    const stack = new Error().stack;
    const caller = stack.split('\n')[2]?.trim() || 'unknown';
    
    console.log('💾 App.js: addConversation 被调用', {
      conversationId: conversation.id,
      sessionId: conversation.sessionId,
      title: conversation.title,
      hasTokenUsage: !!conversation.tokenUsage,
      tokenUsage: conversation.tokenUsage,
      messagesCount: conversation.messages?.length || 0,
      fromStorage: fromStorage,
      shouldAccumulate: shouldAccumulate,
      caller: caller,
      timestamp: new Date().toISOString()
    });
    
    let conversationId = null;
    
    setConversations(prevConversations => {
      // 检查是否已存在相同的对话
      const existingConversation = prevConversations.find(conv => 
        conv.id === conversation.id || conv.sessionId === conversation.sessionId
      );
      
      if (existingConversation) {
        console.log('🔄 App.js: 更新现有对话', {
          existingId: existingConversation.id,
          existingSessionId: existingConversation.sessionId,
          oldTokenUsage: existingConversation.tokenUsage,
          newTokenUsage: conversation.tokenUsage,
          shouldAccumulate: shouldAccumulate
        });
        
        conversationId = existingConversation.id;
        
        // 处理tokenUsage累加
        let finalConversation = { ...conversation };
        if (conversation.tokenUsage) {
          if (shouldAccumulate) {
            const accumulatedTokenUsage = accumulateTokenUsage(existingConversation.tokenUsage, conversation.tokenUsage);
            finalConversation.tokenUsage = accumulatedTokenUsage;
            
            console.log('📊 addConversation中累加tokenUsage', {
              existingTokenUsage: existingConversation.tokenUsage,
              newTokenUsage: conversation.tokenUsage,
              accumulatedTokenUsage: accumulatedTokenUsage
            });
          } else {
            // 直接覆盖，不累加
            finalConversation.tokenUsage = conversation.tokenUsage;
            
            console.log('📊 addConversation中覆盖tokenUsage（不累加）', {
              existingTokenUsage: existingConversation.tokenUsage,
              newTokenUsage: conversation.tokenUsage
            });
          }
        }
        
        const updatedConversation = { ...existingConversation, ...finalConversation, updatedAt: new Date().toISOString() };
        
        // 检查是否真的有变化，避免不必要的状态更新
        const hasChanges = JSON.stringify(existingConversation) !== JSON.stringify(updatedConversation);
        
        if (!hasChanges) {
          console.log('⏭️ App.js: 对话内容无变化，跳过状态更新', {
            conversationId: existingConversation.id
          });
          return prevConversations; // 返回原数组，避免触发重新渲染
        }
        
        const updatedConversations = prevConversations.map(conv => 
          conv.id === existingConversation.id ? updatedConversation : conv
        );
        
        console.log('💾 App.js: 保存更新后的对话到存储', {
          conversationId: updatedConversation.id,
          hasTokenUsage: !!updatedConversation.tokenUsage,
          tokenUsage: updatedConversation.tokenUsage
        });
        
        // 只有非存储数据才保存到本地存储
        if (!fromStorage) {
          console.log('💾 App.js: 保存实时数据到本地存储', { conversationId: conversation.id });
          StorageService.saveConversations(updatedConversations);
        } else {
          console.log('📂 App.js: 跳过存储数据的保存', { conversationId: conversation.id });
        }
        return updatedConversations;
      }
      
      // 创建新对话
      const newConversation = {
        ...conversation,
        id: conversation.id || conversation.sessionId || Date.now().toString(),
        createdAt: conversation.createdAt || new Date().toISOString(),
        updatedAt: conversation.updatedAt || new Date().toISOString()
      };
      
      console.log('✨ App.js: 创建新对话', {
        conversationId: newConversation.id,
        sessionId: newConversation.sessionId,
        hasTokenUsage: !!newConversation.tokenUsage,
        tokenUsage: newConversation.tokenUsage
      });
      
      conversationId = newConversation.id;
      
      const updatedConversations = [newConversation, ...prevConversations];
      
      // 只有非存储数据才保存到本地存储
      if (!fromStorage) {
        StorageService.saveConversations(updatedConversations);
      }
      
      return updatedConversations;
    });
    
    return conversationId;
  };

  // 累加tokenUsage的辅助函数
  const accumulateTokenUsage = (existingTokenUsage, newTokenUsage) => {
    if (!existingTokenUsage) {
      return newTokenUsage;
    }
    
    if (!newTokenUsage) {
      return existingTokenUsage;
    }

    // 累加total_info
    const accumulatedTotalInfo = {
      prompt_tokens: (existingTokenUsage.total_info?.prompt_tokens || 0) + (newTokenUsage.total_info?.prompt_tokens || 0),
      completion_tokens: (existingTokenUsage.total_info?.completion_tokens || 0) + (newTokenUsage.total_info?.completion_tokens || 0),
      total_tokens: (existingTokenUsage.total_info?.total_tokens || 0) + (newTokenUsage.total_info?.total_tokens || 0)
    };

    // 合并per_step_info
    const accumulatedPerStepInfo = [
      ...(existingTokenUsage.per_step_info || []),
      ...(newTokenUsage.per_step_info || [])
    ];

    return {
      total_info: accumulatedTotalInfo,
      per_step_info: accumulatedPerStepInfo
    };
  };

  const updateConversation = (conversationId, updates, shouldAccumulate = true, fromStorage = false) => {
    console.log('🔄 App.updateConversation 被调用', {
        conversationId,
        updates,
        shouldAccumulate,
        fromStorage,
        conversationsCount: conversations.length
      });
    
    setConversations(prevConversations => {
      let hasChanges = false;
      
      const updatedConversations = prevConversations.map(conv => {
        // 通过 id 或 sessionId 查找对话
        const isMatch = conv.id === conversationId || conv.sessionId === conversationId;
        if (isMatch) {
          let finalUpdates = { ...updates };
          
          // 如果更新包含tokenUsage，根据shouldAccumulate决定是累加还是覆盖
          if (updates.tokenUsage) {
            if (shouldAccumulate) {
              const accumulatedTokenUsage = accumulateTokenUsage(conv.tokenUsage, updates.tokenUsage);
              finalUpdates.tokenUsage = accumulatedTokenUsage;
              
              console.log('📊 累加tokenUsage', {
                conversationId: conv.id,
                sessionId: conv.sessionId,
                oldTokenUsage: conv.tokenUsage,
                newTokenUsage: updates.tokenUsage,
                accumulatedTokenUsage: accumulatedTokenUsage
              });
            } else {
              // 直接覆盖，不累加
              finalUpdates.tokenUsage = updates.tokenUsage;
              
              console.log('📊 覆盖tokenUsage（不累加）', {
                conversationId: conv.id,
                sessionId: conv.sessionId,
                oldTokenUsage: conv.tokenUsage,
                newTokenUsage: updates.tokenUsage
              });
            }
          }
          
          const updatedConv = { ...conv, ...finalUpdates, updatedAt: new Date().toISOString() };
          
          // 检查是否真的有变化
          const convHasChanges = JSON.stringify(conv) !== JSON.stringify(updatedConv);
          if (convHasChanges) {
            hasChanges = true;
          }
          
          return updatedConv;
        }
        return conv;
      });
      
      // 如果没有变化，返回原数组避免触发重新渲染
      if (!hasChanges) {
        console.log('⏭️ App.js: updateConversation 无变化，跳过状态更新', {
          conversationId,
          fromStorage
        });
        return prevConversations;
      }
      
      // 只有非存储数据才保存到本地存储
      if (!fromStorage) {
        console.log('💾 App.js: 保存实时数据到本地存储', { conversationId });
        StorageService.saveConversations(updatedConversations);
      } else {
        console.log('📂 App.js: 跳过存储数据的保存', { conversationId });
      }
      
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