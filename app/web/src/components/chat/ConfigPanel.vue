<template>
  <div class="w-[35%] flex flex-col border-l border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
    <div class="flex-1 overflow-y-auto p-6 space-y-6">
      
      <!-- 深度思考 -->
      <div class="space-y-2">
        <ThreeOptionSwitch
          :value="config.deepThinking"
          @change="(value) => handleConfigChange({ deepThinking: value })"
          :label="t('config.deepThinking')"
          :description="t('config.deepThinkingDesc')"
        />
      </div>

      <!-- 多智能体协作 -->
      <div class="space-y-2">
        <ThreeOptionSwitch
          :value="config.multiAgent"
          @change="(value) => handleConfigChange({ multiAgent: value })"
          :label="t('config.multiAgent')"
          :description="t('config.multiAgentDesc')"
        />
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
  </div>
</template>

<script setup>
import { useLanguage } from '../../utils/i18n.js'
import ThreeOptionSwitch from './ThreeOptionSwitch.vue'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

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
const emit = defineEmits(['configChange', 'agentSelect'])

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

<style scoped>
/* Removed custom styles in favor of Tailwind classes */
</style>