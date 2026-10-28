<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useIMConnection, connectionStates } from '../use-im-connection.js'
import FormDrawer from './FormDrawer.vue'
import FieldHelp from './FieldHelp.vue'
import FeishuDeliveryList from './FeishuDeliveryList.vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({ connection: Object })
const emit = defineEmits(['changed', 'removed'])
const { connection, status, error, message, busy, refreshing, probing, deliveries, cursor, deliveriesLoading, deliveryError, unresolved, pairing, secondsLeft, clearPairing, refresh, loadDeliveries, toggle, probe, pair, retry, discard, remove, start } = useIMConnection(props.connection, { onChange: value => emit('changed', value) })
const pairingOpen = ref(false), confirm = ref(null), acceptedRisk = ref(false)
const stateLabel = computed(() => status.value ? connectionStates[status.value.state] || '状态未确认' : '状态未确认')
const locked = computed(() => busy.value || refreshing.value || !status.value)
const configLabels = { app_id: 'App ID', tenant_key: 'Tenant Key' }
watch(pairing, value => { if (value) pairingOpen.value = true; else pairingOpen.value = false })
watch(pairingOpen, value => { if (!value) clearPairing() })
watch(confirm, () => { acceptedRisk.value = false })
async function copy(value) {
  try { await navigator.clipboard.writeText(value); message.value = '已复制' }
  catch { error.value = '无法访问剪贴板，请选中文本手动复制。' }
}
function retryClicked(row) {
  if (row.state === 'unknown') confirm.value = { kind: 'retry', row }
  else void retry(row)
}
async function confirmAction() {
  const target = confirm.value
  if (!target || busy.value || (target.kind === 'retry' && !acceptedRisk.value)) return
  const ok = target.kind === 'retry' ? await retry(target.row, true) : target.kind === 'discard' ? await discard(target.row) : await remove()
  if (ok) { confirm.value = null; if (target.kind === 'delete') emit('removed', connection.value.id) }
}
function filter(value) { unresolved.value = value; void loadDeliveries() }
onMounted(start)
</script>
<template>
  <section class="im-detail" :aria-label="connection.name">
    <header class="im-section-head"><h2>{{ connection.name }}</h2><span class="system-badge" :class="status?.state === 'awaiting_pairing' ? 'amber' : 'neutral'">{{ stateLabel }}</span></header>
    <p v-if="message" class="system-message" role="status"><span>{{ message }}</span><button class="icon-button" type="button" aria-label="关闭提示" @click="message = ''"><AppIcon name="close" /></button></p>
    <div v-if="error && !confirm" class="system-error" role="alert"><span>{{ error }}</span><button class="btn ghost" type="button" :disabled="busy || refreshing" @click="refresh">刷新状态</button></div>
    <p v-if="connection.credentials_error" class="error" role="alert">{{ connection.credentials_error }}</p>
    <dl class="im-status"><div><dt>Agent</dt><dd>{{ connection.agent_id }}</dd></div><div><dt>本人配对</dt><dd>{{ connection.paired ? '已配对' : '未配对' }}</dd></div><div><dt>凭据测试<FieldHelp label="凭据测试" text="只测试能否获取 tenant token，不发送消息，也不代表飞书回调和收发已联调。" /></dt><dd>{{ probing || '未测试' }}</dd></div></dl>
    <div class="im-actions im-connection-actions"><button class="btn ghost" type="button" :disabled="busy || refreshing" @click="refresh"><AppIcon name="refresh" />{{ refreshing ? '刷新中…' : '刷新状态' }}</button><button class="btn ghost" type="button" :disabled="locked" @click="probe">测试凭据</button><button v-if="!connection.paired" class="btn cta" type="button" :disabled="locked || !connection.enabled" @click="pair">生成配对码</button><button class="btn ghost" type="button" :disabled="locked" @click="toggle">{{ connection.enabled ? '停用连接' : '启用连接' }}</button><button class="btn ghost danger" type="button" :disabled="locked" @click="confirm = { kind: 'delete' }; error = ''">删除连接</button></div>
    <div class="im-webhook"><div class="im-field-label"><label :for="`webhook-${connection.id}`">事件回调地址</label><FieldHelp label="事件回调地址" text="使用服务端配置的 SAGE_SERVER_PUBLIC_URL，保留部署路径前缀。修改公网地址需更新服务端环境变量。" /></div><div class="im-copy"><input :id="`webhook-${connection.id}`" :value="connection.webhook_url" placeholder="未配置 SAGE_SERVER_PUBLIC_URL" readonly spellcheck="false" /><button class="btn ghost" type="button" :disabled="!connection.webhook_url" @click="copy(connection.webhook_url)"><AppIcon name="copy" />复制地址</button></div></div>
    <details class="im-config"><summary>连接配置<FieldHelp label="连接配置" text="账号与 Agent 创建后固定；更换账号或 Agent 需新建连接。保存后不返回密钥值。" /></summary><dl class="im-config-values"><div v-for="(label, key) in configLabels" :key="key"><dt>{{ label }}</dt><dd><code>{{ connection.config[key] }}</code></dd></div><div><dt>应用凭据</dt><dd>{{ connection.credentials_configured ? '已配置' : '未配置，请重新创建连接' }}</dd></div></dl></details>
    <FeishuDeliveryList :rows="deliveries" :loading="deliveriesLoading" :error="deliveryError" :cursor="cursor" :busy="busy" :unresolved="unresolved" @filter="filter" @refresh="loadDeliveries()" @more="loadDeliveries(false)" @retry="retryClicked" @discard="row => { confirm = { kind: 'discard', row }; error = '' }" />
    <FormDrawer v-model="pairingOpen" centered title="本人配对" panel-class="im-dialog" :busy="busy">
      <template v-if="pairing"><label for="im-pair-command">在飞书私聊发送</label><div class="im-copy"><input id="im-pair-command" :value="pairing.command" readonly autocomplete="off" spellcheck="false" /><button class="btn ghost" type="button" :disabled="!secondsLeft" @click="copy(pairing.command)">复制命令</button></div><p role="status">剩余 {{ Math.floor(secondsLeft / 60) }} 分 {{ secondsLeft % 60 }} 秒</p></template>
      <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="message === '已复制'" role="status">已复制</p>
      <template #footer><div class="im-actions"><button class="btn ghost" type="button" :disabled="busy" @click="pairingOpen = false">关闭</button><button class="btn ghost" type="button" :disabled="busy || refreshing" @click="refresh">检查配对</button><button class="btn cta" type="button" :disabled="busy" @click="pair">重新生成</button></div></template>
    </FormDrawer>
    <FormDrawer :model-value="Boolean(confirm)" centered :title="confirm?.kind === 'retry' ? '重试未知投递' : confirm?.kind === 'discard' ? '丢弃投递' : '删除飞书连接'" panel-class="im-dialog" :busy="busy" @update:model-value="value => { if (!value) confirm = null }">
      <template v-if="confirm?.kind === 'retry'"><p>平台可能已经接收投递 #{{ confirm.row.id }}。再次发送可能产生重复消息。</p><label class="im-risk"><input v-model="acceptedRisk" type="checkbox" />我接受可能重复发送的风险</label></template>
      <p v-else-if="confirm?.kind === 'discard'">丢弃投递 #{{ confirm.row.id }} 后，该条回复不会再发送，后续待发回复可以继续投递。</p>
      <p v-else>删除「{{ connection.name }}」及其收发状态，保留既有 Sage 会话。</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <template #footer><div class="im-actions"><button class="btn ghost" type="button" :disabled="busy" @click="confirm = null">取消</button><button class="btn cta" type="button" :disabled="busy || (confirm?.kind === 'retry' && !acceptedRisk)" @click="confirmAction">{{ busy ? '处理中…' : confirm?.kind === 'retry' ? '确认重试' : confirm?.kind === 'discard' ? '确认丢弃' : '确认删除' }}</button></div></template>
    </FormDrawer>
  </section>
</template>
