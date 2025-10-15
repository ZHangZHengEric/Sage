import React from 'react';
import './TaskStatusPanel.css';
import { useLanguage } from '../../contexts/LanguageContext';

const TaskStatusPanel = ({ taskStatus, expandedTasks, onToggleTask, onClose }) => {
  const { t } = useLanguage();
  const hasValidTasks = taskStatus && taskStatus.length > 0;
  
  // 调试：打印任务数据结构
  if (taskStatus && taskStatus.length > 0) {
    console.log('📋 任务数据结构:', taskStatus);
    taskStatus.forEach((task, index) => {
      console.log(`📋 任务${index + 1}数据:`, task);
      if (task.execution_summary) {
        console.log(`📋 任务${index + 1} execution_summary:`, task.execution_summary);
      }
    });
  }

  const renderTaskItem = (task, index) => {
    const isExpanded = expandedTasks.has(task.task_id);
    
    return (
      <div key={task.task_id || index} className="task-item">
        <div 
          className="task-header"
          onClick={() => onToggleTask(task.task_id)}
        >
          <span className="task-toggle">
            {isExpanded ? '▼' : '▶'}
          </span>
          <span className="task-name">{task.task_name || `${t('task.taskName')} ${index + 1}`}</span>
          <span className={`task-status ${task.status}`}>
            {task.status === 'completed' ? '✓' : 
             task.status === 'running' ? '⟳' : 
             task.status === 'failed' ? '✗' : '○'}
          </span>
        </div>
        
        {isExpanded && (
          <div className="task-details">
            {task.description && (
              <div className="task-description">
                <strong>{t('task.description')}</strong> {task.description}
              </div>
            )}
            
            {task.progress !== undefined && (
              <div className="task-progress">
                <strong>{t('task.progress')}</strong> {task.progress}%
                <div className="progress-bar">
                  <div 
                    className="progress-fill" 
                    style={{ width: `${task.progress}%` }}
                  ></div>
                </div>
              </div>
            )}
            
            {task.start_time && (
              <div className="task-time">
                <strong>{t('task.startTime')}</strong> {new Date(task.start_time).toLocaleString()}
              </div>
            )}
            
            {task.end_time && (
              <div className="task-time">
                <strong>{t('task.endTime')}</strong> {new Date(task.end_time).toLocaleString()}
              </div>
            )}
            
            {task.error && (
              <div className="task-error">
                <strong>{t('task.error')}</strong> {task.error}
              </div>
            )}
            
            {task.execution_summary && (
              <div className="task-result">
                {task.execution_summary.result_summary && (
                  <div className="result-summary">
                    <strong>{t('task.result')}</strong>
                    <div>{task.execution_summary.result_summary}</div>
                  </div>
                )}
                {task.execution_summary.result_documents && task.execution_summary.result_documents.length > 0 && (
                  <div className="result-documents">
                    <strong>{t('task.relatedDocs')}</strong>
                    <ul>
                      {task.execution_summary.result_documents.map((doc, docIndex) => (
                        <li key={docIndex}>{doc}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            
            {task.subtasks && task.subtasks.length > 0 && (
              <div className="task-subtasks">
                <strong>{t('task.subtasks')}</strong>
                <div className="subtasks-list">
                  {task.subtasks.map((subtask, subIndex) => 
                    renderTaskItem(subtask, subIndex)
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="task-status-panel">
      <div className="panel-header">
        <h3>{t('task.title')}</h3>
        <button 
          className="btn btn-ghost"
          onClick={onClose}
        >
          ×
        </button>
      </div>
      <div className="task-list">
        {hasValidTasks ? (
          taskStatus.map((task, index) => renderTaskItem(task, index))
        ) : (
          <div className="empty-tasks">
            <p>{t('task.noTasks')}</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default TaskStatusPanel;