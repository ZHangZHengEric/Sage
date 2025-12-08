<template>
  <template v-if="isFiles">
    <div 
      v-for="file in node" 
      :key="file" 
      class="file-item"
    >
      <span class="file-icon">📄</span>
      <span class="file-name">{{ file.split('/').pop() }}</span>
      <button 
        class="download-btn"
        @click="$emit('download', file)"
        :title="t('workspace.download')"
      >
        ⬇️
      </button>
    </div>
  </template>
  
  <div v-else class="directory-item">
    <div class="directory-header">
      <span class="directory-icon">📁</span>
      <span class="directory-name">{{ name }}</span>
    </div>
    <div class="directory-content">
      <FileTreeNode
        v-if="hasFiles"
        name="_files"
        :node="node._files"
        :path="path"
        @download="$emit('download', $event)"
      />
      <FileTreeNode
        v-for="(value, key) in filteredNode"
        :key="key"
        :name="key"
        :node="value"
        :path="path + '/' + key"
        @download="$emit('download', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useLanguage } from '../../composables/useLanguage'

const props = defineProps({
  name: String,
  node: [Object, Array],
  path: String
})

const emit = defineEmits(['download'])

const { t } = useLanguage()

const isFiles = computed(() => props.name === '_files')

const hasFiles = computed(() => {
  return props.node._files && props.node._files.length > 0
})

const filteredNode = computed(() => {
  if (!props.node || typeof props.node !== 'object') return {}
  
  const filtered = {}
  Object.keys(props.node).forEach(key => {
    if (key !== '_files') {
      filtered[key] = props.node[key]
    }
  })
  return filtered
})
</script>

<style scoped>
.directory-item {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 4px;
}

.directory-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: rgba(255, 255, 255, 0.05);
  cursor: pointer;
  transition: background 0.2s;
}

.directory-header:hover {
  background: rgba(255, 255, 255, 0.08);
}

.directory-icon {
  font-size: 12px;
}

.directory-name {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.8);
  font-weight: 500;
}

.directory-content {
  padding: 4px 8px 8px 16px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 4px;
  transition: background 0.2s;
  margin-bottom: 2px;
}

.file-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.file-icon {
  font-size: 10px;
}

.file-name {
  flex: 1;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.7);
  word-break: break-word;
}

.download-btn {
  background: rgba(102, 126, 234, 0.2);
  border: 1px solid rgba(102, 126, 234, 0.3);
  border-radius: 4px;
  padding: 2px 4px;
  font-size: 10px;
  color: rgba(255, 255, 255, 0.8);
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 18px;
}

.download-btn:hover {
  background: rgba(102, 126, 234, 0.3);
  border-color: rgba(102, 126, 234, 0.5);
  transform: translateY(-1px);
}

.download-btn:active {
  transform: translateY(0);
}
</style>