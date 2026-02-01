<template>
  <Dialog :open="isOpen" @update:open="(val) => !val && handleClose()">
    <DialogContent class="sm:max-w-[600px]">
      <DialogHeader>
        <DialogTitle>{{ t('agentCreation.title') }}</DialogTitle>
        <DialogDescription class="hidden">Choose creation method</DialogDescription>
      </DialogHeader>

      <div class="py-4">
        <!-- Step 1: Choose Type -->
        <div v-if="!selectedType" class="grid grid-cols-2 gap-4">
          <Card 
            class="cursor-pointer hover:bg-muted/50 transition-colors border-2 hover:border-primary/50"
            :class="{'border-primary': false}"
            @click="handleCreateBlank"
          >
            <CardHeader class="space-y-1 text-center items-center">
              <div class="h-12 w-12 rounded-full bg-primary/10 flex items-center justify-center mb-2">
                <FileText class="h-6 w-6 text-primary" />
              </div>
              <CardTitle class="text-base">{{ t('agentCreation.blankConfig') }}</CardTitle>
              <CardDescription>{{ t('agentCreation.blankConfigDesc') }}</CardDescription>
            </CardHeader>
          </Card>

          <Card 
            class="cursor-pointer hover:bg-muted/50 transition-colors border-2 hover:border-primary/50"
            @click="handleTypeSelect('smart')"
          >
            <CardHeader class="space-y-1 text-center items-center">
              <div class="h-12 w-12 rounded-full bg-primary/10 flex items-center justify-center mb-2">
                <Sparkles class="h-6 w-6 text-primary" />
              </div>
              <CardTitle class="text-base">{{ t('agentCreation.smartConfig') }}</CardTitle>
              <CardDescription>{{ t('agentCreation.smartConfigDesc') }}</CardDescription>
            </CardHeader>
          </Card>
        </div>

        <!-- Step 2: Smart Config Form -->
        <div v-else-if="selectedType === 'smart'" class="space-y-4">
          <div class="flex items-center gap-2 text-primary pb-2 border-b">
            <Sparkles class="h-5 w-5" />
            <h4 class="font-medium">{{ t('agentCreation.smartConfig') }}</h4>
          </div>
          
          <p class="text-sm text-muted-foreground">请描述您希望创建的Agent功能，我们将自动生成配置</p>
          
          <div class="space-y-2">
            <Label>Agent描述</Label>
            <Textarea
              v-model="description"
              :placeholder="t('agentCreation.descriptionPlaceholder')"
              :rows="4"
              :disabled="isGenerating"
              class="resize-none"
            />
          </div>

          <!-- Available Tools -->
          <div class="space-y-2">
            <Label>{{ t('agent.availableTools') }}</Label>
            <ScrollArea class="h-[150px] border rounded-md p-4 bg-muted/10">
              <div class="space-y-3">
                <div v-for="tool in props.tools" :key="tool.name" class="flex items-center space-x-2">
                  <Checkbox 
                    :id="`tool-${tool.name}`" 
                    :checked="selectedTools.includes(tool.name)"
                    @update:checked="(checked) => {
                      if (checked) selectedTools.push(tool.name)
                      else selectedTools = selectedTools.filter(t => t !== tool.name)
                    }"
                    :disabled="isGenerating"
                  />
                  <label 
                    :for="`tool-${tool.name}`" 
                    class="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer"
                  >
                    {{ tool.name }}
                  </label>
                </div>
                <div v-if="props.tools.length === 0" class="text-sm text-muted-foreground text-center py-4">
                  {{ t('tools.noTools') || '暂无可用工具' }}
                </div>
              </div>
            </ScrollArea>
          </div>
        </div>
      </div>

      <DialogFooter v-if="selectedType === 'smart'">
        <Button variant="ghost" @click="selectedType = ''" :disabled="isGenerating">
          返回
        </Button>
        <Button 
          @click="handleCreateSmart" 
          :disabled="!description.trim() || isGenerating"
        >
          <Loader2 v-if="isGenerating" class="mr-2 h-4 w-4 animate-spin" />
          <Sparkles v-else class="mr-2 h-4 w-4" />
          {{ isGenerating ? t('agentCreation.generating') : t('agentCreation.generate') }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { ref } from 'vue'
import { Sparkles, FileText, Loader2 } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'

// UI Components
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'

const props = defineProps({
  isOpen: {
    type: Boolean,
    required: true
  },
  tools: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['close', 'create-blank', 'create-smart'])
const { t } = useLanguage()

const selectedType = ref('')
const description = ref('')
const selectedTools = ref([])
const isGenerating = ref(false)

const handleClose = () => {
  if (isGenerating.value) return
  emit('close')
  // Reset state after transition
  setTimeout(() => {
    selectedType.value = ''
    description.value = ''
    selectedTools.value = []
  }, 300)
}

const handleTypeSelect = (type) => {
  selectedType.value = type
}

const handleCreateBlank = () => {
  emit('create-blank')
  handleClose()
}

const handleCreateSmart = async () => {
  if (!description.value.trim()) return

  isGenerating.value = true
  try {
    await generateConfig()
  } catch (error) {
    console.error('生成配置失败:', error)
  } finally {
    isGenerating.value = false
  }
}

// 恢复 agentAPI
import { agentAPI } from '../api/agent.js'

const generateConfig = async () => {
  try {
    const prompt = `请创建一个Agent，描述如下：
${description.value}

请根据描述生成合适的系统提示词、开场白等配置。
${selectedTools.value.length > 0 ? `用户已选择以下工具，请在配置中启用它们：${selectedTools.value.join(', ')}` : ''}`

    const config = await agentAPI.generateConfig(prompt)
    
    // 确保选中的工具被添加到配置中
    if (selectedTools.value.length > 0) {
      config.availableTools = [...new Set([...(config.availableTools || []), ...selectedTools.value])]
    }

    emit('create-smart', config)
    handleClose()
  } catch (error) {
    throw error
  }
}
</script>

