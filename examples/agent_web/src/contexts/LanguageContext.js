import React, { createContext, useState, useContext, useEffect } from 'react';
import { zhCN, enUS } from '../utils/i18n';

// 创建语言上下文
const LanguageContext = createContext();

// 语言提供者组件
export const LanguageProvider = ({ children }) => {
  // 从本地存储获取语言设置，默认为中文
  const [language, setLanguage] = useState(() => {
    const savedLanguage = localStorage.getItem('language');
    return savedLanguage || 'zh-CN';
  });

  // 获取当前语言的翻译
  const translations = language === 'zh-CN' ? zhCN : enUS;

  // 切换语言的函数
  const toggleLanguage = () => {
    const newLanguage = language === 'zh-CN' ? 'en-US' : 'zh-CN';
    setLanguage(newLanguage);
    localStorage.setItem('language', newLanguage);
  };

  // 翻译函数
  const t = (key) => {
    return translations[key] || key;
  };

  // 当语言变化时保存到本地存储
  useEffect(() => {
    localStorage.setItem('language', language);
  }, [language]);

  return (
    <LanguageContext.Provider value={{ language, toggleLanguage, t }}>
      {children}
    </LanguageContext.Provider>
  );
};

// 自定义钩子，方便组件使用语言上下文
export const useLanguage = () => {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error('useLanguage must be used within a LanguageProvider');
  }
  return context;
};