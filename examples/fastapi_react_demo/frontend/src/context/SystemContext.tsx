import React, { createContext, useContext, useReducer, ReactNode, useEffect } from 'react';

// 类型定义
export interface SystemConfig {
  apiKey: string;
  modelName: string;
  baseUrl: string;
  maxTokens: number;
  temperature: number;
}

export interface RulePreference {
  name: string;
  content: string;
  enabled: boolean;
  id: string;
}

export interface SystemStatus {
  status: string;
  agentsCount: number;
  toolsCount: number;
  activeSessions: number;
  version: string;
}

export interface SystemState {
  config: SystemConfig;
  rulePreferences: RulePreference[];
  status: SystemStatus | null;
  connected: boolean;
  loading: boolean;
  error: string | null;
}

// 动作类型
type SystemAction = 
  | { type: 'SET_CONFIG'; payload: SystemConfig }
  | { type: 'SET_RULE_PREFERENCES'; payload: RulePreference[] }
  | { type: 'ADD_RULE_PREFERENCE'; payload: RulePreference }
  | { type: 'UPDATE_RULE_PREFERENCE'; payload: { id: string; updates: Partial<RulePreference> } }
  | { type: 'DELETE_RULE_PREFERENCE'; payload: string }
  | { type: 'SET_STATUS'; payload: SystemStatus }
  | { type: 'SET_CONNECTED'; payload: boolean }
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string | null }
  | { type: 'RESET_ERROR' };

// 浏览器存储键名
const STORAGE_KEYS = {
  CONFIG: 'sage_system_config',
  RULE_PREFERENCES: 'sage_rule_preferences',
};

// 从localStorage加载数据
const loadFromStorage = <T,>(key: string, defaultValue: T): T => {
  try {
    const stored = localStorage.getItem(key);
    return stored ? JSON.parse(stored) : defaultValue;
  } catch {
    return defaultValue;
  }
};

// 保存到localStorage
const saveToStorage = <T,>(key: string, value: T): void => {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    console.error('Failed to save to localStorage:', error);
  }
};

// 初始状态
const initialState: SystemState = {
  config: loadFromStorage(STORAGE_KEYS.CONFIG, {
    apiKey: '',
    modelName: 'deepseek-chat',
    baseUrl: 'https://api.deepseek.com/v1',
    maxTokens: 4096,
    temperature: 0.7,
  }),
  rulePreferences: loadFromStorage(STORAGE_KEYS.RULE_PREFERENCES, []),
  status: null,
  connected: false,
  loading: false,
  error: null,
};

// Reducer
const systemReducer = (state: SystemState, action: SystemAction): SystemState => {
  switch (action.type) {
    case 'SET_CONFIG':
      saveToStorage(STORAGE_KEYS.CONFIG, action.payload);
      return { ...state, config: action.payload };
    case 'SET_RULE_PREFERENCES':
      saveToStorage(STORAGE_KEYS.RULE_PREFERENCES, action.payload);
      return { ...state, rulePreferences: action.payload };
    case 'ADD_RULE_PREFERENCE':
      const newPreferences = [...state.rulePreferences, action.payload];
      saveToStorage(STORAGE_KEYS.RULE_PREFERENCES, newPreferences);
      return { ...state, rulePreferences: newPreferences };
    case 'UPDATE_RULE_PREFERENCE':
      const updatedPreferences = state.rulePreferences.map(pref =>
        pref.id === action.payload.id ? { ...pref, ...action.payload.updates } : pref
      );
      saveToStorage(STORAGE_KEYS.RULE_PREFERENCES, updatedPreferences);
      return { ...state, rulePreferences: updatedPreferences };
    case 'DELETE_RULE_PREFERENCE':
      const filteredPreferences = state.rulePreferences.filter(pref => pref.id !== action.payload);
      saveToStorage(STORAGE_KEYS.RULE_PREFERENCES, filteredPreferences);
      return { ...state, rulePreferences: filteredPreferences };
    case 'SET_STATUS':
      return { ...state, status: action.payload };
    case 'SET_CONNECTED':
      return { ...state, connected: action.payload };
    case 'SET_LOADING':
      return { ...state, loading: action.payload };
    case 'SET_ERROR':
      return { ...state, error: action.payload, loading: false };
    case 'RESET_ERROR':
      return { ...state, error: null };
    default:
      return state;
  }
};

// Context
const SystemContext = createContext<{
  state: SystemState;
  dispatch: React.Dispatch<SystemAction>;
} | undefined>(undefined);

// Provider
export const SystemProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [state, dispatch] = useReducer(systemReducer, initialState);

  return (
    <SystemContext.Provider value={{ state, dispatch }}>
      {children}
    </SystemContext.Provider>
  );
};

// Hook
export const useSystem = () => {
  const context = useContext(SystemContext);
  if (context === undefined) {
    throw new Error('useSystem must be used within a SystemProvider');
  }
  return context;
}; 