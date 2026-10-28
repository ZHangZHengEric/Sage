<script setup>
import { computed, onMounted, onScopeDispose, ref } from 'vue'
import { api, isForeign } from '../api.js'

const props = defineProps({ modelValue: { type: String, default: '' }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const connections = ref([]), loading = ref(false), error = ref('')
const selectedName = computed(() => connections.value.find(item => item.id === props.modelValue)?.name || '不通知')
let generation = 0, disposed = false
onScopeDispose(() => { disposed = true; generation++ })
async function load() {
  const current = ++generation
  loading.value = true; error.value = ''
  try {
    const page = await api.imConnections()
    if (disposed || current !== generation) return
    connections.value = page.items.filter(item => item.enabled && item.paired && !item.credentials_error && !isForeign(item))
    if (props.modelValue && !connections.value.some(item => item.id === props.modelValue)) emit('update:modelValue', '')
  } catch {
    if (!disposed && current === generation) error.value = 'IM 连接加载失败，点击重试'
  } finally { if (!disposed && current === generation) loading.value = false }
}
onMounted(load)
</script>

<template>
  <div class="im-notification-choice">
    <label><span>IM 通知</span><select :value="modelValue" aria-label="IM 通知" :title="selectedName"
      :disabled="disabled || loading" @change="emit('update:modelValue', $event.target.value)">
      <option value="">不通知</option>
      <option v-for="item in connections" :key="item.id" :value="item.id">{{ item.name }}</option>
    </select></label>
    <button v-if="error" type="button" class="im-notification-error" :disabled="disabled || loading" @click="load">{{ error }}</button>
  </div>
</template>

<style scoped>
.im-notification-choice { min-width: 0; max-width: 100%; }
.im-notification-choice label { display: flex; align-items: center; gap: 4px; min-width: 0; color: var(--muted-foreground); font-size: 12px; }
.im-notification-choice label > span { flex-shrink: 0; }
.im-notification-choice select { min-height: 32px; max-width: 140px; min-width: 0; width: auto; border: 0; box-shadow: none; background: transparent; color: var(--foreground); padding: 4px; font-size: 12px; text-overflow: ellipsis; }
.im-notification-choice select:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.im-notification-error { background: none; border: 0; padding: 4px 0; color: var(--destructive); font-size: 12px; cursor: pointer; }
@media (max-width: 640px) { .im-notification-choice select { min-height: 40px; max-width: 125px; } }
</style>
