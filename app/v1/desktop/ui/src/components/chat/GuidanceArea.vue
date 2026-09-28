<template>
  <div v-if="hasGuidances" class="w-full max-w-[800px] mx-auto mb-2">
    <div class="rounded-2xl border border-border bg-muted/30">
      <button
        type="button"
        class="w-full flex items-center justify-between px-3 py-2 text-xs text-muted-foreground hover:bg-muted/50 transition-colors rounded-t-2xl"
        @click="collapsed = !collapsed"
      >
        <span class="flex items-center gap-1.5">
          <span class="font-medium text-foreground">
            {{ t('guidance.queuedCount', { count: guidances.length }) }}
          </span>
          <CornerDownLeft class="h-3 w-3" />
        </span>
        <ChevronDown
          class="h-4 w-4 transition-transform"
          :class="{ '-rotate-180': !collapsed }"
        />
      </button>
      <div v-if="!collapsed" class="px-3 pb-2 flex flex-col gap-1.5">
        <div
          v-for="g in guidances"
          :key="g.guidanceId"
          class="group flex items-start gap-2 rounded-lg bg-background/60 border border-border/60 px-2.5 py-1.5"
        >
          <div v-if="editingId !== g.guidanceId" class="flex-1 text-sm text-foreground whitespace-pre-wrap break-words">
            {{ g.content }}
          </div>
          <textarea
            v-else
            v-model="editingContent"
            rows="2"
            class="flex-1 bg-transparent border-none outline-none resize-none text-sm text-foreground"
            @keydown.enter.exact.prevent="commitEdit(g)"
            @keydown.esc.prevent="cancelEdit"
          />
          <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <template v-if="editingId === g.guidanceId">
              <button
                type="button"
                class="h-6 w-6 inline-flex items-center justify-center rounded hover:bg-primary/10 text-primary"
                :title="t('guidance.save')"
                @click="commitEdit(g)"
              >
                <Check class="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                class="h-6 w-6 inline-flex items-center justify-center rounded hover:bg-muted text-muted-foreground"
                :title="t('guidance.cancel')"
                @click="cancelEdit"
              >
                <X class="h-3.5 w-3.5" />
              </button>
            </template>
            <template v-else>
              <button
                type="button"
                class="h-6 w-6 inline-flex items-center justify-center rounded hover:bg-muted text-muted-foreground"
                :title="t('guidance.applyNow')"
                @click="applyNow(g)"
              >
                <CornerDownLeft class="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                class="h-6 w-6 inline-flex items-center justify-center rounded hover:bg-muted text-muted-foreground"
                :title="t('guidance.edit')"
                @click="startEdit(g)"
              >
                <Pencil class="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                class="h-6 w-6 inline-flex items-center justify-center rounded hover:bg-destructive/10 text-destructive"
                :title="t('guidance.delete')"
                @click="removeGuidance(g)"
              >
                <Trash2 class="h-3.5 w-3.5" />
              </button>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ChevronDown, Pencil, Trash2, Check, X, CornerDownLeft } from 'lucide-vue-next'
import { useWorkbenchStore } from '@/stores/workbench.js'
import { chatAPI } from '@/api/chat.js'
import { useLanguage } from '@/utils/i18n.js'

const props = defineProps({
  sessionId: { type: String, required: true },
  applyNowHandler: { type: Function, default: null }
})

const { t } = useLanguage()
const workbench = useWorkbenchStore()

const collapsed = ref(false)
const editingId = ref(null)
const editingContent = ref('')

const guidances = computed(() => workbench.getGuidances(props.sessionId))
const hasGuidances = computed(() => guidances.value.length > 0)

const startEdit = (g) => {
  editingId.value = g.guidanceId
  editingContent.value = g.content
}

const cancelEdit = () => {
  editingId.value = null
  editingContent.value = ''
}

const commitEdit = async (g) => {
  const next = (editingContent.value || '').trim()
  if (!next || next === g.content) {
    cancelEdit()
    return
  }
  try {
    await chatAPI.updatePendingUserInjection(props.sessionId, g.guidanceId, next)
    workbench.updateGuidance(props.sessionId, g.guidanceId, next)
  } catch (e) {
    console.warn('[GuidanceArea] update failed:', e)
  } finally {
    cancelEdit()
  }
}

const removeGuidance = async (g) => {
  try {
    await chatAPI.deletePendingUserInjection(props.sessionId, g.guidanceId)
  } catch (e) {
    console.warn('[GuidanceArea] delete failed (will still drop locally):', e)
  } finally {
    workbench.removeGuidance(props.sessionId, g.guidanceId)
  }
}

const applyNow = async (g) => {
  if (props.applyNowHandler) {
    await props.applyNowHandler(g)
  }
}
</script>
