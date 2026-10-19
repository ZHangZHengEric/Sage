<script setup>
import { computed, nextTick, ref } from 'vue'
import { api, isForeign } from '../api.js'
import FormDrawer from './FormDrawer.vue'
import AppIcon from './AppIcon.vue'
import FieldHelp from './FieldHelp.vue'
import { resourceHelp } from '../resource-presentation.js'

const props = defineProps({ item: { type: Object, required: true }, kind: String })
const emit = defineEmits(['edit'])
const connection = computed(() => ['mcp', 'a2a'].includes(props.kind))
async function editConnection() { open.value = false; await nextTick(); emit('edit', props.item) }
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
  <button class="btn ghost" type="button" :aria-label="`查看 ${item.name || item.key_id || '资源'} 详情`" @click="inspect">查看</button>
  <FormDrawer v-model="open" :centered="connection" :panel-class="connection ? 'resource-dialog' : undefined" :title="connection ? '连接详情' : [item._owner?.username, item.name || item.model || item.key_id || '详情'].filter(Boolean).join(' / ')" :busy="busy">
    <p v-if="busy" role="status">加载中…</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <template v-if="detail && connection">
      <div class="rs-identity"><span class="rs-icon" data-tone="blue"><AppIcon :name="kind === 'mcp' ? 'link' : 'agent'" /></span><div><h2>{{ detail.name }}</h2><div class="rs-technical">{{ kind === 'mcp' ? 'MCP 服务' : '远端智能体' }}<span v-if="item._owner"> · {{ item._owner.username }}</span></div></div><span v-if="isForeign(item)" class="rs-badge readonly">只读</span></div>
      <section class="rs-section"><h3>连接设置</h3><dl class="rs-metadata"><div><dt>状态</dt><dd>{{ detail.disabled ? '已停用' : '未停用' }}</dd></div><div v-if="kind === 'mcp'"><dt>协议</dt><dd>{{ detail.protocol }}</dd></div><div><dt>认证</dt><dd>{{ detail.has_api_key ? '已保存密钥' : '无密钥' }}</dd></div></dl><p class="mono">{{ detail.url }}</p><p v-if="detail.description">{{ detail.description }}</p></section>
      <section class="rs-section"><h3>{{ kind === 'mcp' ? '发现的工具' : '远端能力' }}</h3><ul v-if="(detail.tools || detail.skills)?.length" class="rs-file-list"><li v-for="name in detail.tools || detail.skills" :key="name"><code>{{ name }}</code></li></ul><p v-else>尚未发现能力，可刷新连接后重试。</p></section>
      <section class="rs-section rs-callout"><div class="rs-label"><h3>智能体授权</h3><FieldHelp label="智能体授权" :text="resourceHelp.authorization" /></div><p>{{ kind === 'mcp' ? '发现工具后，还需要在智能体的可用工具中选择。' : '委派任务会把内容发送给远端智能体，实际调用遵循当前授权与批准策略。' }}</p></section>
    </template>
    <pre v-else-if="detail">{{ JSON.stringify(detail, null, 2) }}</pre>
    <template v-if="connection" #footer><div class="rs-dialog-footer"><router-link class="btn ghost" to="/agents" @click="open = false">前往智能体配置</router-link><button v-if="!isForeign(item)" class="btn cta" type="button" @click="editConnection">编辑连接</button></div></template>
  </FormDrawer>
</template>

<style scoped>
pre { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
