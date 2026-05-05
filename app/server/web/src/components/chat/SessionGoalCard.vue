<template>
  <div
    class="mb-4 rounded-2xl border border-border/70 bg-background/85 px-4 py-3 shadow-sm backdrop-blur-sm dark:border-white/10 dark:bg-[rgba(8,8,10,0.92)]"
  >
    <template v-if="isEditing">
      <div class="mb-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground/80">
        {{ goal ? (t('chat.goalEdit') || 'Edit goal') : (t('chat.goalSet') || 'Set goal') }}
      </div>
      <textarea
        v-model="draftObjective"
        rows="3"
        class="min-h-[88px] w-full resize-y rounded-xl border border-border/70 bg-background/70 px-3 py-2 text-sm text-foreground outline-none ring-0 placeholder:text-muted-foreground/60 focus:border-primary/40 dark:bg-[rgba(10,10,12,0.86)]"
        :placeholder="t('chat.goalPlaceholder') || 'Describe what you want this session to achieve'"
      />
      <div class="mt-3 flex items-center justify-between gap-3">
        <p class="text-[11px] text-muted-foreground/75">
          {{ t('chat.goalEditorHint') || 'Saved goals are attached to this session.' }}
        </p>
        <div class="flex items-center gap-2">
          <Button variant="ghost" size="sm" class="h-8 rounded-full px-3" :disabled="busy" @click="cancelEdit">
            {{ t('common.cancel') || 'Cancel' }}
          </Button>
          <Button size="sm" class="h-8 rounded-full px-3" :disabled="busy || !draftObjective.trim()" @click="submitGoal">
            {{ t('common.save') || 'Save' }}
          </Button>
        </div>
      </div>
    </template>

    <template v-else-if="goal">
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0 flex-1">
          <div class="mb-1 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground/80">
            {{ t('chat.currentGoal') || 'Current goal' }}
          </div>
          <p class="break-words text-sm font-medium leading-6 text-foreground">
            {{ goal.objective }}
          </p>
        </div>
        <Badge :variant="statusVariant" class="h-6 rounded-full px-2.5 text-[11px] capitalize">
          {{ statusLabel }}
        </Badge>
      </div>
      <div class="mt-3 flex items-center justify-between gap-3">
        <div class="min-w-0 flex-1">
          <p class="text-[11px] text-muted-foreground/75">
            {{ goalMetaText }}
          </p>
          <p v-if="goalTransitionText" class="mt-1 text-[11px] text-muted-foreground/75">
            {{ goalTransitionText }}
          </p>
        </div>
        <div class="flex items-center gap-2">
          <Button variant="ghost" size="sm" class="h-8 rounded-full px-3" :disabled="busy" @click="startEdit">
            {{ t('chat.goalEdit') || 'Edit' }}
          </Button>
          <Button
            v-if="goal.status !== 'completed'"
            variant="secondary"
            size="sm"
            class="h-8 rounded-full px-3"
            :disabled="busy"
            @click="$emit('complete-goal')"
          >
            {{ t('chat.goalComplete') || 'Complete' }}
          </Button>
          <Button variant="ghost" size="sm" class="h-8 rounded-full px-3 text-muted-foreground" :disabled="busy" @click="$emit('clear-goal')">
            {{ t('chat.goalClear') || 'Clear' }}
          </Button>
        </div>
      </div>
    </template>

    <template v-else>
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0 flex-1">
          <div class="mb-1 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground/80">
            {{ t('chat.currentGoal') || 'Current goal' }}
          </div>
          <p class="text-sm leading-6 text-muted-foreground">
            {{ canEdit ? (t('chat.goalEmptyState') || 'No goal has been set for this session yet.') : (t('chat.goalSessionRequired') || 'Start the session first to attach a goal.') }}
          </p>
        </div>
        <Badge variant="outline" class="h-6 rounded-full px-2.5 text-[11px]">
          {{ t('chat.goalStatus.none') || 'None' }}
        </Badge>
      </div>
      <div class="mt-3 flex justify-end">
        <div class="flex w-full items-center justify-between gap-3">
          <p v-if="goalTransitionText" class="text-[11px] text-muted-foreground/75">
            {{ goalTransitionText }}
          </p>
          <div class="flex-1" v-else />
          <Button size="sm" class="h-8 rounded-full px-3" :disabled="busy || !canEdit" @click="startEdit">
            {{ t('chat.goalSet') || 'Set goal' }}
          </Button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useLanguage } from '@/utils/i18n.js'

const props = defineProps({
  goal: {
    type: Object,
    default: null
  },
  goalTransition: {
    type: Object,
    default: null
  },
  busy: {
    type: Boolean,
    default: false
  },
  canEdit: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['save-goal', 'clear-goal', 'complete-goal'])

const { t } = useLanguage()
const isEditing = ref(false)
const draftObjective = ref('')

watch(() => props.goal?.objective, (value) => {
  if (!isEditing.value) {
    draftObjective.value = value || ''
  }
}, { immediate: true })

const statusVariant = computed(() => {
  switch (props.goal?.status) {
    case 'completed':
      return 'default'
    case 'paused':
      return 'secondary'
    default:
      return 'outline'
  }
})

const statusLabel = computed(() => {
  const status = props.goal?.status || 'active'
  return t(`chat.goalStatus.${status}`) || status
})

const goalMetaText = computed(() => {
  if (props.goal?.status === 'completed') {
    return t('chat.goalCompletedHint') || 'This goal has been marked complete.'
  }
  if (props.goal?.status === 'paused') {
    return t('chat.goalPausedHint') || 'This goal is paused and can be resumed by the runtime.'
  }
  return t('chat.goalActiveHint') || 'This goal is attached to the current session.'
})

const goalTransitionText = computed(() => {
  const transition = props.goalTransition
  if (!transition?.type) return ''
  switch (transition.type) {
    case 'resumed':
      return t('chat.goalTransitionResumed') || 'Continuing this goal after resume.'
    case 'completed':
      return t('chat.goalTransitionCompleted') || 'The latest run marked this goal complete.'
    case 'cleared':
      return t('chat.goalTransitionCleared') || 'The latest run cleared the previous goal.'
    case 'replaced':
      return transition.previous_objective
        ? `${t('chat.goalTransitionReplaced') || 'Replaced the previous goal.'} ${transition.previous_objective}`
        : (t('chat.goalTransitionReplaced') || 'Replaced the previous goal.')
    default:
      return ''
  }
})

const startEdit = () => {
  draftObjective.value = props.goal?.objective || ''
  isEditing.value = true
}

const cancelEdit = () => {
  draftObjective.value = props.goal?.objective || ''
  isEditing.value = false
}

const submitGoal = async () => {
  const objective = draftObjective.value.trim()
  if (!objective) return
  emit('save-goal', objective)
  isEditing.value = false
}
</script>
