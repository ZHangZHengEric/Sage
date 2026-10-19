<script setup>
import { nextTick, onBeforeUnmount, ref, useId } from 'vue'
import AppIcon from './AppIcon.vue'

defineProps({ label: { type: String, required: true }, text: { type: String, required: true } })
const id = useId(), root = ref(null), trigger = ref(null), tooltip = ref(null)
const open = ref(false), position = ref({})
let timer
function cancelHide() { clearTimeout(timer) }
function hide() {
  cancelHide(); open.value = false
  window.removeEventListener('scroll', hide, true)
  window.removeEventListener('resize', hide)
  document.removeEventListener('pointerdown', outside)
  document.removeEventListener('keydown', escape, true)
}
function outside(event) { if (!root.value?.contains(event.target)) hide() }
function escape(event) {
  if (event.key !== 'Escape') return
  event.preventDefault(); event.stopPropagation(); hide()
}
async function show() {
  cancelHide(); open.value = true
  await nextTick()
  if (!open.value || !trigger.value || !tooltip.value) return
  const rect = trigger.value.getBoundingClientRect()
  const { width, height } = tooltip.value.getBoundingClientRect()
  position.value = {
    left: `${Math.max(12, Math.min(window.innerWidth - width - 12, rect.left - 8))}px`,
    top: `${rect.bottom + height + 8 < window.innerHeight ? rect.bottom + 8 : Math.max(12, rect.top - height - 8)}px`,
  }
  window.addEventListener('scroll', hide, true)
  window.addEventListener('resize', hide)
  document.addEventListener('pointerdown', outside)
  document.addEventListener('keydown', escape, true)
}
function leave() { timer = setTimeout(hide, 140) }
onBeforeUnmount(() => { if (typeof window !== 'undefined') hide() })
</script>

<template>
  <span ref="root" class="field-help" @pointerenter="cancelHide" @pointerleave="leave">
    <button ref="trigger" type="button" :aria-label="`了解${label}的影响`" :aria-expanded="open" :aria-describedby="open ? id : undefined" @pointerenter="show" @focus="show" @blur="hide" @click="show"><AppIcon name="help" /></button>
    <span v-if="open" :id="id" ref="tooltip" role="tooltip" class="field-tooltip" :style="position">{{ text }}</span>
  </span>
</template>

<style scoped>
.field-help { display: inline-flex; vertical-align: middle; flex-shrink: 0; }
.field-help > button { display: grid; place-items: center; width: 26px; height: 26px; padding: 0; border: 0; border-radius: 50%; background: transparent; color: var(--muted-foreground); }
.field-help > button:hover, .field-help > button[aria-expanded="true"] { color: var(--primary); background: var(--muted); }
.field-help .app-icon { width: 14px; height: 14px; }
.field-tooltip { position: fixed; z-index: 100; width: min(290px, calc(100vw - 24px)); padding: 13px 15px; border: 1px solid #ffffff1f; border-radius: 12px; background: #263128; color: #f8faf5; box-shadow: 0 8px 30px #0002; font-size: 12px; font-weight: 400; line-height: 1.8; text-align: left; white-space: normal; overflow-wrap: anywhere; }
</style>
