export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  displayContent: string;
  timestamp: Date;
  type?: string;
  agentType?: string;
  startTime?: Date;
  endTime?: Date;
  duration?: number;
  toolCalls?: ToolCall[];
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, any>;
  result?: any;
  status: 'running' | 'success' | 'error';
  error?: string;
  duration?: number;
}

export interface MessageGroup {
  userMessage: Message;
  deepThinkMessages: Message[][];
  finalAnswers: Message[];
}

export interface ChatSettings {
  useDeepThink: boolean;
  useMultiAgent: boolean;
} 