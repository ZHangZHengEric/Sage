<template>
  <div class="workbench-item h-full flex flex-col overflow-hidden">
    <!-- 根据类型渲染不同内容 - 占满整个区域 -->
    <div class="workbench-content flex-1 overflow-hidden">
      <!-- 工具调用 -->
      <ToolCallRenderer
        v-if="item.type === 'tool_call'"
        :item="item"
      />

      <!-- 文件预览 -->
      <FileRenderer
        v-else-if="item.type === 'file'"
        :file-path="item.data.filePath"
        :file-name="item.data.fileName"
        :item="item"
      />

      <!-- 默认：显示原始数据 -->
      <DefaultRenderer
        v-else
        :item="item"
      />
    </div>
  </div>
</template>

<script setup>
import FileRenderer from './renderers/FileRenderer.vue'
import ToolCallRenderer from './renderers/ToolCallRenderer.vue'
import DefaultRenderer from './renderers/DefaultRenderer.vue'

const props = defineProps({
  item: {
    type: Object,
    required: true
  }
})
</script>
