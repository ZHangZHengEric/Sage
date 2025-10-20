<template>
  <div class="workspace-panel">
    <div class="panel-header">
      <h3>{{ t('workspace.title') }}</h3>
      <button 
        class="btn btn-ghost"
        @click="$emit('close')"
      >
        ×
      </button>
    </div>
    <div class="workspace-content">
      <div v-if="workspacePath" class="workspace-path">
        <strong>{{ t('workspace.path') }}</strong> {{ workspacePath }}
      </div>
      
      <div class="file-list">
        <div v-if="hasValidFiles">
          <div 
            v-for="(file, index) in workspaceFiles" 
            :key="file.path || index"
            class="file-item"
          >
            <div class="file-info">
              <span class="file-icon">
                {{ getFileIcon(file.name || file.path) }}
              </span>
              <span class="file-name">
                {{ file.name || file.path }}
              </span>
              <span v-if="file.size" class="file-size">
                {{ formatFileSize(file.size) }}
              </span>
            </div>
            
            <div class="file-actions">
              <button 
                class="btn btn-download"
                @click="handleDownload(file.name || file.path)"
                :title="t('workspace.download')"
              >
                ↓
              </button>
            </div>
          </div>
        </div>
        <div v-else class="empty-files">
          <p>{{ t('workspace.noFiles') }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useLanguage } from '../../utils/i18n.js'

const props = defineProps({
  workspaceFiles: {
    type: Array,
    default: () => []
  },
  workspacePath: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['close', 'downloadFile'])

const { t } = useLanguage()

const hasValidFiles = computed(() => {
  return props.workspaceFiles && props.workspaceFiles.length > 0
})

const getFileIcon = (filename) => {
  if (!filename) return '📄'
  
  const ext = filename.split('.').pop()?.toLowerCase()
  
  switch (ext) {
    case 'js':
    case 'jsx':
    case 'ts':
    case 'tsx':
      return '📜'
    case 'vue':
      return '🔧'
    case 'py':
      return '🐍'
    case 'json':
      return '📋'
    case 'md':
      return '📝'
    case 'txt':
      return '📄'
    case 'css':
    case 'scss':
    case 'less':
      return '🎨'
    case 'html':
      return '🌐'
    case 'png':
    case 'jpg':
    case 'jpeg':
    case 'gif':
    case 'svg':
      return '🖼️'
    case 'pdf':
      return '📕'
    case 'zip':
    case 'rar':
    case 'tar':
    case 'gz':
      return '📦'
    default:
      return '📄'
  }
}

const formatFileSize = (bytes) => {
  if (!bytes) return ''
  
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + ' ' + sizes[i]
}

const handleDownload = (filename) => {
  emit('downloadFile', filename)
}
</script>

<style scoped>
/* WorkspacePanel 组件样式 */
.workspace-panel {
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

.workspace-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
}

.workspace-path {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.6);
  padding: 8px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  word-break: break-all;
}

.workspace-path strong {
  color: rgba(255, 255, 255, 0.8);
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.empty-files {
  text-align: center;
  padding: 40px 20px;
  color: rgba(255, 255, 255, 0.5);
}

.empty-files p {
  margin: 0;
  font-size: 14px;
}

.file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  transition: all 0.2s;
}

.file-item:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.15);
}

.file-info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.file-icon {
  font-size: 14px;
  flex-shrink: 0;
}

.file-name {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.8);
  font-weight: 500;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.5);
  flex-shrink: 0;
}

.file-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.btn-download {
  background: none;
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: rgba(255, 255, 255, 0.6);
  font-size: 12px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: all 0.2s;
  min-width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-download:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.3);
  color: rgba(255, 255, 255, 0.9);
}

.btn-download:active {
  transform: translateY(1px);
}
</style>