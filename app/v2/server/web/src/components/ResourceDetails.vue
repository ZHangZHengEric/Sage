<script setup>
import { ref } from 'vue'
import { api } from '../api.js'
import FormDrawer from './FormDrawer.vue'

const props = defineProps({ item: { type: Object, required: true }, kind: String })
const open = ref(false), busy = ref(false), error = ref(''), detail = ref(null)
async function inspect() {
  open.value = true; busy.value = true; error.value = ''; detail.value = null
  try {
    const { _owner, ...item } = props.item
    if (props.kind === 'agents') {
      detail.value = { ...await api.getAgent(item.id, _owner), skills: await api.listAgentSkills(item.id, _owner) }
    } else if (props.kind === 'skills') {
      detail.value = await api.getSkill(item.skill_id, _owner)
    } else detail.value = item
  } catch (exc) { error.value = exc.message } finally { busy.value = false }
}
</script>

<template>
  <button class="btn ghost" type="button" @click="inspect">查看</button>
  <FormDrawer v-model="open" :title="[item._owner?.username, item.name || item.model || item.key_id || '详情'].filter(Boolean).join(' / ')" :busy="busy">
    <p v-if="busy" role="status">加载中…</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <pre v-if="detail">{{ JSON.stringify(detail, null, 2) }}</pre>
  </FormDrawer>
</template>

<style scoped>
pre { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
