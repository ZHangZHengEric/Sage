import { useState, useCallback } from 'react';

export const useTaskManager = () => {
  const [taskStatus, setTaskStatus] = useState(null);
  const [workspaceFiles, setWorkspaceFiles] = useState([]);
  const [workspacePath, setWorkspacePath] = useState(null);
  const [expandedTasks, setExpandedTasks] = useState(new Set());
  const [lastMessageId, setLastMessageId] = useState(null);

  // 获取任务状态
  const fetchTaskStatus = useCallback(async (sessionId) => {
    if (!sessionId) return;
    
    console.log('🔄 开始请求任务状态, sessionId:', sessionId);
    
    try {
      const response = await fetch(`/api/sessions/${sessionId}/tasks_status`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });
      
      if (response.ok) {
        const data = await response.json();
        console.log('📊 任务状态响应数据:', data);
        const tasksObj = data.tasks_status?.tasks || {};
        console.log('📊 任务对象:', tasksObj);
        // 将任务对象转换为数组
        const tasks = Object.values(tasksObj);
        console.log('📊 任务数组:', tasks);
        tasks.forEach((task, index) => {
          console.log(`📊 任务${index + 1}详细数据:`, task);
          if (task.execution_summary) {
            console.log(`📊 任务${index + 1} execution_summary:`, task.execution_summary);
          }
        });
        setTaskStatus(tasks);
        console.log('✅ 任务状态请求成功, 任务数量:', tasks.length);
      } else {
        console.error('获取任务状态失败:', response.statusText);
      }
    } catch (error) {
      console.error('获取任务状态出错:', error);
    }
  }, []);

  // 获取工作空间文件
  const fetchWorkspaceFiles = useCallback(async (sessionId) => {
    if (!sessionId) return;
    
    console.log('📁 开始请求工作空间文件, sessionId:', sessionId);
    
    try {
      const response = await fetch(`/api/sessions/${sessionId}/file_workspace`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });
      
      if (response.ok) {
        const data = await response.json();
        console.log('📁 工作空间文件原始数据:', data);
        console.log('📁 工作空间文件数组:', data.files);
        setWorkspaceFiles(data.files || []);
        setWorkspacePath(data.agent_workspace);
        console.log('✅ 工作空间文件请求成功, 文件数量:', data.files?.length || 0);
      } else {
        console.error('获取工作空间文件失败:', response.statusText);
      }
    } catch (error) {
      console.error('获取工作空间文件出错:', error);
    }
  }, []);

  // 下载文件
  const downloadFile = useCallback(async (sessionId, filePath) => {
    if (!sessionId || !filePath || !workspacePath) return;
    
    try {
      const url = `/api/sessions/file_workspace/download?file_path=${encodeURIComponent(filePath)}&workspace_path=${encodeURIComponent(workspacePath)}`;
      const response = await fetch(url);
      
      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = filePath.split('/').pop();
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
      } else {
        console.error('下载文件失败:', response.statusText);
      }
    } catch (error) {
      console.error('下载文件出错:', error);
    }
  }, [workspacePath]);

  // 切换任务展开状态
  const toggleTaskExpanded = useCallback((taskId) => {
    setExpandedTasks(prev => {
      const newSet = new Set(prev);
      if (newSet.has(taskId)) {
        newSet.delete(taskId);
      } else {
        newSet.add(taskId);
      }
      return newSet;
    });
  }, []);

  // 更新任务和工作空间数据
  const updateTaskAndWorkspace = useCallback((sessionId, reason = 'unknown') => {
    if (sessionId) {
      console.log(`🚀 触发任务和工作空间更新, 原因: ${reason}, sessionId:`, sessionId);
      fetchTaskStatus(sessionId);
      fetchWorkspaceFiles(sessionId);
    }
  }, [fetchTaskStatus, fetchWorkspaceFiles]);

  // 清空任务和工作空间数据
  const clearTaskAndWorkspace = useCallback(() => {
    setTaskStatus(null);
    setWorkspaceFiles([]);
    setWorkspacePath(null);
    setExpandedTasks(new Set());
    setLastMessageId(null);
  }, []);

  // 检查是否需要更新任务状态
  const checkForUpdates = useCallback((messages, sessionId, reason = 'message_change') => {
    if (messages.length > 0 && sessionId) {
      const latestMessage = messages[messages.length - 1];
      if (latestMessage.message_id && latestMessage.message_id !== lastMessageId) {
        console.log(`🔍 检测到新消息ID变化: ${lastMessageId} -> ${latestMessage.message_id}`);
        setLastMessageId(latestMessage.message_id);
        updateTaskAndWorkspace(sessionId, reason);
      } else {
        console.log('🔍 消息ID未变化，跳过任务状态更新');
      }
    }
  }, [lastMessageId, updateTaskAndWorkspace]);

  return {
    taskStatus,
    workspaceFiles,
    workspacePath,
    expandedTasks,
    fetchTaskStatus,
    fetchWorkspaceFiles,
    downloadFile,
    toggleTaskExpanded,
    updateTaskAndWorkspace,
    clearTaskAndWorkspace,
    checkForUpdates
  };
};