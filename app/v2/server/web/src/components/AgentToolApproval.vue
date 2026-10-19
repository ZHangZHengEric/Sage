<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import FieldHelp from './FieldHelp.vue'
import FormDrawer from './FormDrawer.vue'
import { approvalRuleItems, approvalOverrideCount, changeApprovalRule, approvalChanges } from '../agent-approval.js'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) }, tools: { type: Array, default: () => [] },
  defaultMode: String, readonly: Boolean, disabled: Boolean, loading: Boolean, error: String,
})
const emit = defineEmits(['update:modelValue', 'load'])
const open = ref(false), query = ref(''), source = ref(''), customOnly = ref(false), page = ref(1)
const draft = ref({}), before = ref({}), searchInput = ref(null), catalogElement = ref(null)
const pageSize = 20
const rules = computed(() => approvalRuleItems(props.tools, open.value ? before.value : props.modelValue))
const sources = computed(() => [...new Map(rules.value.map(item => [item.source, item.sourceLabel])).entries()]
  .map(([id, label]) => ({ id, label, count: rules.value.filter(item => item.source === id).length })))
const customCount = computed(() => approvalOverrideCount(props.modelValue))
const draftCount = computed(() => approvalOverrideCount(draft.value))
const changes = computed(() => approvalChanges(before.value, draft.value))
const defaultLabel = computed(() => props.defaultMode === 'ask' ? '需要询问' : props.defaultMode === 'auto_approve' ? '免审批' : '沿用旧配置')
const blocked = computed(() => props.disabled || props.readonly || props.loading || Boolean(props.error))
const results = computed(() => {
  const search = query.value.trim().toLocaleLowerCase()
  return rules.value.filter(item => (!source.value || item.source === source.value) &&
    (!customOnly.value || draft.value[item.key] && draft.value[item.key] !== 'inherit') &&
    (!search || `${item.title} ${item.name} ${item.key} ${item.description} ${item.sourceLabel}`.toLocaleLowerCase().includes(search)))
})
const pages = computed(() => Math.max(1, Math.ceil(results.value.length / pageSize)))
const visibleRules = computed(() => results.value.slice((page.value - 1) * pageSize, page.value * pageSize))
watch([query, source, customOnly], () => { page.value = 1; scrollCatalog() })
watch(pages, value => { if (page.value > value) page.value = value })
watch(() => props.disabled, value => { if (value) open.value = false })
watch(() => props.readonly, () => { open.value = false })
function scrollCatalog() { if (catalogElement.value) catalogElement.value.scrollTop = 0 }
async function show() {
  if (props.disabled) return
  before.value = { ...props.modelValue }; draft.value = { ...props.modelValue }
  query.value = ''; source.value = ''; customOnly.value = false; page.value = 1
  open.value = true; emit('load')
  await nextTick(); searchInput.value?.focus()
}
function setRule(key, value) {
  if (!blocked.value) draft.value = changeApprovalRule(draft.value, key, value)
}
function confirm() {
  if (blocked.value) return
  if (changes.value) emit('update:modelValue', { ...draft.value })
  open.value = false
}
function turnPage(value) { page.value = value; scrollCatalog() }
function clearFilters() { query.value = ''; source.value = ''; customOnly.value = false }
</script>
<template>
  <div class="agent-approval-entry">
    <div><strong>逐工具审批</strong><span>{{ customCount ? `${customCount} 项自定义` : '全部继承默认' }}</span></div>
    <button type="button" class="agent-action" :disabled="disabled" @click="show">{{ readonly ? '查看规则' : '设置规则' }}<AppIcon name="chevron" /></button>
  </div>
  <FormDrawer v-model="open" centered panel-class="agent-resource-dialog agent-approval-dialog" title="逐工具审批" :busy="disabled">
    <div class="agent-resource-picker">
      <nav class="agent-resource-sources" aria-label="审批工具来源"><button type="button" :aria-pressed="!source" @click="source = ''">全部工具<span>{{ rules.length }}</span></button><button v-for="group in sources" :key="group.id" type="button" :aria-pressed="source === group.id" @click="source = group.id">{{ group.label }}<span>{{ group.count }}</span></button></nav>
      <div class="agent-resource-center">
        <div class="agent-resource-searchbar"><label class="agent-search"><AppIcon name="search" /><input ref="searchInput" v-model="query" type="search" placeholder="搜索工具名称或用途" aria-label="搜索审批工具" /></label></div>
        <div class="agent-resource-filterbar"><div class="agent-resource-states" aria-label="审批规则范围"><button type="button" :aria-pressed="!customOnly" @click="customOnly = false">全部</button><button type="button" :aria-pressed="customOnly" @click="customOnly = true">自定义 {{ draftCount }}</button></div><span class="agent-approval-default">默认：{{ defaultLabel }}<FieldHelp label="逐工具审批" text="继承默认会移除此工具的单独规则。自定义规则只覆盖审批要求，不会授予工具使用权限，也不会绕过命令与沙箱限制。确认更新页面草稿，保存智能体后生效。" /></span></div>
        <div ref="catalogElement" class="agent-resource-catalog" aria-label="工具审批规则">
          <div v-if="loading" class="agent-resource-empty" role="status">正在加载工具…</div>
          <div v-else-if="error" class="agent-resource-empty" role="alert"><span>{{ error }}</span><button type="button" class="agent-action" :disabled="disabled" @click="emit('load')">重新加载</button></div>
          <template v-else>
            <div v-for="item in visibleRules" :key="item.key" class="agent-approval-rule"><span class="agent-resource-name"><strong>{{ item.title }}</strong><code v-if="item.title !== item.name">{{ item.name }}</code><small v-if="!item.available" class="agent-approval-missing">暂不可用</small></span><select :aria-label="`${item.name} 审批模式`" :value="draft[item.key] || 'inherit'" :disabled="blocked" @change="setRule(item.key, $event.target.value)"><option value="inherit">继承默认</option><option value="ask">需要询问</option><option value="auto_approve">免审批</option></select></div>
            <div v-if="!visibleRules.length" class="agent-resource-empty"><span>{{ query || source ? '没有匹配的工具' : customOnly ? '暂无自定义规则' : '暂无工具' }}</span><button v-if="query || source || customOnly" type="button" class="agent-action" @click="clearFilters">清除筛选</button></div>
          </template>
        </div>
        <div v-if="!loading && !error" class="agent-resource-pages"><span>{{ results.length ? `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, results.length)} / ${results.length}` : '0 项' }}</span><div><button type="button" class="agent-action" :disabled="page === 1" @click="turnPage(page - 1)">上一页</button><button type="button" class="agent-action" :disabled="page >= pages" @click="turnPage(page + 1)">下一页</button></div></div>
      </div>
    </div>
    <template #footer><div class="agent-resource-footer"><span role="status">{{ readonly ? '只读配置' : changes ? `${changes} 项修改` : '' }}</span><div><button type="button" class="agent-action" :disabled="disabled" @click="open = false">{{ readonly ? '关闭' : '取消' }}</button><button v-if="!readonly" type="button" class="agent-action primary" :disabled="blocked" @click="confirm">确认修改</button></div></div></template>
  </FormDrawer>
</template>
<style src="../agent-resource-selection.css"></style>
<style scoped>
.agent-approval-entry { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 20px; margin-top: 22px; border-top: 1px solid var(--border); }
.agent-approval-entry > div { display: flex; align-items: baseline; flex-wrap: wrap; gap: 9px; }
.agent-approval-entry strong { font-size: 12px; font-weight: 550; }
.agent-approval-entry span { font-size: 11px; color: var(--muted-foreground); }
.agent-approval-default { display: flex; align-items: center; gap: 6px; color: var(--muted-foreground); font-size: 11px; }
.agent-approval-rule { display: flex; gap: 16px; align-items: center; padding: 13px 0; border-bottom: 1px solid var(--border); }
.agent-approval-rule:last-child { border: 0; }
.agent-approval-rule > select { width: 130px; flex-shrink: 0; font-size: 12px; }
.agent-resource-name .agent-approval-missing { color: var(--status-warning); font-size: 10px; }
@media (max-width: 600px) { .agent-approval-rule { gap: 10px; } .agent-approval-rule > select { width: 112px; font-size: 11px; } }
</style>
