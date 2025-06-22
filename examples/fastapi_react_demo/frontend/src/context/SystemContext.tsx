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

// Workflow相关类型定义 - 改为嵌套对象格式
export interface WorkflowStep {
  id: string;
  name: string;
  description: string;
  order: number;
  substeps?: { [key: string]: WorkflowStep }; // 改为嵌套对象格式
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  steps: { [key: string]: WorkflowStep }; // 改为嵌套对象格式
  enabled: boolean;
  category: string; // 分类：如 "研究分析", "代码开发", "文档处理" 等
  tags: string[]; // 标签
  createdAt: string;
  updatedAt: string;
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
  workflowTemplates: WorkflowTemplate[]; // 新增workflow模板
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
  | { type: 'SET_WORKFLOW_TEMPLATES'; payload: WorkflowTemplate[] }
  | { type: 'ADD_WORKFLOW_TEMPLATE'; payload: WorkflowTemplate }
  | { type: 'UPDATE_WORKFLOW_TEMPLATE'; payload: { id: string; updates: Partial<WorkflowTemplate> } }
  | { type: 'DELETE_WORKFLOW_TEMPLATE'; payload: string }
  | { type: 'SET_STATUS'; payload: SystemStatus }
  | { type: 'SET_CONNECTED'; payload: boolean }
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string | null }
  | { type: 'RESET_ERROR' };

// 浏览器存储键名
const STORAGE_KEYS = {
  CONFIG: 'sage_system_config',
  RULE_PREFERENCES: 'sage_rule_preferences',
  WORKFLOW_TEMPLATES: 'sage_workflow_templates', // 新增
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

// 默认工作流模板 - 精简版本，控制在10个步骤以内
const DEFAULT_WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
  {
    id: 'default-research',
    name: '调研报告工作流',
    description: '完整的调研报告撰写流程，适用于市场调研、行业分析、专题研究等报告撰写',
    category: 'research',
    tags: ['调研', '报告', '分析'],
    enabled: false,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    steps: {
      'step1': { 
        id: 'step1', 
        name: '确定调研主题', 
        description: '明确调研的主题和目标', 
        order: 1,
        substeps: {
          'step1-1': { id: 'step1-1', name: '定义核心问题', description: '明确需要调研解决的核心问题', order: 1 },
          'step1-2': { id: 'step1-2', name: '设定调研范围', description: '确定调研的时间、地域、对象范围', order: 2 }
        }
      },
      'step2': { 
        id: 'step2', 
        name: '制定调研方案', 
        description: '设计调研的具体实施方案', 
        order: 2,
        substeps: {
          'step2-1': { id: 'step2-1', name: '确定调研方法', description: '选择问卷、访谈、观察等调研方法', order: 1 },
          'step2-2': { id: 'step2-2', name: '设计调研工具', description: '设计问卷表、访谈提纲等调研工具', order: 2 }
        }
      },
      'step3': { 
        id: 'step3', 
        name: '收集基础资料', 
        description: '收集相关的背景资料和数据', 
        order: 3,
        substeps: {
          'step3-1': { id: 'step3-1', name: '行业背景研究', description: '了解相关行业的基本情况和发展趋势', order: 1 },
          'step3-2': { id: 'step3-2', name: '政策法规梳理', description: '梳理相关的政策法规和标准规范', order: 2 }
        }
      },
      'step4': { 
        id: 'step4', 
        name: '实施调研', 
        description: '执行调研方案收集数据', 
        order: 4,
        substeps: {
          'step4-1': { id: 'step4-1', name: '一手数据采集', description: '通过问卷、访谈等方式收集第一手数据', order: 1 },
          'step4-2': { id: 'step4-2', name: '二手数据整理', description: '收集整理相关的统计数据和研究报告', order: 2 }
        }
      },
      'step5': { id: 'step5', name: '撰写调研报告', description: '分析数据并撰写完整的调研报告', order: 5 }
    }
  },
  {
    id: 'default-development',
    name: '产品开发工作流',
    description: '完整的产品开发流程，包含需求分析、设计、开发、测试、上线等环节',
    category: 'development',
    tags: ['产品', '开发', '项目'],
    enabled: false,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    steps: {
      'step1': { 
        id: 'step1', 
        name: '需求调研', 
        description: '深入了解用户需求和市场需求', 
        order: 1,
        substeps: {
          'step1-1': { id: 'step1-1', name: '用户访谈', description: '与目标用户进行深度访谈', order: 1 },
          'step1-2': { id: 'step1-2', name: '竞品分析', description: '分析竞争对手的产品特点', order: 2 }
        }
      },
      'step2': { 
        id: 'step2', 
        name: '产品设计', 
        description: '设计产品功能和用户体验', 
        order: 2,
        substeps: {
          'step2-1': { id: 'step2-1', name: '功能规划', description: '规划产品的核心功能和特性', order: 1 },
          'step2-2': { id: 'step2-2', name: 'UI/UX设计', description: '设计用户界面和交互体验', order: 2 }
        }
      },
      'step3': { 
        id: 'step3', 
        name: '技术架构', 
        description: '设计技术架构和选择技术栈', 
        order: 3,
        substeps: {
          'step3-1': { id: 'step3-1', name: '系统架构设计', description: '设计系统的整体架构', order: 1 },
          'step3-2': { id: 'step3-2', name: '技术选型', description: '选择合适的技术栈和工具', order: 2 }
        }
      },
      'step4': { 
        id: 'step4', 
        name: '开发实现', 
        description: '编码实现产品功能', 
        order: 4,
        substeps: {
          'step4-1': { id: 'step4-1', name: '前端开发', description: '实现用户界面和交互功能', order: 1 },
          'step4-2': { id: 'step4-2', name: '后端开发', description: '实现业务逻辑和数据处理', order: 2 }
        }
      },
      'step5': { 
        id: 'step5', 
        name: '测试发布', 
        description: '测试产品质量并发布上线', 
        order: 5,
        substeps: {
          'step5-1': { id: 'step5-1', name: '功能测试', description: '测试产品的各项功能是否正常', order: 1 },
          'step5-2': { id: 'step5-2', name: '上线部署', description: '将产品部署到生产环境', order: 2 }
        }
      }
    }
  },
  {
    id: 'default-content',
    name: '内容创作工作流',
    description: '系统化的内容创作流程，适用于文章、视频、课程等各类内容创作',
    category: 'content',
    tags: ['内容', '创作', '写作'],
    enabled: false,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    steps: {
      'step1': { 
        id: 'step1', 
        name: '主题策划', 
        description: '确定内容主题和创作方向', 
        order: 1,
        substeps: {
          'step1-1': { id: 'step1-1', name: '主题选择', description: '选择有价值和吸引力的主题', order: 1 },
          'step1-2': { id: 'step1-2', name: '受众分析', description: '分析目标受众的需求和偏好', order: 2 }
        }
      },
      'step2': { 
        id: 'step2', 
        name: '资料收集', 
        description: '收集创作所需的资料和素材', 
        order: 2,
        substeps: {
          'step2-1': { id: 'step2-1', name: '信息搜集', description: '搜集相关的事实、数据和案例', order: 1 },
          'step2-2': { id: 'step2-2', name: '素材准备', description: '准备图片、音频、视频等素材', order: 2 }
        }
      },
      'step3': { 
        id: 'step3', 
        name: '内容大纲', 
        description: '制定内容的结构和大纲', 
        order: 3,
        substeps: {
          'step3-1': { id: 'step3-1', name: '结构设计', description: '设计内容的逻辑结构和层次', order: 1 },
          'step3-2': { id: 'step3-2', name: '要点梳理', description: '梳理各部分的核心要点', order: 2 }
        }
      },
      'step4': { 
        id: 'step4', 
        name: '内容创作', 
        description: '根据大纲进行具体的内容创作', 
        order: 4,
        substeps: {
          'step4-1': { id: 'step4-1', name: '初稿撰写', description: '按照大纲撰写内容初稿', order: 1 },
          'step4-2': { id: 'step4-2', name: '内容完善', description: '完善内容细节和表达方式', order: 2 }
        }
      },
      'step5': { 
        id: 'step5', 
        name: '审核发布', 
        description: '审核内容质量并进行发布', 
        order: 5,
        substeps: {
          'step5-1': { id: 'step5-1', name: '内容审核', description: '检查内容的准确性和质量', order: 1 },
          'step5-2': { id: 'step5-2', name: '渠道发布', description: '选择合适的渠道进行发布', order: 2 }
        }
      }
    }
  }
];

