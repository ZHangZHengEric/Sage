<script setup>
import { ref, useId, watch } from 'vue'
import { api } from '../api.js'
import FormDrawer from './FormDrawer.vue'
import FieldHelp from './FieldHelp.vue'

const props = defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue', 'created'])
const id = useId(), agents = ref([]), loaded = ref(false), loading = ref(false), busy = ref(false), error = ref('')
const form = ref({})
const fields = [
  ['app_id', 'App ID', 'cli_...', 'cli_[A-Za-z0-9_]+', '你的飞书自建应用 App ID。', false],
  ['tenant_key', 'Tenant Key', '', null, '应用所属企业的 tenant_key，事件中的租户必须与此一致。', false],
  ['app_secret', 'App Secret', '', null, '飞书应用凭证，仅用于你创建的连接，保存后不返回密钥值。', true],
  ['verification_token', 'Verification Token', '', null, '飞书事件订阅的 Verification Token。', true],
  ['encrypt_key', 'Encrypt Key', '', null, '飞书事件订阅的 Encrypt Key，用于事件验签与解密。', true],
]
watch(() => props.modelValue, async (open, _, onCleanup) => {
  let stale = false
  onCleanup(() => { stale = true })
  if (!open) { form.value = {}; loaded.value = false; return }
  error.value = ''; loaded.value = false; loading.value = true
  form.value = { name: '', agent_id: '', config: Object.fromEntries(fields.map(([key]) => [key, ''])) }
  try {
    const values = await api.agentSummaries(false)
    if (stale) return
    agents.value = values
    form.value.agent_id = values[0]?.id || ''; loaded.value = true
  } catch (exc) { if (!stale) error.value = exc.message } finally { if (!stale) loading.value = false }
}, { immediate: true })
async function save() {
  if (busy.value || !loaded.value) return
  busy.value = true; error.value = ''
  try {
    const value = await api.createIMConnection(form.value)
    emit('created', value); emit('update:modelValue', false)
  } catch (exc) { error.value = exc.message } finally { busy.value = false }
}
</script>

<template>
  <FormDrawer :model-value="modelValue" :busy="busy" title="添加飞书连接" panel-class="im-dialog" @update:model-value="emit('update:modelValue', $event)">
    <p v-if="loading" role="status">正在加载 Agent…</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <form :id="id" class="im-form" @submit.prevent="save">
      <fieldset :disabled="busy || loading || !loaded">
        <label :for="`${id}-name`">连接名称</label><input :id="`${id}-name`" v-model.trim="form.name" required maxlength="128" autocomplete="off" />
        <label :for="`${id}-agent`">Agent</label><select :id="`${id}-agent`" v-model="form.agent_id" required><option value="" disabled>选择 Agent</option><option v-for="agent in agents" :key="agent.id" :value="agent.id">{{ agent.name || agent.id }}</option></select>
        <p v-if="loaded && !agents.length" class="error" role="status">请先创建一个 Agent</p>
        <template v-if="form.config">
          <div v-for="[key, label, placeholder, pattern, help, secret] in fields" :key="key" class="im-form-field">
            <div class="im-field-label"><label :for="`${id}-${key}`">{{ label }}</label><FieldHelp :label="label" :text="help" /></div>
            <input :id="`${id}-${key}`" v-model.trim="form.config[key]" :type="secret ? 'password' : 'text'" required :maxlength="secret ? 512 : 128" :pattern="pattern || undefined" :placeholder="placeholder" autocomplete="off" spellcheck="false" />
          </div>
        </template>
      </fieldset>
    </form>
    <template #footer><div class="im-actions"><FieldHelp label="连接配置" text="连接归属当前登录用户，只能绑定你自己的 Agent。账号和 Agent 创建后固定；服务端须配置公网回调基址 SAGE_SERVER_PUBLIC_URL。" /><button class="btn ghost" type="button" :disabled="busy" @click="emit('update:modelValue', false)">取消</button><button class="btn cta" :form="id" type="submit" :disabled="busy || !loaded || !agents.length">{{ busy ? '创建中…' : '创建连接' }}</button></div></template>
  </FormDrawer>
</template>
