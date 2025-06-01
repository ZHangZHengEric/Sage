import React, { createContext, useContext, useReducer, ReactNode } from 'react';

// 类型定义
export interface SystemConfig {
  apiKey: string;
  modelName: string;
  baseUrl: string;
  maxTokens: number;
  temperature: number;
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
  status: SystemStatus | null;
  connected: boolean;
  loading: boolean;
  error: string | null;
}

// 动作类型
type SystemAction = 
  | { type: 'SET_CONFIG'; payload: SystemConfig }
  | { type: 'SET_STATUS'; payload: SystemStatus }
  | { type: 'SET_CONNECTED'; payload: boolean }
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string | null }
  | { type: 'RESET_ERROR' };

// 初始状态
const initialState: SystemState = {
  config: {
    apiKey: '',
    modelName: 'deepseek-chat',
    baseUrl: 'https://api.deepseek.com/v1',
    maxTokens: 4096,
    temperature: 0.7,
  },
  status: null,
  connected: false,
  loading: false,
  error: null,
};

// Reducer
const systemReducer = (state: SystemState, action: SystemAction): SystemState => {
  switch (action.type) {
    case 'SET_CONFIG':
      return { ...state, config: action.payload };
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