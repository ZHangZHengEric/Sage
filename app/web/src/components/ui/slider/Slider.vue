<script setup>
import { reactiveOmit } from "@vueuse/core"
import { SliderRange, SliderRoot, SliderThumb, SliderTrack, useForwardPropsEmits } from "reka-ui"
import { cn } from '@/utils'

const props = defineProps({
  modelValue: { type: Array, required: false },
  defaultValue: { type: Array, required: false },
  min: { type: Number, required: false },
  max: { type: Number, required: false },
  step: { type: Number, required: false },
  minStepsBetweenThumbs: { type: Number, required: false },
  orientation: { type: String, required: false },
  dir: { type: String, required: false },
  inverted: { type: Boolean, required: false },
  name: { type: String, required: false },
  disabled: { type: Boolean, required: false },
  asChild: { type: Boolean, required: false },
  as: { type: [String, Object], required: false },
  class: { type: [String, Object, Array], required: false }
})

const emits = defineEmits(['update:modelValue', 'valueCommit'])

const delegatedProps = reactiveOmit(props, "class")

const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <SliderRoot
    :class="cn(
      'relative flex w-full touch-none select-none items-center data-[orientation=vertical]:flex-col data-[orientation=vertical]:w-2 data-[orientation=vertical]:h-full',
      props.class,
    )"
    v-bind="forwarded"
  >
    <SliderTrack class="relative h-2 w-full data-[orientation=vertical]:w-2 grow overflow-hidden rounded-full bg-secondary">
      <SliderRange class="absolute h-full data-[orientation=vertical]:w-full bg-primary" />
    </SliderTrack>
    <SliderThumb
      v-for="(_, key) in modelValue"
      :key="key"
      class="block h-5 w-5 rounded-full border-2 border-primary bg-background ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50"
    />
  </SliderRoot>
</template>
