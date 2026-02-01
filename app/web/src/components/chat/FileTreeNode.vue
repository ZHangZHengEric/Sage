<template>
  <template v-if="isFiles">
    <div 
      v-for="file in node" 
      :key="file" 
      class="flex items-center gap-1.5 p-1 rounded transition-colors hover:bg-accent/50 mb-0.5"
    >
      <File class="w-3 h-3 text-muted-foreground" />
      <span class="flex-1 text-[11px] text-muted-foreground/90 break-all">{{ file.split('/').pop() }}</span>
      <button 
        class="flex items-center justify-center w-5 h-[18px] rounded border border-primary/30 bg-primary/10 hover:bg-primary/20 hover:border-primary/50 hover:-translate-y-px active:translate-y-0 transition-all cursor-pointer"
        @click="$emit('download', file)"
        :title="t('workspace.download')"
      >
        <Download class="w-2.5 h-2.5 text-primary" />
      </button>
    </div>
  </template>
  
  <div v-else class="bg-card/30 border border-border/50 rounded-md overflow-hidden mb-1">
    <div class="flex items-center gap-1.5 p-1.5 bg-card/40 cursor-pointer hover:bg-card/60 transition-colors">
      <Folder class="w-3 h-3 text-muted-foreground" />
      <span class="text-xs font-medium text-muted-foreground/90">{{ name }}</span>
    </div>
    <div class="pl-4 pr-2 pb-2 pt-1">
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
import { File, Folder, Download } from 'lucide-vue-next'
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
