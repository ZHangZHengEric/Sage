<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import FieldHelp from './FieldHelp.vue'
import FormDrawer from './FormDrawer.vue'
import { filterResourceChoices, selectResourceResults } from '../agent-resource-selection.js'

const props = defineProps({
  kind: { type: String, required: true }, items: { type: Array, required: true },
  selected: { type: Array, default: () => [] }, readonly: Boolean, disabled: Boolean, pending: Boolean,
})
const emit = defineEmits(['update:selected'])
const noun = computed(() => ({ tools: '工具', skills: '技能', agents: '成员' })[props.kind])
const selectedSet = computed(() => new Set(props.selected))
const selectedItems = computed(() => props.items.filter(item => selectedSet.value.has(item.id)))
const unavailableCount = computed(() => selectedItems.value.filter(item => !item.available).length)
const summary = computed(() => {
  const counts = new Map()
  for (const item of selectedItems.value) counts.set(item.sourceLabel, (counts.get(item.sourceLabel) || 0) + 1)
  return [...counts].map(([label, count]) => `${label} ${count}`).join(' · ')
})
const open = ref(false), manage = ref(false), draft = ref(new Set()), before = ref(new Set())
const query = ref(''), source = ref(''), connection = ref(''), category = ref(''), state = ref('all'), page = ref(1)
const searchInput = ref(null), catalogElement = ref(null), removed = ref(null)
const pageSize = 20
const browseItems = computed(() => props.readonly ? props.items.filter(item => selectedSet.value.has(item.id)) : props.items)
const sources = computed(() => [...new Map(browseItems.value.map(item => [item.source, item.sourceLabel])).entries()].map(([id, label]) => ({
  id, label, count: browseItems.value.filter(item => item.source === id).length,
})))
const connections = computed(() => [...new Map(browseItems.value.flatMap(item => item.connections || []).map(group => [group.id, group])).values()]
  .map(group => ({ ...group, count: browseItems.value.filter(item => item.connections?.some(value => value.id === group.id)).length })))
