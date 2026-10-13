<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({ modelValue: Boolean, title: String, busy: Boolean })
const emit = defineEmits(['update:modelValue'])
const dialog = ref(null)
const body = ref(null)
let previousOverflow = ''
let locked = false
function sync() {
  if (!dialog.value) return
  if (props.modelValue && !dialog.value.open) {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    locked = true
    dialog.value.showModal()
    body.value.scrollTop = 0
  } else if (!props.modelValue && dialog.value.open) {
    dialog.value.close()
    unlock()
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
onMounted(sync)
onBeforeUnmount(unlock)
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="form-drawer" :aria-label="title" @cancel.prevent="close" @click="event => { if (event.target === dialog) close() }">
      <div class="form-drawer-shell">
        <header class="form-drawer-head">
          <h2>{{ title }}</h2>
          <button class="btn ghost" type="button" aria-label="关闭侧窗" :disabled="busy" @click="close">关闭</button>
        </header>
        <div ref="body" class="form-drawer-body"><slot /></div>
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
.form-drawer { position: fixed; inset: 0 0 0 auto; width: 70vw; max-width: none; height: 100dvh; max-height: none; margin: 0; padding: 0; border: 0; background: var(--surface, #fff); color: inherit; box-shadow: -8px 0 32px #0002; }
.form-drawer::backdrop { background: #0006; }
.form-drawer-shell { display: flex; flex-direction: column; height: 100%; }
.form-drawer-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 1.25rem 1.5rem; border-bottom: 1px solid #8883; }
.form-drawer-head h2 { margin: 0; }
.form-drawer-body { flex: 1; overflow: auto; padding: 1.5rem; }
.form-drawer-body :deep(.panel) { box-shadow: none; margin: 0 0 1rem; }
@media (max-width: 640px) { .form-drawer { width: 100vw; } .form-drawer-body { padding: 1rem; } }
@media (prefers-reduced-motion: no-preference) { .form-drawer[open] { animation: drawer-enter 180ms ease-out; } @keyframes drawer-enter { from { transform: translateX(100%); } to { transform: translateX(0); } } }
</style>
