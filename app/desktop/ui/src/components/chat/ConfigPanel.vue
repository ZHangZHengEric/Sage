<template>
  <ResizablePanel 
    :title="t('chat.settings')"
    @close="$emit('close')"
  >
    <template #icon>
      <Settings class="w-4 h-4 text-muted-foreground" />
    </template>
    
    <div class="h-full overflow-y-auto p-6 space-y-6">
      <!-- 深度思考 -->
      <div class="space-y-2">
        <ThreeOptionSwitch
          :value="config.deepThinking"
          @change="(value) => handleConfigChange({ deepThinking: value })"
          :label="t('config.deepThinking')"
          :description="t('config.deepThinkingDesc')"
        />
      </div>

      <!-- Agent 模式 -->
      <div class="space-y-2">
        <Label>{{ t('config.agentMode') }}</Label>
        <Select :model-value="config.agentMode || 'auto'" @update:model-value="(v) => handleConfigChange({ agentMode: v })">
          <SelectTrigger class="w-full">
            <SelectValue :placeholder="t('config.modeAuto')" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="auto">{{ t('config.modeAuto') }}</SelectItem>
            <SelectItem value="fibre">{{ t('config.modeFibre') }}</SelectItem>
            <SelectItem value="simple">{{ t('config.modeSimple') }}</SelectItem>
            <SelectItem value="multi">{{ t('config.modeMulti') }}</SelectItem>
          </SelectContent>
        </Select>
        <p class="text-xs text-muted-foreground">
          {{ t('config.agentModeDesc') }}
        </p>
      </div>

      <!-- 更多建议 -->
      <div class="flex flex-col gap-2">
        <div class="flex items-center space-x-2">
          <Checkbox 
            id="moreSuggest" 
            :checked="config.moreSuggest"
            @update:checked="handleConfigToggle('moreSuggest')"
          />
          <Label for="moreSuggest" class="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer">
            {{ t('config.moreSuggest') }}
          </Label>
        </div>
        <p class="text-xs text-muted-foreground pl-6">
          {{ t('config.moreSuggestDesc') }}
        </p>
      </div>

      <!-- 最大循环次数 -->
      <div class="space-y-2">
        <Label for="maxLoopCount">{{ t('config.maxLoopCount') }}</Label>
        <Input
          id="maxLoopCount"
          type="number"
          min="1"
          max="50"
          :value="config.maxLoopCount"
          @input="handleMaxLoopCountChange"
          class="h-9"
        />
        <p class="text-xs text-muted-foreground">
          {{ t('config.maxLoopCountDesc') }}
        </p>
      </div>
    </div>
  </ResizablePanel>
</template>

<script setup>
import { useLanguage } from '../../utils/i18n.js'
import { Settings } from 'lucide-vue-next'
import ResizablePanel from './ResizablePanel.vue'
import ThreeOptionSwitch from './ThreeOptionSwitch.vue'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

// Props
const props = defineProps({
  config: {
    type: Object,
    required: true
  },
  agents: {
    type: Array,
    default: () => []
  },
  selectedAgent: {
    type: Object,
    default: null
  }
})

// Emits
const emit = defineEmits(['configChange', 'agentSelect', 'close'])

// Composables
const { t } = useLanguage()

// Methods
const handleConfigChange = (changes) => {
  emit('configChange', changes)
}

const handleConfigToggle = (key) => {
  const newValue = !props.config[key]
  console.log(`配置开关变更: ${key} = ${newValue}`)
  handleConfigChange({ [key]: newValue })
}

const handleMaxLoopCountChange = (e) => {
  const value = parseInt(e.target.value, 10)
  if (!isNaN(value) && value > 0) {
    handleConfigChange({ maxLoopCount: value })
  }
}

const handleAgentChange = (e) => {
  const agent = props.agents.find(a => a.id === e.target.value)
  emit('agentSelect', agent)
}
</script>
