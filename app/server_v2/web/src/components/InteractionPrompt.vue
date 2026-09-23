<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  interaction: { type: Object, default: null },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['decide'])

// Decisions that carry the answer itself rather than a yes or a no.
const TEXT_DECISIONS = new Set(['submit', 'change_direction'])
const LABELS = {
  approve_once: '允许这一次',
  approve_and_remember: '允许并记住',
  deny: '拒绝这次调用',
  cancel: '取消本次运行',
  submit: '提交',
  retry: '重试',
  change_direction: '换个方向',
}

const text = ref('')

const payload = computed(() => props.interaction?.payload || {})
const decisions = computed(() => props.interaction?.allowed_decisions || [])
const toolName = computed(() => payload.value.tool_name || '')
const wantsText = computed(() => decisions.value.some((name) => TEXT_DECISIONS.has(name)))
const prompt = computed(() => payload.value.prompt || payload.value.guidance || '')
const title = computed(() => {
  if (toolName.value) return `要运行 ${toolName.value} 吗？`
  return payload.value.title || '智能体在等你的回答'
})
const args = computed(() => {
  const value = payload.value.arguments
  if (value === undefined || value === null) return ''
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
})

watch(
  () => props.interaction,
  () => {
    text.value = ''
  },
)

function label(name) {
  return LABELS[name] || name
}

function choose(name) {
  const answer = text.value.trim()
  emit('decide', {
    decision: name,
    payload: wantsText.value && answer ? { text: answer } : {},
  })
}
</script>

<template>
  <div v-if="interaction" class="ask" role="group" :aria-label="title">
    <header class="ask-head">
      <strong>{{ title }}</strong>
      <span v-if="payload.side_effect_level" class="tag">{{ payload.side_effect_level }}</span>
    </header>
    <p v-if="payload.risk_reason" class="muted">{{ payload.risk_reason }}</p>
    <p v-else-if="prompt" class="muted">{{ prompt }}</p>
    <pre v-if="args" class="ask-args">{{ args }}</pre>
    <label v-if="wantsText" class="sr-only" for="interaction-text">回答</label>
    <textarea
      v-if="wantsText"
      id="interaction-text"
      v-model="text"
      rows="2"
      :disabled="busy"
      :placeholder="payload.questions?.[0]?.placeholder || '写下你的回答…'"
    />
    <div class="row">
      <button
        v-for="name in decisions"
        :key="name"
        class="btn"
        :class="name.startsWith('approve') || name === 'submit' ? 'cta' : 'ghost'"
        type="button"
        :disabled="busy"
        @click="choose(name)"
      >
        {{ label(name) }}
      </button>
    </div>
  </div>
</template>
