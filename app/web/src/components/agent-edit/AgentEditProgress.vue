<template>
  <div class="w-full py-5 px-6 border-b bg-background/70 backdrop-blur-sm">
    <!-- Progress Bar -->
    <div class="relative mb-6">
      <div class="absolute top-1/2 left-0 w-full h-1 bg-muted/70 -translate-y-1/2 rounded-full"></div>
      <div 
        class="absolute top-1/2 left-0 h-1 bg-primary -translate-y-1/2 rounded-full transition-all duration-300"
        :style="{ width: `${((currentStep - 1) / (steps.length - 1)) * 100}%` }"
      ></div>
      
      <div class="relative flex justify-between">
        <div 
          v-for="step in steps" 
          :key="step.id"
          class="flex flex-col items-center gap-2 cursor-pointer group"
          @click="handleStepClick(step.id)"
        >
          <div 
            class="w-9 h-9 rounded-full flex items-center justify-center text-sm font-medium border-2 transition-all duration-300 z-10 shadow-sm"
            :class="[
              step.id === currentStep 
                ? 'bg-primary border-primary text-primary-foreground scale-110' 
                : step.id < currentStep 
                  ? 'bg-primary border-primary text-primary-foreground' 
                  : 'bg-background border-muted text-muted-foreground group-hover:border-primary/50'
            ]"
          >
            <span v-if="step.id < currentStep">✓</span>
            <span v-else>{{ step.id }}</span>
          </div>
          <span 
            class="text-xs font-medium transition-colors duration-300 absolute top-11 w-32 text-center"
            :class="[
              step.id === currentStep ? 'text-primary' : 'text-muted-foreground'
            ]"
          >
            {{ step.label }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useAgentEditStore } from '../../stores/agentEdit'

const store = useAgentEditStore()
const currentStep = computed(() => store.currentStep)
const steps = computed(() => store.STEPS)

const handleStepClick = (stepId) => {
  store.setStep(stepId)
}
</script>
