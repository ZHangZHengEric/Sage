<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import FieldHelp from './FieldHelp.vue'
import FormDrawer from './FormDrawer.vue'
import PluginConfig from './PluginConfig.vue'
import AgentModelFields from './AgentModelFields.vue'
import { toolPresentation } from '../resource-presentation.js'
import { agentSections, agentHelp, budgetFields, cloneConfiguration, sameConfiguration, sectionChanges } from '../agent-presentation.js'
const props = defineProps({
  form: { type: Object, required: true },
  agentId: String, readonly: Boolean, canEdit: Boolean, canDelete: Boolean, busy: Boolean, error: String, message: String,
  resourcesLoading: Boolean, resourcesError: String, approvalLoading: Boolean, approvalError: String,
  models: { type: Array, default: () => [] }, tools: { type: Array, default: () => [] },
  skills: { type: Array, default: () => [] }, selectedSkills: { type: Array, default: () => [] },
  approvalTools: { type: Array, default: () => [] }, externalTools: { type: Array, default: () => [] },
  savedPlugins: { type: Object, default: null }, pluginCatalog: { type: Object, default: null },
  savedForm: { type: Object, default: null }, savedSkills: { type: Array, default: null },
})
const emit = defineEmits(['close', 'edit', 'save', 'delete', 'update:form', 'update:selectedSkills', 'reload-resources', 'load-approval-tools'])
const initialForm = cloneConfiguration(props.form), initialSkills = [...props.selectedSkills]
const sections = agentSections
const resourcesDisabled = computed(() => props.resourcesLoading || Boolean(props.resourcesError))
const activeSection = ref('basic'), content = ref(null), navigation = ref(null), leaveOpen = ref(false)
const toolCategory = ref(''), toolSearch = ref(''), skillSearch = ref(''), onlySelectedTools = ref(false), onlySelectedSkills = ref(false)
const approvalSearch = ref(''), onlyApprovalOverrides = ref(false)
const disabled = computed(() => props.readonly || props.busy)
const choicesDisabled = computed(() => disabled.value || resourcesDisabled.value)
watch([activeSection, resourcesDisabled], ([section, unavailable]) => {
  if (section === 'approval' && !unavailable) emit('load-approval-tools')
})
const baseline = computed(() => props.savedForm || initialForm)
const baselineSkills = computed(() => props.savedSkills || initialSkills)
const changedSections = computed(() => sectionChanges(props.form, baseline.value, props.selectedSkills, baselineSkills.value))
const dirty = computed(() => !sameConfiguration(props.form, baseline.value) || changedSections.value.skills)
const modelLabel = computed(() => props.models.find(model => model.id === props.form.model_id)?.model || props.form.model_id || props.models.find(model => model.is_default)?.model || '使用默认模型')
const summaries = computed(() => ({
  basic: props.form.name || '未命名', plugins: modelLabel.value,
  memory: { agent: '当前智能体', session: '当前会话', principal: '当前用户' }[props.form.memory?.scope || 'agent'],
  budgets: props.form.budgets?.max_steps != null ? `${props.form.budgets.max_steps} 步` : '跟随默认',
  tools: `${props.form.tools?.length || 0} 个工具`, skills: `${props.selectedSkills.length} 个技能`,
  approval: props.form.tool_approval ? props.form.tool_approval.default === 'ask' ? '需要询问' : '免审批' : '沿用旧配置',
  execution: { sandboxed: '工作区内执行', ask: '命令需审批', deny: '禁止执行' }[props.form.execution_policy?.shell || 'sandboxed'],
}))
const categories = computed(() => [...new Map(props.tools.filter(tool => tool.category).map(tool => [tool.category, toolPresentation(tool).category])).entries()])
const presentedTools = computed(() => props.tools.map(tool => ({ ...tool, presentation: toolPresentation(tool) })))
const displayedTools = computed(() => {
  const query = toolSearch.value.toLowerCase()
  return presentedTools.value.filter(tool => (!toolCategory.value || tool.category === toolCategory.value) && (!onlySelectedTools.value || props.form.tools?.includes(tool.name)) && `${tool.name} ${tool.presentation.title} ${tool.presentation.description} ${tool.presentation.category}`.toLowerCase().includes(query))
})
const displayedSkills = computed(() => props.skills.filter(skill => (!onlySelectedSkills.value || props.selectedSkills.includes(skill.name)) && `${skill.name} ${skill.description || ''}`.toLowerCase().includes(skillSearch.value.toLowerCase())))
const unavailableTools = computed(() => (props.form.tools || []).filter(name => !props.tools.some(tool => tool.name === name)))
const unavailableSkills = computed(() => props.selectedSkills.filter(name => !props.skills.some(skill => skill.name === name)))
const approvalRules = computed(() => {
  const tools = new Map(props.approvalTools.map(tool => [tool.approval_key || tool.name, { name: tool.name, title: toolPresentation(tool).title }]))
  for (const key of Object.keys(props.form.tool_approval?.tools || {})) if (!tools.has(key)) tools.set(key, { name: key, title: key })
  return [...tools].map(([key, tool]) => ({ key, ...tool }))
})
const approvalOverrideCount = computed(() => Object.values(props.form.tool_approval?.tools || {}).filter(value => value !== 'inherit').length)
const displayedApprovalRules = computed(() => approvalRules.value.filter(tool => (!onlyApprovalOverrides.value || (props.form.tool_approval?.tools?.[tool.key] && props.form.tool_approval.tools[tool.key] !== 'inherit')) && `${tool.name} ${tool.title}`.toLowerCase().includes(approvalSearch.value.toLowerCase())))
const availableExternalTools = computed(() => [...new Set([...props.externalTools, ...(props.form.external_tools || [])])])
async function jump(id) {
  activeSection.value = id
  await nextTick()
  const scroller = content.value, target = scroller?.querySelector(`#agent-${id}`)
  if (!target) return
  const inset = typeof window === 'undefined' ? 24 : parseFloat(window.getComputedStyle(target).scrollMarginTop) || 0
  scroller.scrollTo({ top: Math.max(0, scroller.scrollTop + target.getBoundingClientRect().top - scroller.getBoundingClientRect().top - inset), behavior: typeof window !== 'undefined' && !window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'smooth' : 'instant' })
}
function trackSection() {
  if (!content.value) return
  const top = content.value.getBoundingClientRect().top
  let current = 'basic'
  for (const section of sections) if (content.value.querySelector(`#agent-${section.id}`)?.getBoundingClientRect().top <= top + 100) current = section.id
  activeSection.value = current
}
watch(activeSection, async () => {
  await nextTick()
  const nav = navigation.value, button = nav?.querySelector('[aria-current="location"]')
  if (button && nav.scrollWidth > nav.clientWidth) nav.scrollTo({ left: Math.max(0, button.offsetLeft - nav.offsetLeft - (nav.clientWidth - button.offsetWidth) / 2), behavior: 'instant' })
})
function update(key, value) { if (!disabled.value) emit('update:form', { ...props.form, [key]: value }) }
function toggleTool(name) {
  if (choicesDisabled.value) return
  const selected = new Set(props.form.tools || [])
  if (selected.has(name)) selected.delete(name); else selected.add(name)
  update('tools', [...selected])
}
function selectTools(select) {
  if (choicesDisabled.value) return
  const selected = new Set(props.form.tools || [])
  for (const tool of displayedTools.value) { if (select) selected.add(tool.name); else selected.delete(tool.name) }
  update('tools', [...selected])
}
function toggleExternalTool(name) {
  if (choicesDisabled.value) return
  const selected = new Set(props.form.external_tools || [])
  if (selected.has(name)) selected.delete(name); else selected.add(name)
  update('external_tools', [...selected])
}
function toggleSkill(name) {
  if (choicesDisabled.value) return
  const selected = new Set(props.selectedSkills)
  if (selected.has(name)) selected.delete(name); else selected.add(name)
  emit('update:selectedSkills', [...selected])
}
function updateBudget(key, value) {
  const budgets = { ...(props.form.budgets || {}) }
  if (value === '') delete budgets[key]; else budgets[key] = Number(value)
  update('budgets', budgets)
}
function setApprovalDefault(value) {
  update('tool_approval', value ? { default: value, tools: { ...(props.form.tool_approval?.tools || {}) } } : null)
}
function setToolApproval(key, value) {
  const config = props.form.tool_approval || { default: 'auto_approve', tools: {} }
  update('tool_approval', { ...config, tools: { ...config.tools, [key]: value } })
}
function requestClose() {
  if (props.busy) return
  if (dirty.value && !props.readonly) leaveOpen.value = true
  else emit('close')
}
function discardAndClose() { if (!props.busy) { leaveOpen.value = false; emit('close') } }
async function submit(exit = false) {
  if (choicesDisabled.value) return
  if (!props.form.name?.trim()) { await jump('basic'); content.value?.querySelector('#agent-name')?.focus(); return }
  const invalid = content.value?.querySelector('input:invalid, textarea:invalid, select:invalid')
  if (invalid) {
    for (let parent = invalid.parentElement; parent && parent !== content.value; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true
    const section = invalid.closest('[data-agent-section]')?.dataset.agentSection
    if (section) await jump(section)
    await nextTick(); invalid.reportValidity(); return
  }
  leaveOpen.value = false; emit('save', exit)
}
</script>
<template>
  <div class="agent-editor">
    <header class="agent-editor-head">
      <div class="agent-editor-title"><button class="agent-icon-button" type="button" aria-label="返回智能体列表" :disabled="busy" @click="requestClose"><AppIcon class="agent-back-icon" name="chevron" /></button><span class="agent-breadcrumb">智能体</span><span class="agent-breadcrumb-separator">/</span><h1>{{ form.name || '新智能体' }}</h1><span v-if="readonly" class="agent-badge">只读</span><span v-else class="agent-save-state" :class="{ dirty }" role="status"><i></i>{{ busy ? '正在保存' : dirty ? '有未保存更改' : agentId ? '已保存' : '尚未保存' }}</span></div>
      <div class="agent-editor-actions"><button v-if="readonly && canEdit" class="agent-action primary" type="button" :disabled="busy" @click="emit('edit')">编辑配置</button><template v-if="!readonly"><button class="agent-action agent-save-exit" type="button" :disabled="busy || resourcesDisabled || !form.name?.trim()" @click="submit(true)">保存并返回</button><button class="agent-action primary" type="button" :disabled="busy || resourcesDisabled || !form.name?.trim()" @click="submit(false)">{{ busy ? '保存中…' : '保存更改' }}</button></template><button v-if="readonly" class="agent-action" type="button" :disabled="busy" @click="requestClose">返回列表</button></div>
    </header>
    <p v-if="resourcesLoading" class="agent-editor-feedback" role="status">正在加载可选配置…</p><p v-else-if="resourcesError" class="agent-editor-feedback error" role="alert">{{ resourcesError }}<button class="agent-action" type="button" @click="emit('reload-resources')">重新加载配置</button></p>
    <p v-if="error" class="agent-editor-feedback error" role="alert">{{ error }}</p><p v-else-if="message && !dirty" class="agent-editor-feedback success" role="status">{{ message }}</p>
    <div class="agent-editor-layout">
      <nav ref="navigation" class="editor-nav" aria-label="智能体配置分区"><span class="agent-nav-caption">配置目录</span><button v-for="section in sections" :key="section.id" type="button" :class="{ active: activeSection === section.id }" :aria-current="activeSection === section.id ? 'location' : undefined" @click="jump(section.id)"><AppIcon :name="section.icon" /><span class="agent-nav-copy"><strong>{{ section.label }}</strong><small>{{ summaries[section.id] }}</small></span><i v-if="changedSections[section.id]" class="agent-change-dot" aria-label="此栏目有修改"></i></button><span class="agent-nav-end"><AppIcon name="check" />八个栏目连续滚动</span></nav>
      <div ref="content" class="editor-scroll" @scroll.passive="trackSection"><div class="editor-sections">
        <section id="agent-basic" data-agent-section="basic" class="agent-config-section"><header class="agent-section-heading"><h2>基本信息</h2><span v-if="changedSections.basic" class="agent-modified">已修改</span></header><div class="agent-basic-grid"><div class="agent-basic-meta">
          <div class="agent-field"><div class="agent-field-label"><label for="agent-name">名称</label><FieldHelp label="名称" :text="agentHelp.name" /></div><input id="agent-name" :value="form.name" :readonly="readonly" :disabled="busy" required placeholder="给智能体起一个名字" @input="update('name', $event.target.value)" /></div>
          <div class="agent-field"><div class="agent-field-label"><label for="agent-description">描述</label><FieldHelp label="描述" :text="agentHelp.description" /></div><textarea id="agent-description" :value="form.description" :readonly="readonly" :disabled="busy" rows="3" placeholder="它可以帮你做什么？" @input="update('description', $event.target.value)" /></div>
          <div v-if="agentId" class="agent-record-id"><span>ID</span><code>{{ agentId }}</code></div>
        </div><div class="agent-prompt"><div class="agent-field"><div class="agent-field-label"><label for="agent-instructions">系统提示词</label><FieldHelp label="系统提示词" :text="agentHelp.instructions" /></div><textarea id="agent-instructions" :value="form.instructions" :readonly="readonly" :disabled="busy" rows="10" placeholder="描述它的角色、任务和回答要求" @input="update('instructions', $event.target.value)" /></div><div class="agent-prompt-footer"><span>系统指令</span><span>{{ form.instructions?.length || 0 }} 字符</span></div></div></div></section>
        <section id="agent-plugins" data-agent-section="plugins" class="agent-config-section agent-plugin-section"><header class="agent-section-heading"><h2>能力编排</h2><span v-if="changedSections.plugins" class="agent-modified">已修改</span></header><PluginConfig v-if="pluginCatalog && !resourcesDisabled" :catalog-data="pluginCatalog" :model-value="form.plugins || {}" :saved-value="savedPlugins" :model-label="modelLabel" :disabled="readonly || busy || resourcesDisabled" @update:model-value="update('plugins', $event)"><template #model><AgentModelFields :model-id="form.model_id" :fast-model-id="form.fast_model_id" :models="models" :disabled="readonly || busy || resourcesDisabled" @update:model-id="update('model_id', $event)" @update:fast-model-id="update('fast_model_id', $event)" /></template></PluginConfig></section>
        <section id="agent-memory" data-agent-section="memory" class="agent-config-section"><header class="agent-section-heading"><h2>记忆</h2><span v-if="changedSections.memory" class="agent-modified">已修改</span></header><div class="agent-memory-grid"><div v-for="[key, label, icon] in [['recall', '检索历史记忆', 'history'], ['auto_write', '自动保存记忆', 'file']]" :key="key" class="agent-setting-row"><div><AppIcon :name="icon" /><span :id="`agent-memory-${key}`">{{ label }}</span><FieldHelp :label="label" :text="agentHelp[key]" /></div><button class="agent-switch" type="button" role="switch" :aria-labelledby="`agent-memory-${key}`" :aria-checked="Boolean(form.memory?.[key])" :disabled="choicesDisabled" @click="update('memory', { ...form.memory, [key]: !form.memory?.[key] })"></button></div></div><div class="agent-field"><div class="agent-field-label"><span>记忆范围</span><FieldHelp label="记忆范围" :text="agentHelp.scope" /></div><div class="agent-choice-group" role="group" aria-label="记忆范围"><button v-for="[value, label, icon] in [['agent', '当前智能体', 'agent'], ['session', '当前会话', 'chat'], ['principal', '当前用户', 'user']]" :key="value" type="button" :aria-pressed="(form.memory?.scope || 'agent') === value" :disabled="choicesDisabled" @click="update('memory', { ...form.memory, scope: value })"><AppIcon :name="icon" />{{ label }}<AppIcon v-if="(form.memory?.scope || 'agent') === value" name="check" /></button></div></div></section>
        <section id="agent-budgets" data-agent-section="budgets" class="agent-config-section"><header class="agent-section-heading"><h2>运行预算</h2><span v-if="changedSections.budgets" class="agent-modified">已修改</span></header><div class="agent-budget-grid"><div v-for="field in budgetFields.slice(0, 3)" :key="field.key" class="agent-field"><div class="agent-field-label"><label :for="`agent-budget-${field.key}`">{{ field.label }}</label><FieldHelp :label="field.label" :text="field.help" /></div><div class="agent-unit-input"><input :id="`agent-budget-${field.key}`" type="number" :min="field.min" :max="field.max" :step="field.step || 1" :value="form.budgets?.[field.key]" :readonly="readonly" :disabled="busy" placeholder="跟随默认" @input="updateBudget(field.key, $event.target.value)" /><span>{{ field.unit }}</span></div></div></div><details class="agent-subsection"><summary>更多 Token 边界<span>4 项</span><AppIcon name="chevron" /></summary><div class="agent-budget-grid"><div v-for="field in budgetFields.slice(3)" :key="field.key" class="agent-field"><div class="agent-field-label"><label :for="`agent-budget-${field.key}`">{{ field.label }}</label><FieldHelp :label="field.label" :text="field.help" /></div><div class="agent-unit-input"><input :id="`agent-budget-${field.key}`" type="number" :min="field.min" step="1" :value="form.budgets?.[field.key]" :readonly="readonly" :disabled="busy" placeholder="跟随默认" @input="updateBudget(field.key, $event.target.value)" /><span>{{ field.unit }}</span></div></div></div></details></section>
        <section id="agent-tools" data-agent-section="tools" class="agent-config-section"><header class="agent-section-heading"><h2>可用工具</h2><span class="agent-selection-count">{{ form.tools?.length || 0 }} 已选</span><span v-if="changedSections.tools" class="agent-modified">已修改</span></header><div class="agent-selection-toolbar"><label class="agent-search"><AppIcon name="search" /><input v-model="toolSearch" type="search" placeholder="搜索工具名称或用途" aria-label="搜索工具" /></label><select v-model="toolCategory" aria-label="工具分类"><option value="">全部分类</option><option v-for="[value, label] in categories" :key="value" :value="value">{{ label }}</option></select><button class="agent-filter-button" type="button" :aria-pressed="onlySelectedTools" @click="onlySelectedTools = !onlySelectedTools">仅已选 {{ form.tools?.length || 0 }}</button><template v-if="!readonly"><button class="agent-text-button" type="button" :disabled="busy || resourcesDisabled" @click="selectTools(true)">全选当前结果</button><button class="agent-text-button" type="button" :disabled="busy || resourcesDisabled" @click="selectTools(false)">取消当前结果</button></template></div><div class="agent-tool-grid"><label v-for="tool in displayedTools" :key="tool.name" class="agent-select-row" :class="{ selected: form.tools?.includes(tool.name) }"><input type="checkbox" :checked="form.tools?.includes(tool.name)" :disabled="choicesDisabled" @change="toggleTool(tool.name)" /><span><strong>{{ tool.presentation.title }}</strong><code>{{ tool.name }}</code><small>{{ tool.presentation.description }}</small></span><span class="agent-row-category">{{ tool.presentation.category }}</span></label></div><div v-if="!displayedTools.length" class="agent-inline-empty">没有匹配的工具<button class="agent-text-button" type="button" @click="toolSearch = ''; toolCategory = ''; onlySelectedTools = false">清除筛选</button></div><div v-for="name in unavailableTools" :key="name" class="agent-unavailable-selection"><code>{{ name }}</code><span>当前不可用</span><button v-if="!readonly" class="agent-text-button" type="button" :disabled="busy || resourcesDisabled" @click="toggleTool(name)">取消授权</button></div><p v-if="!form.tools?.length" class="agent-context-note">未选择时使用服务端默认工具。</p><details class="agent-subsection" open><summary>外部工具<span>{{ form.external_tools?.length || 0 }} 已授权</span><FieldHelp label="外部工具授权" :text="agentHelp.external" /><AppIcon name="chevron" /></summary><p class="agent-context-note">仅允许所选工具。未选择时禁用外部工具，后续新增工具需单独勾选授权。</p><div v-if="availableExternalTools.length" class="agent-external-list"><label v-for="name in availableExternalTools" :key="name" class="agent-select-row"><input type="checkbox" :checked="form.external_tools?.includes(name)" :disabled="choicesDisabled" @change="toggleExternalTool(name)" /><span><code>{{ name }}</code><small v-if="!externalTools.includes(name)">当前不可用，可取消授权</small></span></label></div><p v-else class="agent-inline-empty">暂无外部工具，请先在工具页面添加连接并刷新工具。</p></details></section>
        <section id="agent-skills" data-agent-section="skills" class="agent-config-section"><header class="agent-section-heading"><h2>可用技能</h2><span class="agent-selection-count">{{ selectedSkills.length }} 已选</span><span v-if="changedSections.skills" class="agent-modified">已修改</span></header><div class="agent-selection-toolbar"><label class="agent-search"><AppIcon name="search" /><input v-model="skillSearch" type="search" placeholder="搜索技能名称或用途" aria-label="搜索技能" /></label><button class="agent-filter-button" type="button" :aria-pressed="onlySelectedSkills" @click="onlySelectedSkills = !onlySelectedSkills">仅已选 {{ selectedSkills.length }}</button></div><div class="agent-skill-grid"><label v-for="skill in displayedSkills" :key="skill.skill_id || skill.name" class="agent-skill-item" :class="{ selected: selectedSkills.includes(skill.name) }"><input type="checkbox" :checked="selectedSkills.includes(skill.name)" :disabled="choicesDisabled" @change="toggleSkill(skill.name)" /><span class="agent-skill-symbol"><AppIcon name="skill" /></span><span><strong>{{ skill.name }}</strong><small>{{ skill.description }}</small></span></label></div><div v-if="!displayedSkills.length" class="agent-inline-empty">没有匹配的技能<button class="agent-text-button" type="button" @click="skillSearch = ''; onlySelectedSkills = false">清除筛选</button></div><div v-for="name in unavailableSkills" :key="name" class="agent-unavailable-selection"><code>{{ name }}</code><span>当前不可用</span><button v-if="!readonly" class="agent-text-button" type="button" :disabled="busy || resourcesDisabled" @click="toggleSkill(name)">取消选择</button></div></section>
        <section id="agent-approval" data-agent-section="approval" class="agent-config-section"><p v-if="approvalLoading" role="status">正在加载工具审批选项…</p><p v-else-if="approvalError" class="error" role="alert">{{ approvalError }}<button type="button" class="agent-action" @click="emit('load-approval-tools')">重新加载</button></p><header class="agent-section-heading"><h2>工具审批</h2><span v-if="changedSections.approval" class="agent-modified">已修改</span></header><div class="agent-field"><div class="agent-field-label"><span>默认审批模式</span><FieldHelp label="默认审批模式" :text="agentHelp.approval" /></div><div class="agent-choice-group" role="group" aria-label="默认审批模式"><span v-if="!form.tool_approval" class="agent-legacy-value">沿用旧配置</span><button v-for="[value, label, icon] in [['ask', '需要询问', 'shield'], ['auto_approve', '免审批', 'check']]" :key="value" type="button" :aria-pressed="form.tool_approval?.default === value" :disabled="choicesDisabled" @click="setApprovalDefault(value)"><AppIcon :name="icon" />{{ label }}<AppIcon v-if="form.tool_approval?.default === value" name="check" /></button></div></div><details v-if="form.tool_approval" class="agent-subsection" open><summary>逐工具审批规则<span>{{ approvalOverrideCount }} 项自定义</span><AppIcon name="chevron" /></summary><div class="agent-selection-toolbar"><label class="agent-search"><AppIcon name="search" /><input v-model="approvalSearch" type="search" placeholder="搜索审批规则" aria-label="搜索审批规则" /></label><button class="agent-filter-button" type="button" :aria-pressed="onlyApprovalOverrides" @click="onlyApprovalOverrides = !onlyApprovalOverrides">仅自定义 {{ approvalOverrideCount }}</button></div><div v-for="tool in displayedApprovalRules" :key="tool.key" class="agent-approval-row"><span>{{ tool.title }}<code>{{ tool.name }}</code></span><select :aria-label="`${tool.name} 审批模式`" :value="form.tool_approval.tools?.[tool.key] || 'inherit'" :disabled="choicesDisabled" @change="setToolApproval(tool.key, $event.target.value)"><option value="inherit">继承默认</option><option value="ask">需要询问</option><option value="auto_approve">免审批</option></select></div><p v-if="!displayedApprovalRules.length" class="agent-inline-empty">没有匹配的审批规则</p></details></section>
        <section id="agent-execution" data-agent-section="execution" class="agent-config-section"><header class="agent-section-heading"><h2>执行权限</h2><span v-if="changedSections.execution" class="agent-modified">已修改</span></header><div class="agent-permission-grid"><div class="agent-field"><div class="agent-field-label"><label for="agent-shell">命令权限上限</label><FieldHelp label="命令权限上限" :text="agentHelp.shell" /></div><select id="agent-shell" :value="form.execution_policy?.shell || 'sandboxed'" :disabled="disabled" @change="update('execution_policy', { ...form.execution_policy, shell: $event.target.value })"><option value="sandboxed">允许用户设置工作区内自动执行</option><option value="ask">命令必须审批</option><option value="deny">禁止命令执行</option></select></div><div class="agent-field"><div class="agent-field-label"><label for="agent-network">沙箱网络</label><FieldHelp label="沙箱网络" :text="agentHelp.network" /></div><select id="agent-network" :value="form.sandbox?.network || 'none'" :disabled="disabled" @change="update('sandbox', { ...form.sandbox, network: $event.target.value })"><option value="none">禁止联网</option><option value="unrestricted">允许联网</option></select></div></div><div v-if="canDelete && !readonly" class="agent-danger-zone"><button class="agent-text-button danger" type="button" :disabled="busy" @click="emit('delete')"><AppIcon name="trash" />删除智能体</button></div></section>
        <footer class="agent-document-end"><AppIcon name="check" />已到最后一个栏目<button class="agent-text-button" type="button" @click="jump('basic')">返回基本信息</button></footer>
      </div></div>
    </div>
    <FormDrawer v-model="leaveOpen" centered panel-class="agent-confirm-dialog" title="保留这次修改？" :busy="busy"><p class="agent-confirm-copy">有尚未保存的配置。</p><div class="agent-confirm-actions"><button class="agent-action" type="button" @click="leaveOpen = false">继续编辑</button><button class="agent-action" type="button" @click="discardAndClose">放弃修改</button><button class="agent-action primary" type="button" :disabled="busy || resourcesDisabled || !form.name?.trim()" @click="submit(true)">保存并返回</button></div></FormDrawer>
  </div>
</template>
<style src="../agent-surfaces.css"></style>
