<template>
  <div class="workbench-item h-full flex flex-col overflow-hidden">
    <!-- 根据类型渲染不同内容 - 占满整个区域 -->
    <div class="workbench-content flex-1 overflow-hidden">
      <!-- 空值检查 -->
      <div v-if="!item || !item.type" class="h-full flex items-center justify-center text-muted-foreground">
        <p class="text-sm">无效的工作台项</p>
      </div>

      <!-- 工具调用 -->
      <ToolCallRenderer
        v-else-if="item.type === 'tool_call'"
        :item="item"
      />

      <!-- 文件预览 -->
      <FileRenderer
        v-else-if="item.type === 'file'"
        :file-path="item.data?.filePath"
        :file-name="item.data?.fileName"
        :item="item"
      />

      <!-- 代码/命令输出 -->
      <CodeOutputRenderer
        v-else-if="item.type === 'code' || item.type === 'command'"
        :item="item"
      />

      <!-- 图表 -->
      <ChartRenderer
        v-else-if="item.type === 'chart'"
        :item="item"
      />

      <!-- 图片 -->
      <ImageRenderer
        v-else-if="item.type === 'image'"
        :item="item"
      />

      <!-- 表格数据 -->
      <TableRenderer
        v-else-if="item.type === 'table'"
        :item="item"
      />

      <!-- 普通文本/Markdown -->
      <TextRenderer
        v-else-if="item.type === 'text' || item.type === 'markdown'"
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
import CodeOutputRenderer from './renderers/CodeOutputRenderer.vue'
import ChartRenderer from './renderers/ChartRenderer.vue'
import ImageRenderer from './renderers/ImageRenderer.vue'
import TableRenderer from './renderers/TableRenderer.vue'
import TextRenderer from './renderers/TextRenderer.vue'
import DefaultRenderer from './renderers/DefaultRenderer.vue'

const props = defineProps({
  item: {
    type: Object,
    required: true
  }
})
</script>
