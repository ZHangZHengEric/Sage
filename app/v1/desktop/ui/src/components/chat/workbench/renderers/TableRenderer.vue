<template>
  <div class="table-renderer h-full flex flex-col overflow-hidden">
    <!-- 整合头部 -->
    <div class="flex items-center justify-between px-3 py-2.5 bg-muted/30 border-b border-border flex-none h-12">
      <div class="flex items-center gap-2 min-w-0">
        <span class="font-medium text-sm" :class="roleColor">{{ roleLabel }}</span>
        <span class="text-muted-foreground/50">|</span>
        <span class="text-sm text-muted-foreground">{{ formatTime(item?.timestamp) }}</span>
        <span class="text-muted-foreground/50">|</span>
        <span class="text-xl">📋</span>
        <span class="text-sm font-medium">数据表格</span>
        <Badge variant="secondary" class="text-xs">{{ rowCount }} 行</Badge>
      </div>
    </div>

    <!-- 表格内容 -->
    <div class="flex-1 overflow-auto p-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead
              v-for="column in columns"
              :key="column.key"
              class="font-semibold"
            >
              {{ column.title || column.key }}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="(row, index) in data" :key="index">
            <TableCell
              v-for="column in columns"
              :key="column.key"
              class="text-sm"
            >
              <template v-if="isImagePath(row[column.key])">
                <div class="flex items-center gap-2">
                  <img
                    :src="toFileUrl(row[column.key])"
                    :alt="formatCellValue(row[column.key])"
                    class="w-16 h-16 object-cover rounded border cursor-pointer hover:opacity-80"
                    @click="openImage(toFileUrl(row[column.key]))"
                  />
                  <span class="text-xs text-muted-foreground truncate max-w-[150px]">{{ formatCellValue(row[column.key]).split('/').pop() }}</span>
                </div>
              </template>
              <template v-else>
                {{ formatCellValue(row[column.key]) }}
              </template>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const props = defineProps({
  item: {
    type: Object,
    required: true
  }
})

// 从 item 中提取表格信息
const data = computed(() => {
  return props.item.data?.data || []
})

const columns = computed(() => {
  return props.item.data?.columns || []
})

const rowCount = computed(() => {
  return data.value.length
})

// ItemHeader 相关信息
const roleLabel = computed(() => {
  const roleMap = {
    'assistant': 'AI',
    'user': '用户',
    'system': '系统',
    'tool': '工具'
  }
  return roleMap[props.item?.role] || 'AI'
})

const roleColor = computed(() => {
  const colorMap = {
    'assistant': 'text-primary',
    'user': 'text-muted-foreground',
    'system': 'text-orange-500',
    'tool': 'text-blue-500'
  }
  return colorMap[props.item?.role] || 'text-primary'
})

const formatTime = (timestamp) => {
  if (!timestamp) return ''

  let dateVal = timestamp
  const num = Number(timestamp)

  if (!isNaN(num)) {
    if (num < 10000000000) {
      dateVal = num * 1000
    } else {
      dateVal = num
    }
  }

  const date = new Date(dateVal)
  if (isNaN(date.getTime())) return ''

  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')

  return `${hours}:${minutes}:${seconds}`
}

// 打开图片预览
const openImage = (url) => {
  window.open(url, '_blank')
}

// 检查是否为图片路径
const isImagePath = (value) => {
  if (typeof value !== 'string') return false
  const imageExtensions = /\.(jpg|jpeg|png|gif|webp|svg|bmp)$/i
  const isPath = value.startsWith('/') || value.startsWith('file://')
  return isPath && imageExtensions.test(value)
}

// 将本地路径转换为 file:// URL
const toFileUrl = (localPath) => {
  if (!localPath) return ''
  if (localPath.startsWith('file://')) return localPath
  return `file://${encodeURI(localPath)}`
}

const formatCellValue = (value) => {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
</script>
