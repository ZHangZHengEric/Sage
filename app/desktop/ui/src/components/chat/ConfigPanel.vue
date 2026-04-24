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

      <!-- Agent 模式 -->
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

      <div v-if="(config.agentMode || 'simple') === 'fibre'" class="space-y-2">
        <Label>{{ t('agentEdit.subAgents') }}</Label>
        <p class="text-xs text-muted-foreground">
          {{ t('config.subAgentsDesc') }}
        </p>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="text-xs text-primary hover:underline"
            @click="setSubAgentSelectionMode('auto_all')"
          >
            {{ t('agentEdit.subAgentModeAutoAll') }}
          </button>
          <button
            type="button"
            class="text-xs text-primary hover:underline"
            @click="setSubAgentSelectionMode('manual')"
          >
            {{ t('agentEdit.subAgentModeManual') }}
          </button>
          <span class="text-xs text-muted-foreground">
            {{ t('config.subAgentsCurrent') }}{{ subAgentSelectionMode === 'manual' ? t('agentEdit.subAgentModeManual') : t('agentEdit.subAgentModeAutoAll') }}
          </span>
        </div>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="text-xs text-primary hover:underline"
            @click="selectAllSubAgents"
            :disabled="subAgentSelectionMode !== 'manual'"
          >
            全选
          </button>
          <button
            type="button"
            class="text-xs text-muted-foreground hover:underline"
            @click="clearSubAgents"
            :disabled="subAgentSelectionMode !== 'manual'"
          >
            清空
          </button>
        </div>
        <div class="max-h-40 overflow-y-auto rounded-md border border-border bg-background/40 p-2 space-y-1">
          <label
            v-for="agent in selectableSubAgents"
            :key="agent.id"
            class="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-muted/50 cursor-pointer"
          >
            <Checkbox
              :checked="selectedSubAgentIds.includes(agent.id)"
              :disabled="subAgentSelectionMode !== 'manual'"
              @update:checked="(checked) => toggleSubAgent(agent.id, checked === true)"
            />
            <span class="text-sm truncate">{{ agent.name }}</span>
          </label>
          <p v-if="selectableSubAgents.length === 0" class="text-xs text-muted-foreground px-2 py-1">
            当前没有可选子智能体
          </p>
        </div>
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
import { computed } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import { Settings } from 'lucide-vue-next'
import ResizablePanel from './ResizablePanel.vue'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'

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

const selectableSubAgents = computed(() => {
  const currentId = props.selectedAgent?.id
  return (props.agents || []).filter(agent => agent?.id && agent.id !== currentId)
})

const selectedSubAgentIds = computed(() => (
  subAgentSelectionMode.value === 'manual'
    ? (Array.isArray(props.config?.availableSubAgentIds) ? props.config.availableSubAgentIds : [])
    : selectableSubAgents.value.map(agent => agent.id)
))

const subAgentSelectionMode = computed(() => (
  props.config?.subAgentSelectionMode === 'manual' ? 'manual' : 'auto_all'
))

const toggleSubAgent = (agentId, checked) => {
  if (subAgentSelectionMode.value !== 'manual') return
  const current = [...selectedSubAgentIds.value]
  const next = checked
    ? [...new Set([...current, agentId])]
    : current.filter(id => id !== agentId)
  handleConfigChange({ availableSubAgentIds: next, subAgentSelectionMode: 'manual' })
}

const selectAllSubAgents = () => {
  handleConfigChange({
    availableSubAgentIds: selectableSubAgents.value.map(agent => agent.id),
    subAgentSelectionMode: 'manual'
  })
}

const clearSubAgents = () => {
  handleConfigChange({ availableSubAgentIds: [], subAgentSelectionMode: 'manual' })
}

const setSubAgentSelectionMode = (mode) => {
  handleConfigChange({
    subAgentSelectionMode: mode === 'manual' ? 'manual' : 'auto_all',
    ...(mode === 'auto_all' ? {} : { availableSubAgentIds: selectedSubAgentIds.value })
  })
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
