export interface ToolCallData {
  id: string;
  toolName: string;
  parameters: Record<string, any>;
  result?: any;
  duration?: number;
  status: 'running' | 'success' | 'error';
  error?: string;
  timestamp: Date;
} 