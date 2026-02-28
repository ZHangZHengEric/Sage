<template>
  <div class="h-full bg-gradient-to-b from-background to-muted/20 border p-2 shadow-sm overflow-hidden flex flex-col">
    <!-- Progress Bar -->
    <AgentEditProgress />
    <!-- Main Content (Steps) -->
    <div class="flex-1 overflow-y-auto p-6 scroll-smooth">
      <Transition name="fade" mode="out-in">
        <component :is="currentStepComponent" :key="store.currentStep" v-bind="stepProps" />
      </Transition>
    </div>
    <!-- Footer -->
    <div class="px-5 py-5 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 flex justify-between items-center shrink-0 z-10">
      <!-- Left Side: Return/Cancel -->
      <Button 
        variant="ghost" 
        @click="handleReturn" 
        class="text-muted-foreground hover:text-foreground transition-colors"
      >
        <ChevronLeft class="mr-2 h-4 w-4" />
        {{ t('common.return') }}
      </Button>

      <!-- Right Side: Navigation & Action -->
      <div class="flex items-center gap-3">
         <Button 
            v-if="store.currentStep > 1"
            variant="secondary" 
            @click="handlePrevStep" 
            :disabled="store.currentStep === 1 || saving"
            class="min-w-[100px] shadow-sm border border-border/50"
         >
            <Loader v-if="saving" class="mr-2 h-4 w-4 animate-spin" />
            <ChevronLeft v-else class="mr-2 h-4 w-4" />
            {{ t('common.prevStep') }}
         </Button>
         
         <Button 
            v-if="store.currentStep < store.STEPS.length" 
            @click="handleNextStep"
            :disabled="(store.currentStep === 1 && !store.isStep1Valid) || saving"
            class="min-w-[120px] shadow-md bg-primary hover:bg-primary/90 text-primary-foreground transition-all active:scale-95"
         >
            <Loader v-if="saving" class="mr-2 h-4 w-4 animate-spin" />
            <template v-else>
              {{ t('common.saveAndNextStep') }}
              <ChevronRight class="ml-2 h-4 w-4" />
            </template>
         </Button>
         <Button 
            v-else 
            @click="handleSave(true)" 
            :disabled="saving"
            class="min-w-[120px] shadow-md bg-primary hover:bg-primary/90 text-primary-foreground transition-all active:scale-95"
         >
            <Loader v-if="saving" class="mr-2 h-4 w-4 animate-spin" />
            <Save v-else class="mr-2 h-4 w-4" />
            {{ t('common.save') }}
         </Button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, computed } from 'vue'
import { useAgentEditStore } from '../stores/agentEdit'
import { useLanguage } from '../utils/i18n.js'
import { 
  Loader, 
  PanelRightClose, 
  PanelRightOpen, 
  ChevronLeft, 
  ChevronRight, 
  Save 
} from 'lucide-vue-next'

// Sub-components
import AgentEditProgress from './agent-edit/AgentEditProgress.vue'
import AgentEditStep1 from './agent-edit/AgentEditStep1.vue'
import AgentEditStep2 from './agent-edit/AgentEditStep2.vue'

// UI Components
import { Button } from '@/components/ui/button'

const props = defineProps({
  visible: { type: Boolean, default: false },
  agent: { type: Object, default: null },
  tools: { type: Array, default: () => [] },
  skills: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:visible', 'save'])
const store = useAgentEditStore()
const { t } = useLanguage()
const saving = ref(false)
const showRightPanel = ref(true)

// Computed for dynamic component rendering
const currentStepComponent = computed(() => {
  switch(store.currentStep) {
    case 1: return AgentEditStep1
    case 2: return AgentEditStep2
    default: return AgentEditStep1
  }
})

const stepProps = computed(() => {
  if (store.currentStep === 2) {
    return {
      tools: props.tools,
      skills: props.skills
    }
  }
  return {}
})

// Initialize store when agent prop changes or component mounts
watch(() => props.agent, (newAgent) => {
  const isIdUpdate = newAgent && newAgent.id && store.formData.id === null && newAgent.name === store.formData.name
  const isSameAgent = newAgent && store.formData.id === newAgent.id
  
  if (isIdUpdate || isSameAgent) {
    store.initForm(newAgent, { preserveStep: true })
  } else {
    store.initForm(newAgent)
  }
}, { immediate: true })

onMounted(() => {
  // Auto-hide right panel on small screens
  if (window.innerWidth < 1024) {
    showRightPanel.value = false
  }
})


const handleSave = async (shouldExit = true) => {
  saving.value = true
  try {
    store.prepareForSave()
    await new Promise((resolve) => {
      emit('save', store.formData, shouldExit, () => {
        resolve()
      })
      // 如果parent没有调用callback (比如旧代码), 这里的promise会一直pending
      // 实际上在AgentList中我们已经确保调用了
      // 为了安全起见，可以加一个超时？或者假设parent总是可靠的
    })
  } catch (e) {
    console.error('handleSave error', e)
  } finally {
    saving.value = false
  }
}

const handleNextStep = async () => {
  const currentStep = store.currentStep
  store.nextStep()
  if (store.currentStep !== currentStep) {
    await handleSave(false)
  }
}

const handlePrevStep = async () => {
  const currentStep = store.currentStep
  store.prevStep()
  if (store.currentStep !== currentStep) {
    await handleSave(false)
  }
}

const handleReturn = () => {
  store.currentStep = 1
  emit('update:visible', false)
}
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