// 初始化默认工作流模板
const initializeDefaultWorkflows = (existingWorkflows: WorkflowTemplate[]): WorkflowTemplate[] => {
  // 如果没有任何工作流，则返回默认模板
  if (existingWorkflows.length === 0) {
    return DEFAULT_WORKFLOW_TEMPLATES;
  }
  
  // 检查是否存在默认工作流，如果不存在则添加
  const hasDefaultResearch = existingWorkflows.some(w => w.id === 'default-research');
  const hasDefaultDevelopment = existingWorkflows.some(w => w.id === 'default-development');
  
  const result = [...existingWorkflows];
  
  if (!hasDefaultResearch) {
    result.push(DEFAULT_WORKFLOW_TEMPLATES[0]);
  }
  
  if (!hasDefaultDevelopment) {
    result.push(DEFAULT_WORKFLOW_TEMPLATES[1]);
  }
  
  return result;
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
  workflowTemplates: initializeDefaultWorkflows(loadFromStorage(STORAGE_KEYS.WORKFLOW_TEMPLATES, [])), // 初始化默认工作流
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
    case 'SET_WORKFLOW_TEMPLATES':
      saveToStorage(STORAGE_KEYS.WORKFLOW_TEMPLATES, action.payload);
      return { ...state, workflowTemplates: action.payload };
    case 'ADD_WORKFLOW_TEMPLATE':
      const newTemplates = [...state.workflowTemplates, action.payload];
      saveToStorage(STORAGE_KEYS.WORKFLOW_TEMPLATES, newTemplates);
      return { ...state, workflowTemplates: newTemplates };
    case 'UPDATE_WORKFLOW_TEMPLATE':
      const updatedTemplates = state.workflowTemplates.map(template =>
        template.id === action.payload.id ? { ...template, ...action.payload.updates } : template
      );
      saveToStorage(STORAGE_KEYS.WORKFLOW_TEMPLATES, updatedTemplates);
      return { ...state, workflowTemplates: updatedTemplates };
    case 'DELETE_WORKFLOW_TEMPLATE':
      const filteredTemplates = state.workflowTemplates.filter(template => template.id !== action.payload);
      saveToStorage(STORAGE_KEYS.WORKFLOW_TEMPLATES, filteredTemplates);
      return { ...state, workflowTemplates: filteredTemplates };
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