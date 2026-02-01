<template>
  <div class="flex flex-col gap-2 mb-4">
    <div class="flex flex-col gap-1">
      <span class="text-sm font-medium text-foreground/90">{{ label }}</span>
      <small v-if="description" class="text-xs text-muted-foreground">{{ description }}</small>
    </div>
    <div class="flex items-center p-1 bg-muted rounded-lg border border-border">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        class="flex-1 h-7 rounded-md text-xs font-medium transition-all"
        :class="{ 'bg-background text-foreground shadow-sm': currentOption === 'off', 'text-muted-foreground hover:text-foreground': currentOption !== 'off' }"
        @click="handleOptionChange('off')"
        :disabled="disabled"
      >
        {{ t('common.off') }}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        class="flex-1 h-7 rounded-md text-xs font-medium transition-all"
        :class="{ 'bg-background text-foreground shadow-sm': currentOption === 'auto', 'text-muted-foreground hover:text-foreground': currentOption !== 'auto' }"
        @click="handleOptionChange('auto')"
        :disabled="disabled"
      >
        {{ t('common.auto') }}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        class="flex-1 h-7 rounded-md text-xs font-medium transition-all"
        :class="{ 'bg-background text-foreground shadow-sm': currentOption === 'on', 'text-muted-foreground hover:text-foreground': currentOption !== 'on' }"
        @click="handleOptionChange('on')"
        :disabled="disabled"
      >
        {{ t('common.on') }}
      </Button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import { Button } from '@/components/ui/button'

// Props
const props = defineProps({
  value: {
    type: [Boolean, null],
    default: null
  },
  disabled: {
    type: Boolean,
    default: false
  },
  label: {
    type: String,
    required: true
  },
  description: {
    type: String,
    default: ''
  }
})

// Emits
const emit = defineEmits(['change'])

// Composables
const { t } = useLanguage()

// Computed
const currentOption = computed(() => {
  return getOptionFromValue(props.value)
})

// Methods
const getOptionFromValue = (val) => {
  if (val === null || val === undefined) return 'auto'
  return val ? 'on' : 'off'
}

const getValueFromOption = (option) => {
  switch (option) {
    case 'on': return true
    case 'off': return false
    case 'auto': return null
    default: return null
  }
}

const handleOptionChange = (option) => {
  if (props.disabled) return
  const newValue = getValueFromOption(option)
  emit('change', newValue)
}
</script>