const categories = computed(() => [...new Set(browseItems.value.filter(item => !source.value || item.source === source.value).map(item => item.category).filter(Boolean))])
const results = computed(() => filterResourceChoices(browseItems.value, draft.value, {
  query: query.value, source: source.value, connection: connection.value, category: category.value, state: state.value,
}))
const pages = computed(() => Math.max(1, Math.ceil(results.value.length / pageSize)))
const visibleItems = computed(() => results.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const added = computed(() => [...draft.value].filter(id => !before.value.has(id)).length)
const removedCount = computed(() => [...before.value].filter(id => !draft.value.has(id)).length)
const selectableCount = computed(() => results.value.filter(item => item.available).length)
const allSelected = computed(() => selectableCount.value > 0 && results.value.filter(item => item.available).every(item => draft.value.has(item.id)))
const someSelected = computed(() => results.value.some(item => item.available && draft.value.has(item.id)))
watch([query, source, connection, category, state], () => { page.value = 1; scrollCatalog() })
watch(pages, value => { if (page.value > value) page.value = value })
watch(() => props.disabled, value => { if (value) open.value = false })
watch(() => props.readonly, () => { open.value = false })
function scrollCatalog() { if (catalogElement.value) catalogElement.value.scrollTop = 0 }
async function show(selectedOnly = false) {
  if (props.disabled) return
  before.value = new Set(props.selected); draft.value = new Set(props.selected)
  manage.value = selectedOnly; query.value = ''; source.value = ''; connection.value = ''; category.value = ''
  state.value = selectedOnly || props.readonly ? 'selected' : 'all'; page.value = 1; open.value = true
  await nextTick(); searchInput.value?.focus()
}
function chooseSource(value, group = '') { source.value = value; connection.value = group; category.value = '' }
function clearFilters() { query.value = ''; source.value = ''; connection.value = ''; category.value = ''; state.value = props.readonly ? 'selected' : 'all' }
function toggle(item, checked) {
  if (props.readonly || props.disabled || checked && !item.available) return
  const next = new Set(draft.value)
  if (checked) next.add(item.id); else next.delete(item.id)
  draft.value = next
}
function bulk(checked) {
  if (!props.readonly && !props.disabled) draft.value = selectResourceResults(draft.value, results.value, checked)
}
function confirm() {
  if (props.disabled) return
  if (!props.readonly) emit('update:selected', [...draft.value])
  open.value = false
}
function remove(item) {
  if (props.readonly || props.disabled) return
  removed.value = item
  emit('update:selected', props.selected.filter(id => id !== item.id))
}
function undo() {
  if (props.readonly || props.disabled || !removed.value) return
  emit('update:selected', [...new Set([...props.selected, removed.value.id])]); removed.value = null
}
function turnPage(value) { page.value = value; scrollCatalog() }
</script>
<template>
  <div class="agent-resource-selection">
    <header class="agent-section-heading agent-resource-heading">
      <h2>可用{{ noun }}</h2><span class="agent-selection-count">{{ selectedItems.length }} 已选</span>
      <span v-if="!pending && unavailableCount" class="agent-resource-warning">{{ unavailableCount }} 项不可用</span>
      <slot name="status" />
      <FieldHelp :label="`${noun}选择`" :text="kind === 'agents' ? '选择允许委派任务的当前用户智能体。新运行使用成员的最新配置，已开始的运行保留其配置快照。' : kind === 'tools' ? '仅授权所选的具体工具。批量选择针对当前目录，不会自动授权以后新增的工具。实际调用仍受工具审批和执行权限限制。' : '选择允许智能体使用的技能。技能绑定在保存智能体后更新，不会自动授权技能涉及的工具。'" />
      <button v-if="!readonly && selectedItems.length" type="button" class="agent-action" :disabled="disabled" @click="show()"><AppIcon name="plus" />添加{{ noun }}</button>
    </header>
    <div v-if="selectedItems.length && kind === 'tools'" class="agent-resource-summary">{{ summary }}</div>
    <div v-if="selectedItems.length" class="agent-resource-chosen-list">
      <div v-for="item in selectedItems.slice(0, 6)" :key="item.id" class="agent-resource-chosen-row">
        <span class="agent-resource-symbol"><AppIcon :name="kind === 'tools' ? 'tools' : kind === 'agents' ? 'agent' : 'skill'" /></span>
        <span class="agent-resource-name"><strong>{{ item.title }}</strong><code v-if="item.title !== item.name">{{ item.name }}</code><small v-else-if="item.description">{{ item.description }}</small></span>
        <span v-if="!pending && !item.available" class="agent-resource-warning">当前不可用</span><span v-else-if="kind === 'tools'" class="agent-resource-origin">{{ item.connections?.map(group => group.name).join('、') || item.sourceLabel }}</span>
        <button v-if="!readonly" type="button" class="agent-icon-button" :aria-label="`移除 ${item.name}`" :disabled="disabled" @click="remove(item)"><AppIcon name="close" /></button>
      </div>
      <button type="button" class="agent-resource-view-all" :disabled="disabled" @click="show(true)">{{ selectedItems.length > 6 ? `查看全部 ${selectedItems.length} 项已选` : readonly ? '查看已选详情' : '管理已选' }}<AppIcon name="chevron" /></button>
    </div>
    <div v-else class="agent-resource-empty"><AppIcon :name="kind === 'tools' ? 'tools' : kind === 'agents' ? 'agent' : 'skill'" /><span>{{ pending ? '正在加载资源…' : `尚未选择${noun}` }}</span><button v-if="!readonly" type="button" class="agent-action" :disabled="disabled" @click="show()">添加{{ noun }}</button></div>
    <p v-if="removed && !selectedSet.has(removed.id)" class="agent-resource-undo" role="status">已移除 {{ removed.title }}<button type="button" class="agent-text-button" :disabled="disabled || readonly" @click="undo">撤销</button></p>
    <FormDrawer v-model="open" centered :panel-class="`agent-resource-dialog ${kind !== 'tools' ? 'agent-resource-skills' : ''}`" :title="`${readonly ? '查看已选' : manage ? '管理已选' : '选择'}${noun}`" :busy="disabled">
      <div class="agent-resource-picker" :class="{ 'agent-resource-picker-single': kind !== 'tools' }">
        <nav v-if="kind === 'tools'" class="agent-resource-sources" :aria-label="`${noun}来源`">
          <button type="button" :aria-pressed="!source && !connection" @click="chooseSource('')">全部{{ noun }}<span>{{ browseItems.length }}</span></button>
          <template v-for="group in sources" :key="group.id">
            <button v-if="sources.length > 1" type="button" :aria-pressed="source === group.id && !connection" @click="chooseSource(group.id)">{{ group.label }}<span>{{ group.count }}</span></button>
            <button v-for="server in connections.filter(value => value.source === group.id)" :key="server.id" type="button" class="agent-resource-server" :aria-pressed="connection === server.id" @click="chooseSource(group.id, server.id)">{{ server.name }}<span>{{ server.count }}</span></button>
          </template>
        </nav>
        <div class="agent-resource-center">
          <div class="agent-resource-searchbar"><label class="agent-search"><AppIcon name="search" /><input ref="searchInput" v-model="query" type="search" placeholder="搜索名称、标识或用途" :aria-label="`搜索${noun}`" /></label><select v-if="categories.length > 1" v-model="category" aria-label="工具分类"><option value="">全部分类</option><option v-for="value in categories" :key="value" :value="value">{{ value }}</option></select></div>
          <div class="agent-resource-filterbar"><div class="agent-resource-states" :aria-label="`${noun}选择状态`"><button v-if="!readonly" type="button" :aria-pressed="state === 'all'" @click="state = 'all'">全部</button><button type="button" :aria-pressed="state === 'selected'" @click="state = 'selected'">已选 {{ draft.size }}</button></div><label v-if="!readonly" class="agent-resource-bulk"><input type="checkbox" aria-label="全选当前结果" :checked="allSelected" :indeterminate="someSelected && !allSelected" :disabled="disabled || !selectableCount" @change="bulk($event.target.checked)" /><span>全选当前 {{ selectableCount }} 项</span><FieldHelp label="批量选择范围" text="包含当前筛选条件下所有页面的可用项目。取消勾选只移除此范围内的选择，其他已选保持不变；以后新增的工具不会自动授权。" /></label><span v-else class="agent-resource-result-count">{{ results.length }} 项</span></div>
          <div ref="catalogElement" class="agent-resource-catalog" :aria-label="`${noun}目录`">
            <article v-for="item in visibleItems" :key="item.id" class="agent-resource-catalog-row" :class="{ selected: draft.has(item.id) }">
              <label><input type="checkbox" :aria-label="`选择 ${item.name}`" :checked="draft.has(item.id)" :disabled="readonly || disabled || !item.available && !draft.has(item.id)" @change="toggle(item, $event.target.checked)" /><span class="agent-resource-name"><strong>{{ item.title }}</strong><code v-if="item.title !== item.name">{{ item.name }}</code></span></label>
              <span v-if="!item.available" class="agent-resource-warning">不可用</span><span v-else-if="kind === 'tools'" class="agent-resource-row-origin">{{ item.connections?.map(group => group.name).join('、') || item.category || item.sourceLabel }}</span>
              <details v-if="item.description || !item.available"><summary :aria-label="`查看 ${item.name} 详情`"><AppIcon name="chevron" /></summary><div><p>{{ item.available ? item.description : '资源当前不在可选目录中，原有选择保留，可移除。' }}</p></div></details>
            </article>
            <div v-if="!visibleItems.length" class="agent-resource-empty"><span>{{ query || source || connection || category ? '没有匹配的资源' : state === 'selected' ? '尚未选择' : '暂无资源' }}</span><button v-if="query || source || connection || category || state !== 'all' && !readonly" type="button" class="agent-action" @click="clearFilters">清除筛选</button></div>
          </div>
          <div class="agent-resource-pages"><span>{{ results.length ? `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, results.length)} / ${results.length}` : '0 项' }}</span><div><button type="button" class="agent-action" :disabled="page === 1" @click="turnPage(page - 1)">上一页</button><button type="button" class="agent-action" :disabled="page >= pages" @click="turnPage(page + 1)">下一页</button></div></div>
        </div>

      </div>
      <template #footer><div class="agent-resource-footer"><span role="status">{{ readonly ? '只读配置' : added || removedCount ? `新增 ${added} · 移除 ${removedCount}` : '' }}</span><div><button type="button" class="agent-action" :disabled="disabled" @click="open = false">{{ readonly ? '关闭' : '取消' }}</button><button v-if="!readonly" type="button" class="agent-action primary" :disabled="disabled" @click="confirm">确认选择（{{ draft.size }}）</button></div></div></template>
    </FormDrawer>
  </div>
</template>
<style src="../agent-resource-selection.css"></style>
