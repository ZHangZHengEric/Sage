import { useState, useEffect } from 'react';
import { Message, ChatSettings } from '../types/chat';

export interface ChatHistoryItem {
  id: string;
  title: string;
  messages: Message[];
  settings?: ChatSettings; // 保存对话时的设置状态
  createdAt: Date;
  updatedAt: Date;
}

const STORAGE_KEY = 'zavix_chat_history';
const MAX_HISTORY_ITEMS = 50;

export const useChatHistory = () => {
  const [history, setHistory] = useState<ChatHistoryItem[]>([]);

  // 从 localStorage 加载历史记录
  useEffect(() => {
    try {
      const savedHistory = localStorage.getItem(STORAGE_KEY);
      if (savedHistory) {
        const parsed = JSON.parse(savedHistory);
        // 恢复 Date 对象和完整的Message结构
        const restoredHistory = parsed.map((item: any) => ({
          ...item,
          createdAt: new Date(item.createdAt),
          updatedAt: new Date(item.updatedAt),
          messages: item.messages.map((msg: any) => ({
            ...msg,
            timestamp: new Date(msg.timestamp),
            startTime: msg.startTime ? new Date(msg.startTime) : undefined,
            endTime: msg.endTime ? new Date(msg.endTime) : undefined
          }))
        }));
        setHistory(restoredHistory);
      }
    } catch (error) {
      console.error('加载对话历史失败:', error);
      setHistory([]);
    }
  }, []);

  // 保存历史记录到 localStorage
  const saveToStorage = (newHistory: ChatHistoryItem[]) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(newHistory));
    } catch (error) {
      console.error('保存对话历史失败:', error);
    }
  };

  // 生成对话标题（取第一条用户消息的前20个字符）
  const generateTitle = (messages: ChatHistoryItem['messages']): string => {
    const firstUserMessage = messages.find(msg => msg.role === 'user');
    if (firstUserMessage) {
      // 只使用displayContent，绝不使用content
      const content = firstUserMessage.displayContent;
      return content.length > 20 ? content.substring(0, 20) + '...' : content;
    }
    return '新对话';
  };

  // 添加或更新对话
  const saveChat = (
    chatId: string,
    messages: ChatHistoryItem['messages'],
    settings?: ChatSettings,
    title?: string
  ): void => {
    if (messages.length === 0) return;

    const now = new Date();
    const chatTitle = title || generateTitle(messages);

    setHistory(prevHistory => {
      const existingIndex = prevHistory.findIndex(item => item.id === chatId);
      let newHistory: ChatHistoryItem[];

      if (existingIndex >= 0) {
        // 更新现有对话
        newHistory = [...prevHistory];
        newHistory[existingIndex] = {
          ...newHistory[existingIndex],
          title: chatTitle,
          messages: [...messages],
          settings: settings || newHistory[existingIndex].settings,
          updatedAt: now
        };
      } else {
        // 添加新对话
        const newItem: ChatHistoryItem = {
          id: chatId,
          title: chatTitle,
          messages: [...messages],
          settings: settings,
          createdAt: now,
          updatedAt: now
        };
        newHistory = [newItem, ...prevHistory];
      }

      // 限制历史记录数量
      if (newHistory.length > MAX_HISTORY_ITEMS) {
        newHistory = newHistory.slice(0, MAX_HISTORY_ITEMS);
      }

      // 按更新时间排序
      newHistory.sort((a, b) => b.updatedAt.getTime() - a.updatedAt.getTime());

      saveToStorage(newHistory);
      return newHistory;
    });
  };

  // 删除单个对话
  const deleteChat = (chatId: string): void => {
    setHistory(prevHistory => {
      const newHistory = prevHistory.filter(item => item.id !== chatId);
      saveToStorage(newHistory);
      return newHistory;
    });
  };

  // 清空所有历史记录
  const clearHistory = (): void => {
    setHistory([]);
    localStorage.removeItem(STORAGE_KEY);
  };

  // 获取对话
  const getChat = (chatId: string): ChatHistoryItem | undefined => {
    return history.find(item => item.id === chatId);
  };

  return {
    history,
    saveChat,
    deleteChat,
    clearHistory,
    getChat
  };
}; 