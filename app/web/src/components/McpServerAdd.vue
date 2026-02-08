<template>
  <div class="w-full h-full p-4 overflow-y-auto">
    <div class="max-w-2xl mx-auto">
      <form @submit.prevent="handleSubmit" class="space-y-8 pb-10">
        <!-- Basic Info -->
        <div class="space-y-4">
          <h3 class="flex items-center gap-2 text-lg font-semibold">
            <Database class="w-5 h-5" />
            {{ t('tools.basicInfo') }}
          </h3>

          <div class="space-y-2">
            <Label for="name">{{ t('tools.serverName') }}</Label>
            <Input 
              id="name" 
              v-model="form.name" 
              type="text" 
              :placeholder="t('tools.enterServerName')" 
              required
            />
          </div>
        </div>

        <!-- Protocol Config -->
        <div class="space-y-4">
          <h3 class="flex items-center gap-2 text-lg font-semibold">
            <Code class="w-5 h-5" />
            {{ t('tools.protocolConfig') }}
          </h3>

          <div class="space-y-2">
            <Label>{{ t('tools.protocol') }}</Label>
            <Select v-model="form.protocol" required>
              <SelectTrigger>
                <SelectValue placeholder="Select protocol" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="stdio">stdio</SelectItem>
                <SelectItem value="sse">SSE</SelectItem>
                <SelectItem value="streamable_http">Streamable HTTP</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <!-- stdio -->
          <div v-if="form.protocol === 'stdio'" class="space-y-4 animate-in slide-in-from-top-2 duration-200">
            <div class="space-y-2">
              <Label for="command">{{ t('tools.command') }}</Label>
              <Input 
                id="command" 
                v-model="form.command" 
                type="text" 
                :placeholder="t('tools.enterCommand')"
                required 
              />
            </div>

            <div class="space-y-2">
              <Label for="args">{{ t('tools.arguments') }}</Label>
              <Input 
                id="args" 
                v-model="form.args" 
                type="text" 
                :placeholder="t('tools.enterArguments')"
              />
            </div>
          </div>

          <!-- SSE -->
          <div v-if="form.protocol === 'sse'" class="space-y-2 animate-in slide-in-from-top-2 duration-200">
            <Label for="sse_url">{{ t('tools.sseUrl') }}</Label>
            <Input 
              id="sse_url" 
              v-model="form.sse_url" 
              type="url" 
              :placeholder="t('tools.enterSseUrl')" 
              required
            />
          </div>

          <!-- Streamable HTTP -->
          <div v-if="form.protocol === 'streamable_http'" class="space-y-2 animate-in slide-in-from-top-2 duration-200">
            <Label for="streamable_http_url">{{ t('tools.streamingHttpUrl') }}</Label>
            <Input 
              id="streamable_http_url" 
              v-model="form.streamable_http_url" 
              type="url"
              :placeholder="t('tools.enterStreamingHttpUrl')" 
              required 
            />
          </div>
        </div>

        <!-- Additional Info -->
        <div class="space-y-4">
          <h3 class="flex items-center gap-2 text-lg font-semibold">
            <Globe class="w-5 h-5" />
            {{ t('tools.additionalInfo') }}
          </h3>

          <div class="space-y-2">
            <Label for="description">{{ t('tools.description') }}</Label>
            <Textarea 
              id="description" 
              v-model="form.description" 
              :placeholder="t('tools.enterDescription')"
              rows="4" 
              class="resize-y min-h-[100px]"
            />
          </div>
        </div>

        <!-- Actions -->
        <div class="flex justify-center gap-4 pt-6 border-t">
          <Button type="button" variant="outline" @click="$emit('cancel')">
            {{ t('tools.cancel') }}
          </Button>
          <Button type="submit" :disabled="loading">
            <Loader v-if="loading" class="mr-2 h-4 w-4 animate-spin" />
            {{ loading ? t('tools.adding') : t('tools.add') }}
          </Button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { Database, Code, Globe, Loader } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

// Props
const props = defineProps({
  loading: {
    type: Boolean,
    default: false
  }
})

// Emits
const emit = defineEmits(['submit', 'cancel'])

// Composables
const { t } = useLanguage()

// State
const form = reactive({
  name: '',
  protocol: 'sse',
  command: '',
  args: '',
  sse_url: '',
  streamable_http_url: '',
  description: ''
})

// Methods
const handleSubmit = () => {
  const payload = {
    name: form.name,
    protocol: form.protocol,
    description: form.description
  }

  // 根据协议类型添加相应字段
  if (form.protocol === 'stdio') {
    payload.command = form.command
    if (form.args) {
      payload.args = Array.isArray(form.args)
        ? form.args
        : form.args.split(' ').filter(arg => arg.trim())
    }
  } else if (form.protocol === 'sse') {
    payload.sse_url = form.sse_url
  } else if (form.protocol === 'streamable_http') {
    payload.streamable_http_url = form.streamable_http_url
  }

  emit('submit', payload)
}

// 重置表单的方法
const resetForm = () => {
  form.name = ''
  form.protocol = 'sse'
  form.command = ''
  form.args = ''
  form.sse_url = ''
  form.streamable_http_url = ''
  form.description = ''
}

// 暴露重置方法给父组件
defineExpose({
  resetForm
})
</script>
