<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({ modelValue: Boolean, title: String, busy: Boolean, centered: Boolean, wide: Boolean, panelClass: String })
const emit = defineEmits(['update:modelValue'])
const dialog = ref(null)
const body = ref(null)
let previousOverflow = ''
let locked = false
let lastOutsideFocus = null
let returnFocus = null
function rememberFocus(event) {
  if (event.target instanceof HTMLElement && event.target !== document.body && !event.target.closest('dialog')) lastOutsideFocus = event.target
}
function sync() {
  if (!dialog.value) return
  if (props.modelValue && !dialog.value.open) {
    returnFocus = lastOutsideFocus || document.activeElement
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    locked = true
    dialog.value.showModal()
    body.value.scrollTop = 0
  } else if (!props.modelValue && dialog.value.open) {
    dialog.value.close()
    unlock()
    nextTick(() => { if (returnFocus?.isConnected) returnFocus.focus() })
  }
}
function unlock() {
  if (locked) document.body.style.overflow = previousOverflow
  locked = false
}
function close() {
  if (!props.busy) emit('update:modelValue', false)
}
watch(() => props.modelValue, sync, { flush: 'post' })
onMounted(() => { document.addEventListener('focusin', rememberFocus); sync() })
onBeforeUnmount(() => { document.removeEventListener('focusin', rememberFocus); unlock() })
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="form-drawer" :class="[panelClass, { 'form-dialog': centered, 'form-drawer-wide': wide }]" :aria-label="title" @cancel.prevent="close" @click="event => { if (event.target === dialog) close() }">
      <div class="form-drawer-shell">
        <header class="form-drawer-head">
          <h2>{{ title }}</h2>
          <button class="btn ghost" type="button" :aria-label="centered ? '关闭弹框' : '关闭侧窗'" :disabled="busy" @click="close">关闭</button>
        </header>
        <div ref="body" class="form-drawer-body"><slot /></div>
        <footer v-if="$slots.footer" class="form-drawer-footer"><slot name="footer" /></footer>
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
.form-drawer { position: fixed; inset: 0 0 0 auto; width: 70vw; max-width: none; height: 100dvh; max-height: none; margin: 0; padding: 0; border: 0; background: var(--surface, #fff); color: inherit; box-shadow: var(--shadow-popover); }
.form-drawer::backdrop { background: var(--overlay); }
.form-drawer-wide { width: min(1440px, 94vw); }
.form-drawer-shell { display: flex; flex-direction: column; height: 100%; }
.form-drawer-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 1.25rem 1.5rem; border-bottom: 1px solid var(--border); }
.form-drawer-head h2 { margin: 0; }
.form-drawer-body { flex: 1; overflow: auto; padding: 1.5rem; }
.form-drawer-body :deep(.panel) { box-shadow: none; margin: 0 0 1rem; }
@media (max-width: 640px) { .form-drawer { width: 100vw; } .form-drawer-body { padding: 1rem; } }
@media (prefers-reduced-motion: no-preference) { .form-drawer[open] { animation: drawer-enter 180ms ease-out; } @keyframes drawer-enter { from { transform: translateX(100%); } to { transform: translateX(0); } } }
.form-dialog { inset: 0; width: min(32rem, calc(100vw - 2rem)); height: fit-content; max-height: calc(100dvh - 2rem); margin: auto; border: 1px solid var(--border); border-radius: var(--radius); }
.form-dialog[open] { display: flex; animation: none; }
.form-dialog .form-drawer-shell { width: 100%; height: auto; min-height: 0; max-height: calc(100dvh - 2rem); }
.form-dialog .form-drawer-head h2 { overflow-wrap: anywhere; min-width: 0; }
.form-dialog .form-drawer-head button { flex-shrink: 0; }
.form-drawer-footer { flex-shrink: 0; border-top: 1px solid var(--border); padding: 16px 24px; }
</style>
