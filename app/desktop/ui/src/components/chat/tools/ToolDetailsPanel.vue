<template>
  <Dialog :open="open" @update:open="$emit('update:open', $event)">
    <DialogContent class="sm:max-w-[70vw] max-h-[90vh] flex flex-col p-0 gap-0 overflow-hidden bg-background">
      <DialogHeader class="px-6 py-4 border-b bg-muted/20">
        <DialogTitle class="flex items-center gap-2">
           <Terminal class="w-5 h-5 text-primary" />
                       {{ t('chat.toolName') }}： {{ toolExecution.function.name }}
        </DialogTitle>
      </DialogHeader>
      
      <ScrollArea class="flex-1 min-h-0 ">
        <div class="p-6 space-y-8" v-if="toolExecution">
          <!-- Parameters -->
          <div class="space-y-3">
            <div class="flex items-center justify-between">
              <h4 class="text-sm font-medium text-muted-foreground uppercase tracking-wider">{{ t('chat.toolParams') }}</h4>
              <div class="flex items-center gap-2">
                <span v-if="copiedParams" class="text-xs text-green-500 font-medium animate-in fade-in slide-in-from-right-2">Copied!</span>
                <Button variant="outline" size="sm" class="h-7 w-7 p-0" @click="copyParams" title="Copy Parameters">
                  <Copy class="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
            <div class="relative group" v-if="!parsedArguments">
              <div class="absolute inset-0 bg-gradient-to-r from-transparent via-transparent to-background/10 pointer-events-none rounded-lg border border-transparent group-hover:border-border/50 transition-colors"></div>
              <div class="bg-muted rounded-lg border border-border/40 overflow-hidden shadow-inner">
                 <div class="flex items-center justify-between px-4 py-2 bg-muted/50 border-b border-border/10">
                    <span class="text-[10px] text-muted-foreground font-mono">JSON</span>
                 </div>
                <pre class="p-4 text-xs font-mono text-foreground overflow-auto max-h-[200px] custom-scrollbar whitespace-pre-wrap break-all">{{ formatJsonParams(toolExecution?.function?.arguments) }}</pre>
              </div>
            </div>
            
            <div v-else class="rounded-lg border border-border/40 overflow-hidden shadow-sm bg-background p-1">
               <div class="overflow-auto max-h-[300px] custom-scrollbar">
                  <JsonDataViewer :data="parsedArguments" />
               </div>
            </div>
          </div>

          <!-- Result -->
          <div class="space-y-3">
            <div class="flex items-center justify-between">
              <h4 class="text-sm font-medium text-muted-foreground uppercase tracking-wider">{{ t('chat.toolResult') }}</h4>
              <div class="flex items-center gap-2">
                <span v-if="copiedResult" class="text-xs text-green-500 font-medium animate-in fade-in slide-in-from-right-2">Copied!</span>
                <Button variant="outline" size="sm" class="h-7 w-7 p-0" @click="copyResult" title="Copy Result">
                  <Copy class="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
            
            <div v-if="parsedResult" class="rounded-lg border border-border/40 overflow-hidden shadow-sm bg-background p-1">
               <div class="overflow-auto max-h-[400px] custom-scrollbar">
                  <JsonDataViewer :data="parsedResult" />
               </div>
            </div>

            <div v-else class="bg-muted rounded-lg border border-border/40 overflow-hidden shadow-inner">
               <div class="flex items-center justify-between px-4 py-2 bg-muted/50 border-b border-border/10">
                  <span class="text-[10px] text-muted-foreground font-mono">Output</span>
               </div>
               <pre class="p-4 text-xs font-mono text-foreground overflow-x-auto max-h-[200px]  custom-scrollbar whitespace-pre-wrap break-all">{{ formatJsonParams(formatToolResult(toolResult)) }}</pre>
            </div>
          </div>
        </div>
      </ScrollArea>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useLanguage } from '@/utils/i18n.js'
import { Copy, Terminal } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import JsonDataViewer from '@/components/chat/tools/JsonDataViewer.vue'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

// 使用国际化
const { t } = useLanguage()

// 定义 props
const props = defineProps({
  open: {
    type: Boolean,
    default: false
  },
  toolExecution: {
    type: Object,
    default: null
  },
  toolResult: {
    type: [String, Object, Array],
    default: null
  }
})

// 定义 emits
const emit = defineEmits(['update:open'])

const copiedParams = ref(false)
const copiedResult = ref(false)

const parsedArguments = computed(() => {
  try {
    const args = props.toolExecution?.function?.arguments
    if (!args) return null
    // parse JSON
    const parsed = JSON.parse(args)
    if (parsed && typeof parsed === 'object' && Object.keys(parsed).length > 0) {
      return parsed
    }
    return null
  } catch (e) {
    return null
   }
 })

 const parsedResult = computed(() => {
   try {
     const result = props.toolResult.content
     if (!result) return null
     
     if (typeof result === 'object') {
        return result
     }
     
     if (typeof result === 'string') {
        // Try parsing string as JSON
        try {
          const parsed = JSON.parse(result)
          return parsed
        } catch {
          return null
        }
     }
     
     return null
   } catch (e) {
     return null
   }
 })
 
 // 复制到剪贴板
 const copyToClipboard = async (text, type) => {
  try {
    await navigator.clipboard.writeText(text)
    if (type === 'params') {
      copiedParams.value = true
      setTimeout(() => copiedParams.value = false, 2000)
    } else {
      copiedResult.value = true
      setTimeout(() => copiedResult.value = false, 2000)
    }
  } catch (err) {
    console.error('复制失败:', err)
  }
}

const copyParams = () => {
  if (props.toolExecution?.function?.arguments) {
    copyToClipboard(formatJsonParams(props.toolExecution.function.arguments), 'params')
  }
}

const copyResult = () => {
  if (props.toolResult) {
    copyToClipboard(formatJsonParams(formatToolResult(props.toolResult)), 'result')
  }
}

// 格式化工具结果
const formatToolResult = (result) => {
  if (!result) return ''
  if (typeof result === 'string') {
    try {
      const parsed = JSON.parse(result)
      return parsed.content || result
    } catch {
      return result
    }
  } else if (typeof result === 'object') {
    return result.content || JSON.stringify(result, null, 2)
  }
  return JSON.stringify(result, null, 2)
}

// 格式化JSON参数显示
const formatJsonParams = (params) => {
  if (!params) return ''
  if (typeof params === 'string') {
    try {
      const parsed = JSON.parse(params)
      return JSON.stringify(parsed, null, 2)
    } catch {
      return params
    }
  } else if (typeof params === 'object') {
    return JSON.stringify(params, null, 2)
  }
  return String(params)
}
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}
</style>

