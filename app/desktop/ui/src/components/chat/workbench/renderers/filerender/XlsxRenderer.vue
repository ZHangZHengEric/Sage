<template>
  <div class="xlsx-renderer h-full overflow-auto p-4">
    <div v-if="loading" class="flex items-center justify-center h-full text-muted-foreground">
      <div class="text-center">
        <Loader2 class="w-8 h-8 animate-spin mx-auto mb-2" />
        <p class="text-sm">正在解析 Excel 文件...</p>
      </div>
    </div>
    <div v-else-if="error" class="flex flex-col items-center justify-center h-full text-muted-foreground">
      <FileText class="w-16 h-16 mb-3 opacity-50" />
      <p class="text-sm mb-1">Excel 文件</p>
      <p class="text-xs text-destructive mb-4">{{ error }}</p>
      <Button variant="outline" size="sm" @click="openFile">
        <ExternalLink class="w-4 h-4 mr-1" />
        打开文件
      </Button>
    </div>
    <div v-else class="xlsx-content">
      <div v-for="(sheet, sheetName) in sheets" :key="sheetName" class="mb-6">
        <h3 class="text-sm font-medium mb-2 text-muted-foreground">{{ sheetName }}</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm border-collapse border border-border">
            <tbody>
              <tr v-for="(row, rowIndex) in sheet" :key="rowIndex" class="border-b border-border">
                <td v-for="(cell, cellIndex) in row" :key="cellIndex" class="px-3 py-2 border-r border-border min-w-[80px]">
                  {{ cell }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Loader2, FileText, ExternalLink } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import * as XLSX from 'xlsx'

const props = defineProps({
  filePath: {
    type: String,
    default: ''
  },
  fileContent: {
    type: String,
    default: ''
  }
})

const loading = ref(false)
const error = ref('')
const sheets = ref({})

const loadXlsx = async () => {
  if (!props.fileContent) return
  
  loading.value = true
  error.value = ''
  
  try {
    // 将 base64 转换为 Uint8Array
    const binaryString = atob(props.fileContent)
    const bytes = new Uint8Array(binaryString.length)
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i)
    }
    
    const workbook = XLSX.read(bytes, { type: 'array' })
    const result = {}
    
    workbook.SheetNames.forEach(sheetName => {
      const worksheet = workbook.Sheets[sheetName]
      result[sheetName] = XLSX.utils.sheet_to_json(worksheet, { header: 1 })
    })
    
    sheets.value = result
  } catch (err) {
    error.value = err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

const openFile = () => {
  if (props.filePath) {
    window.__TAURI__.shell.open(props.filePath)
  }
}

onMounted(() => {
  loadXlsx()
})
</script>
