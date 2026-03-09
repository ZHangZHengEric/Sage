<template>
  <div class="slider-container relative w-full h-5 flex items-center">
    <div class="slider-track absolute w-full h-1.5 bg-muted rounded-full"></div>
    <div 
      class="slider-range absolute h-1.5 bg-primary rounded-full"
      :style="{ left: rangeLeft, width: rangeWidth }"
    ></div>
    <input
      type="range"
      :min="min"
      :max="max"
      :step="step"
      :value="modelValue[0]"
      @input="handleInput"
      class="slider-input absolute w-full h-full opacity-0 cursor-pointer"
    />
    <div 
      class="slider-thumb absolute w-4 h-4 bg-primary rounded-full shadow-md border-2 border-background"
      :style="{ left: thumbPosition }"
    ></div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: {
    type: Array,
    default: () => [0]
  },
  min: {
    type: Number,
    default: 0
  },
  max: {
    type: Number,
    default: 100
  },
  step: {
    type: Number,
    default: 1
  }
})

const emit = defineEmits(['update:modelValue'])

const percentage = computed(() => {
  const value = props.modelValue[0] || props.min
  return ((value - props.min) / (props.max - props.min)) * 100
})

const thumbPosition = computed(() => {
  return `calc(${percentage.value}% - 8px)`
})

const rangeLeft = computed(() => '0%')
const rangeWidth = computed(() => `${percentage.value}%`)

const handleInput = (e) => {
  const value = parseFloat(e.target.value)
  emit('update:modelValue', [value])
}
</script>

<style scoped>
.slider-container {
  touch-action: none;
}

.slider-input {
  -webkit-appearance: none;
  appearance: none;
}

.slider-input::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.slider-input::-moz-range-thumb {
  width: 16px;
  height: 16px;
  cursor: pointer;
  border: none;
  background: transparent;
}
</style>
