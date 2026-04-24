<template>
  <ResizablePanel
    :title="t('chat.settings')"
    @close="$emit('close')"
  >
    <template #icon>
      <Settings class="w-4 h-4 text-muted-foreground" />
    </template>

    <div class="h-full overflow-y-auto p-6 space-y-6">
      <div class="space-y-2">
        <div class="space-y-2">
          <Label>{{ t('config.deepThinking') }}</Label>
          <div class="flex items-center h-10 gap-3 border rounded-md px-3 bg-background">
            <Switch
              :checked="Boolean(config.deepThinking)"
              @update:checked="(value) => handleConfigChange({ deepThinking: Boolean(value) })"
            />
            <span class="text-sm text-muted-foreground">
              {{ config.deepThinking ? t('common.enabled') : t('common.disabled') }}
            </span>
          </div>
          <p class="text-xs text-muted-foreground">
            {{ t('config.deepThinkingDesc') }}
          </p>
        </div>
      </div>

      <div class="space-y-2">
        <Label>{{ t('config.agentMode') }}</Label>
        <Select :model-value="config.agentMode || 'simple'" @update:model-value="(v) => handleConfigChange({ agentMode: v })">
          <SelectTrigger class="w-full">
            <SelectValue :placeholder="t('config.modeSimple')" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="fibre">{{ t('config.modeFibre') }}</SelectItem>
            <SelectItem value="simple">{{ t('config.modeSimple') }}</SelectItem>
          </SelectContent>
        </Select>
        <p class="text-xs text-muted-foreground">
          {{ t('config.agentModeDesc') }}
        </p>
      </div>

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
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'

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

const emit = defineEmits(['configChange', 'agentSelect', 'close'])

const { t } = useLanguage()

const handleConfigChange = (changes) => {
  emit('configChange', changes)
}

const handleConfigToggle = (key) => {
  const newValue = !props.config[key]
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
