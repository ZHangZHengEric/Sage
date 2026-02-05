<template>
  <div class="h-full bg-gradient-to-b from-background to-muted/20 border rounded-2xl shadow-sm overflow-hidden flex flex-col">
    <!-- Progress Bar -->
    <AgentEditProgress />
    <!-- Main Content (Steps) -->
    <div class="flex-1 overflow-y-auto p-6 scroll-smooth">
      <Transition name="fade" mode="out-in">
        <component :is="currentStepComponent" :key="store.currentStep" v-bind="stepProps" />
      </Transition>
    </div>
    <!-- Footer -->
    <div class="p-4 border-t bg-muted/20 flex justify-center items-center">
      <div class="flex items-center gap-2">
         <Button 
            variant="outline" 
            @click="store.prevStep" 
            :disabled="store.currentStep === 1"
            class="min-w-[100px]"
         >
            <ChevronLeft class="mr-2 h-4 w-4" />
            {{ t('common.prevStep') }}
         </Button>
         
         <Button 
            v-if="store.currentStep < store.STEPS.length" 
            @click="store.nextStep"
            :disabled="store.currentStep === 1 && !store.isStep1Valid"
            class="min-w-[100px]"
         >
            {{ t('common.nextStep') }}
            <ChevronRight class="ml-2 h-4 w-4" />
         </Button>
         <Button 
            v-else 
            @click="handleSave" 
            :disabled="saving"
            class="min-w-[100px]"
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
import AgentEditStep3 from './agent-edit/AgentEditStep3.vue'

// UI Components
import { Button } from '@/components/ui/button'

const props = defineProps({
  visible: { type: Boolean, default: false },
  agent: { type: Object, default: null },
  tools: { type: Array, default: () => [] },
  skills: { type: Array, default: () => [] },
  knowledgeBases: { type: Array, default: () => [] }
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
    case 3: return AgentEditStep3
    default: return AgentEditStep1
  }
})

const stepProps = computed(() => {
  if (store.currentStep === 2) {
    return {
      tools: props.tools,
      skills: props.skills,
      knowledgeBases: props.knowledgeBases
    }
  }
  return {}
})

// Initialize store when agent prop changes or component mounts
watch(() => props.agent, (newAgent) => {
  store.initForm(newAgent)
}, { immediate: true })

onMounted(() => {
  if (!props.agent) {
    if (store.formData.id === null && !store.formData.name) {
        store.loadDraft()
    }
  }
  // Auto-hide right panel on small screens
  if (window.innerWidth < 1024) {
    showRightPanel.value = false
  }
})


const handleSave = async () => {
  saving.value = true
  try {
    store.prepareForSave()
    emit('save', store.formData)
  } catch (e) {
    console.error('handleSave error', e)
  } finally {
    saving.value = false
  }
}

const handleClose = () => {
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
