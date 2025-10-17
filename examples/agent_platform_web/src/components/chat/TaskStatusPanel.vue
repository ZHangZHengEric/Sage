<template>
  <div class="task-status-panel">
    <div class="panel-header">
      <h3>{{ t('task.title') }}</h3>
      <button 
        class="btn btn-ghost"
        @click="$emit('close')"
      >
        ×
      </button>
    </div>
    <div class="task-list">
      <div v-if="hasValidTasks">
        <div 
          v-for="(task, index) in taskStatus" 
          :key="task.task_id || index"
          class="task-item"
        >
          <div 
            class="task-header"
            @click="$emit('toggleTask', task.task_id)"
          >
            <span class="task-toggle">
              {{ expandedTasks.has(task.task_id) ? '▼' : '▶' }}
            </span>
            <span class="task-name">
              {{ task.task_name || `${t('task.taskName')} ${index + 1}` }}
            </span>
            <span :class="`task-status ${task.status}`">
              {{ getStatusIcon(task.status) }}
            </span>
          </div>
          
          <div v-if="expandedTasks.has(task.task_id)" class="task-details">
            <div v-if="task.description" class="task-description">
              <strong>{{ t('task.description') }}</strong> {{ task.description }}
            </div>
            
            <div v-if="task.progress !== undefined" class="task-progress">
              <strong>{{ t('task.progress') }}</strong> {{ task.progress }}%
              <div class="progress-bar">
                <div 
                  class="progress-fill" 
                  :style="{ width: `${task.progress}%` }"
                ></div>
              </div>
            </div>
            
            <div v-if="task.start_time" class="task-time">
              <strong>{{ t('task.startTime') }}</strong> {{ formatTime(task.start_time) }}
            </div>
            
            <div v-if="task.end_time" class="task-time">
              <strong>{{ t('task.endTime') }}</strong> {{ formatTime(task.end_time) }}
            </div>
            
            <div v-if="task.error" class="task-error">
              <strong>{{ t('task.error') }}</strong> {{ task.error }}
            </div>
            
            <div v-if="task.execution_summary" class="task-result">
              <div v-if="task.execution_summary.result_summary" class="result-summary">
                <strong>{{ t('task.result') }}</strong>
                <div>{{ task.execution_summary.result_summary }}</div>
              </div>
              <div 
                v-if="task.execution_summary.result_documents && task.execution_summary.result_documents.length > 0" 
                class="result-documents"
              >
                <strong>{{ t('task.relatedDocs') }}</strong>
                <ul>
                  <li 
                    v-for="(doc, docIndex) in task.execution_summary.result_documents" 
                    :key="docIndex"
                  >
                    {{ doc }}
                  </li>
                </ul>
              </div>
            </div>
            
            <div v-if="task.subtasks && task.subtasks.length > 0" class="task-subtasks">
              <strong>{{ t('task.subtasks') }}</strong>
              <div class="subtasks-list">
                <TaskStatusPanel
                  :task-status="task.subtasks"
                  :expanded-tasks="expandedTasks"
                  @toggle-task="$emit('toggleTask', $event)"
                  @close="$emit('close')"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="empty-tasks">
        <p>{{ t('task.noTasks') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useLanguage } from '../../utils/language.js'

const props = defineProps({
  taskStatus: {
    type: Array,
    default: () => []
  },
  expandedTasks: {
    type: Set,
    default: () => new Set()
  }
})

const emit = defineEmits(['close', 'toggleTask'])

const { t } = useLanguage()

const hasValidTasks = computed(() => {
  return props.taskStatus && props.taskStatus.length > 0
})

const getStatusIcon = (status) => {
  switch (status) {
    case 'completed': return '✓'
    case 'running': return '⟳'
    case 'failed': return '✗'
    default: return '○'
  }
}

const formatTime = (timeString) => {
  return new Date(timeString).toLocaleString()
}

// 调试：打印任务数据结构
onMounted(() => {
  if (props.taskStatus && props.taskStatus.length > 0) {
    console.log('📋 任务数据结构:', props.taskStatus)
    props.taskStatus.forEach((task, index) => {
      console.log(`📋 任务${index + 1}数据:`, task)
      if (task.execution_summary) {
        console.log(`📋 任务${index + 1} execution_summary:`, task.execution_summary)
      }
    })
  }
})
</script>

<style scoped>
/* TaskStatusPanel 组件样式 */
.task-status-panel {
  width: 35%;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 0;
  padding: 20px 24px;
  backdrop-filter: blur(10px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-left: 1px solid rgba(255, 255, 255, 0.1);
  border-top: none;
  border-right: none;
  border-bottom: none;
}

.panel-header {
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.9);
}

.panel-header .btn {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.6);
  font-size: 18px;
  cursor: pointer;
  padding: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  transition: all 0.2s;
}

.panel-header .btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.9);
}

.empty-tasks {
  text-align: center;
  padding: 40px 20px;
  color: rgba(255, 255, 255, 0.5);
}

.empty-tasks p {
  margin: 0;
  font-size: 14px;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-item {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  overflow: hidden;
  transition: all 0.2s;
}

.task-item:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.15);
}

.task-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}

.task-header:hover {
  background: rgba(255, 255, 255, 0.05);
}

.task-toggle {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.6);
  width: 12px;
  text-align: center;
}

.task-name {
  flex: 1;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.8);
  font-weight: 500;
}

.task-status {
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.task-status.completed {
  background: rgba(34, 197, 94, 0.2);
  color: #22c55e;
}

.task-status.running {
  background: rgba(59, 130, 246, 0.2);
  color: #3b82f6;
  animation: pulse 2s infinite;
}

.task-status.failed {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

.task-status.pending {
  background: rgba(156, 163, 175, 0.2);
  color: #9ca3af;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.task-details {
  padding: 10px;
  background: rgba(0, 0, 0, 0.1);
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.task-description,
.task-time,
.task-error,
.task-result {
  margin-bottom: 8px;
  font-size: 11px;
  line-height: 1.4;
}

.task-description strong,
.task-time strong,
.task-error strong,
.task-result strong {
  color: rgba(255, 255, 255, 0.7);
  font-weight: 600;
}

.task-description {
  color: rgba(255, 255, 255, 0.8);
}

.task-time {
  color: rgba(255, 255, 255, 0.6);
}

.task-error {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
  padding: 6px;
  border-radius: 4px;
  border-left: 3px solid #ef4444;
}

.task-result {
  color: rgba(255, 255, 255, 0.7);
}

.task-result pre {
  background: rgba(0, 0, 0, 0.3);
  padding: 6px;
  border-radius: 4px;
  font-size: 10px;
  margin: 4px 0 0 0;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.task-progress {
  color: rgba(255, 255, 255, 0.7);
}

.progress-bar {
  width: 100%;
  height: 4px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
  margin-top: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #3b82f6;
  transition: width 0.3s ease;
}

.result-summary,
.result-documents {
  margin-bottom: 8px;
}

.result-documents ul {
  margin: 4px 0 0 16px;
  padding: 0;
}

.result-documents li {
  margin-bottom: 2px;
  font-size: 10px;
}

.task-subtasks {
  margin-top: 8px;
}

.subtasks-list {
  margin-top: 4px;
  padding-left: 12px;
  border-left: 1px solid rgba(255, 255, 255, 0.1);
}
</style>