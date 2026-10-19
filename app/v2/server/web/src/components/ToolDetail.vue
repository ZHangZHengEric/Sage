<script setup>
import { computed, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import FieldHelp from './FieldHelp.vue'
import FormDrawer from './FormDrawer.vue'
import { resourceHelp, toolPresentation, toolParameters } from '../resource-presentation.js'
const props = defineProps({ modelValue: Boolean, item: Object })
const emit = defineEmits(['update:modelValue'])
const tab = ref('overview'), message = ref('')
const view = computed(() => toolPresentation(props.item || {}))
const parameters = computed(() => toolParameters(props.item || {}))
const sources = { official: '官方工具', mcp: 'MCP 工具', host: '主机工具' }
const effects = { none: '未声明副作用', read: '读取', write: '写入', reversible: '可撤销修改', irreversible: '不可撤销修改' }
watch(() => props.item, () => { tab.value = 'overview'; message.value = '' })
async function copy(value) {
  try { await navigator.clipboard.writeText(value); message.value = '已复制' }
  catch { message.value = '无法复制，请从原始定义中手动选择文本' }
}
</script>
<template>
  <FormDrawer :model-value="modelValue" title="工具详情" centered panel-class="resource-dialog tool-dialog" @update:model-value="emit('update:modelValue', $event)">
    <template v-if="item">
      <div class="rs-identity"><span class="rs-icon" :data-tone="view.tone"><AppIcon :name="view.icon" /></span><div><h2>{{ view.title }}</h2><div class="rs-technical">{{ item.name }}</div></div><span class="rs-badge neutral">{{ sources[item.source] || item.source }}</span></div>
      <nav class="rs-detail-tabs" aria-label="工具详情分区"><button v-for="[value, label] in [['overview', '概览'], ['parameters', '调用参数'], ['raw', '原始定义']]" :key="value" :aria-pressed="tab === value" @click="tab = value">{{ label }}</button></nav>
      <template v-if="tab === 'overview'">
        <section class="rs-section"><h3>用途</h3><p>{{ view.description || '此工具暂未提供用途说明' }}</p><p v-if="item.description && item.description !== view.description" class="rs-original-description">{{ item.description }}</p><div class="rs-callname"><code>{{ item.name }}</code><button class="btn ghost" type="button" @click="copy(item.name)">复制调用名</button></div></section>
        <section class="rs-section"><dl class="rs-metadata"><div><dt>来源</dt><dd>{{ sources[item.source] || item.source }}</dd></div><div><dt>分类</dt><dd>{{ view.category }}</dd></div><div><dt>工具声明的作用</dt><dd>{{ effects[item.side_effect_level] || '未提供' }}</dd></div><div><dt>默认选择</dt><dd class="rs-label">{{ item.default ? '默认工具集' : '可选工具' }}<FieldHelp label="默认工具集" :text="resourceHelp.defaults" /></dd></div></dl></section>
        <section class="rs-section rs-callout"><div class="rs-label"><h3>调用权限</h3><FieldHelp label="调用权限" :text="resourceHelp.authorization" /></div><p>在智能体配置中选择这个工具。实际调用范围和批准方式沿用该智能体的执行策略。</p></section>
      </template>
      <template v-else-if="tab === 'parameters'"><section class="rs-section"><div class="rs-label"><h3>输入参数</h3><FieldHelp label="输入参数" :text="resourceHelp.parameters" /></div><div v-for="field in parameters" :key="field.name" class="rs-parameter"><div class="rs-parameter-heading"><strong>{{ field.label }}</strong><code v-if="field.label !== field.name">{{ field.name }}</code><span class="rs-badge neutral">{{ field.type }}</span><span v-if="field.required" class="rs-badge">必填</span><span v-else class="rs-small muted">可选</span></div><p v-if="field.description">{{ field.description }}</p><div v-if="field.hasDefault" class="rs-parameter-note">默认值：<code>{{ JSON.stringify(field.default) }}</code></div><div v-if="field.enum" class="rs-parameter-note">可选值：{{ field.enum.map(value => JSON.stringify(value)).join(' / ') }}</div></div><p v-if="!parameters.length">{{ item.input_schema?.type === 'object' || item.input_schema?.properties ? '此工具没有命名输入参数' : '此工具尚未提供参数定义' }}</p></section></template>
      <section v-else><div class="rs-raw-head"><span class="muted rs-small">工具定义</span><button class="btn ghost" type="button" @click="copy(JSON.stringify(item, null, 2))">复制</button></div><pre class="rs-code">{{ JSON.stringify(item, null, 2) }}</pre></section>
    </template>
    <template #footer><div class="rs-dialog-footer"><span class="rs-small muted" role="status">{{ message }}</span><router-link class="btn cta" to="/agents" @click="emit('update:modelValue', false)">前往智能体配置<AppIcon name="chevron" /></router-link></div></template>
  </FormDrawer>
</template>
