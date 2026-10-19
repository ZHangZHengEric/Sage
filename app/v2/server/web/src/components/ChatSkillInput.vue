<script setup>
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  modelValue: { type: String, default: '' }, skills: { type: Array, default: () => [] },
  agentId: String, agentPackage: Object, placeholder: String, disabled: Boolean,
})
const emit = defineEmits(['update:modelValue', 'update:skills', 'keydown'])
const textarea = ref(null), query = ref(null), activeIndex = ref(0)
const available = ref([]), loading = ref(false), loadError = ref('')
let loaded = false, revision = 0
const options = computed(() => available.value.filter(item => !props.skills.includes(item.name) &&
  item.name.toLowerCase().startsWith(query.value?.keyword.toLowerCase() || '')))

async function loadSkills() {
  if (loaded || loading.value || !props.agentId || props.disabled) return
  const request = ++revision
  loading.value = true; loadError.value = ''
  try {
    const items = props.agentPackage
      ? (props.agentPackage.manifest.agents[props.agentId]?.skills || []).map(name => ({ name }))
      : await api.listAgentSkills(props.agentId)
    if (request !== revision) return
    available.value = items
    loaded = true
  } catch (exc) {
    if (request === revision) loadError.value = exc.message
  } finally { if (request === revision) loading.value = false }
}

watch(() => [props.agentId, props.agentPackage], () => {
  ++revision; loaded = false
  available.value = []; loading.value = false; loadError.value = ''; query.value = null
  emit('update:skills', [])
})
watch(() => props.disabled, disabled => { if (disabled) query.value = null })
watch(() => props.modelValue, () => nextTick(() => { resize(); if (query.value) updateQuery() }))
watch(options, () => { activeIndex.value = 0 })
watch(activeIndex, () => nextTick(() => {
  if (typeof document !== 'undefined') document.getElementById(`chat-skill-option-${activeIndex.value}`)?.scrollIntoView?.({ block: 'nearest' })
}))
onUnmounted(() => { ++revision })

function resize() {
  const el = textarea.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}
function updateQuery() {
  const el = textarea.value
  if (!el || props.disabled || el.selectionStart !== el.selectionEnd) { query.value = null; return }
  const end = el.selectionStart
  const match = props.modelValue.slice(0, end).match(/(?:^|\s)\/([^\s/<>]*)$/)
  if (!match) { query.value = null; return }
  const keyword = match[1]
  if (query.value?.keyword !== keyword) activeIndex.value = 0
  query.value = { keyword, start: end - keyword.length - 1, end }
  void loadSkills()
}
function onInput(event) {
  emit('update:modelValue', event.target.value)
  nextTick(() => { resize(); updateQuery() })
}
async function selectSkill(skill) {
  if (!query.value || !skill || !options.value.some(item => item.name === skill.name)) return
  const { start, end } = query.value
  emit('update:skills', [...props.skills, skill.name])
  emit('update:modelValue', props.modelValue.slice(0, start) + props.modelValue.slice(end))
  query.value = null
  await nextTick()
  textarea.value?.focus()
  textarea.value?.setSelectionRange(start, start)
  resize()
}
function removeSkill(name) {
  emit('update:skills', props.skills.filter(item => item !== name))
  textarea.value?.focus()
}
function keydown(event) {
  if (event.isComposing || event.keyCode === 229) return
  if (query.value) {
    if (event.key === 'Escape') { event.preventDefault(); query.value = null; return }
    if (['ArrowDown', 'ArrowUp'].includes(event.key) && options.value.length) {
      event.preventDefault()
      activeIndex.value = (activeIndex.value + (event.key === 'ArrowDown' ? 1 : -1) + options.value.length) % options.value.length
      return
    }
    if ((event.key === 'Enter' && !event.shiftKey && !event.altKey) || event.key === 'Tab') {
      if (options.value.length) { event.preventDefault(); void selectSkill(options.value[activeIndex.value]); return }
      if (event.key === 'Enter' && (loading.value || loadError.value)) { event.preventDefault(); return }
    }
  }
  emit('keydown', event)
}
defineExpose({ focus: () => textarea.value?.focus(), resize })
</script>

<template>
  <div class="chat-skill-input">
    <div v-if="skills.length" class="chat-skill-tags" aria-label="已选技能">
      <button v-for="name in skills" :key="name" type="button" class="chat-skill-tag" :aria-label="`移除技能 ${name}`" @click="removeSkill(name)">
        <span>{{ name }}</span><span aria-hidden="true">×</span>
      </button>
    </div>
    <div v-if="query" class="chat-skill-popup">
      <p v-if="loading" role="status">加载技能中…</p>
      <div v-else-if="loadError" class="chat-skill-error" role="alert">{{ loadError }}<button type="button" class="btn secondary" @mousedown.prevent @click="loadSkills">重试</button></div>
      <p v-else-if="!options.length" role="status">{{ available.length ? '没有匹配的技能' : '当前智能体暂无可用技能' }}</p>
      <div id="chat-skill-options" class="chat-skill-options" role="listbox" aria-label="可用技能">
        <button v-for="(item, index) in options" :id="`chat-skill-option-${index}`" :key="item.name" type="button" role="option"
          :aria-selected="index === activeIndex" :class="{ active: index === activeIndex }" tabindex="-1"
          @mousedown.prevent @click="selectSkill(item)" @mouseenter="activeIndex = index">
          <span>{{ item.name }}</span><small v-if="item.description">{{ item.description }}</small>
        </button>
      </div>
    </div>
    <label class="sr-only" for="chat-input">消息</label>
    <textarea id="chat-input" ref="textarea" :value="modelValue" rows="1" :placeholder="placeholder"
      role="combobox" aria-autocomplete="list" aria-haspopup="listbox" :aria-expanded="Boolean(query)" :aria-controls="query ? 'chat-skill-options' : undefined"
      :aria-activedescendant="query && options.length ? `chat-skill-option-${activeIndex}` : undefined"
      @input="onInput" @keydown="keydown" @click="updateQuery" @select="updateQuery"
      @keyup="['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes($event.key) && updateQuery()" @blur="query = null" />
  </div>
</template>

<style scoped>
.chat-skill-input { position: relative; min-width: 0; }
textarea { display: block; width: 100%; }
.chat-skill-tags { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 4px 6px; }
.chat-skill-tag { display: inline-flex; align-items: center; gap: 8px; max-width: 100%; padding: 4px 8px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--muted); color: var(--foreground); font-size: 12px; cursor: pointer; }
.chat-skill-tag span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chat-skill-popup { position: absolute; bottom: calc(100% + 12px); left: 0; right: 0; z-index: 20; padding: 6px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--card); box-shadow: 0 4px 16px var(--shadow-color); }
.chat-skill-popup p { margin: 0; padding: 12px; color: var(--muted-foreground); font-size: 12px; }
.chat-skill-options { max-height: min(240px, 35vh); overflow-y: auto; }
.chat-skill-options button { display: flex; flex-direction: column; gap: 4px; width: 100%; padding: 9px 10px; border: 0; border-radius: var(--radius); background: transparent; color: var(--foreground); text-align: left; overflow-wrap: anywhere; cursor: pointer; }
.chat-skill-options button.active { background: var(--muted); }
.chat-skill-options small { color: var(--muted-foreground); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.chat-skill-error { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px; font-size: 12px; color: var(--destructive); }
button:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
</style>
