<script setup>
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
const props = defineProps({
  form: { type: Object, required: true },
  agentId: String, readonly: Boolean, canEdit: Boolean, busy: Boolean, error: String, message: String,
  models: { type: Array, default: () => [] }, tools: { type: Array, default: () => [] },
  skills: { type: Array, default: () => [] }, selectedSkills: { type: Array, default: () => [] },
  externalTools: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'edit', 'save', 'update:form', 'update:selectedSkills'])
const activeSection = ref('basic'), content = ref(null), toolCategory = ref('')
const toolSearch = ref(''), skillSearch = ref('')
const sections = [
  { id: 'basic', label: '基本信息', icon: 'user' },
  { id: 'model', label: '模型配置', icon: 'model' },
  { id: 'tools', label: '可用工具', icon: 'tools' },
  { id: 'skills', label: '可用技能', icon: 'skill' },
  { id: 'execution', label: '执行权限', icon: 'settings' },
]
const categories = computed(() => [...new Set(props.tools.map(tool => tool.category).filter(Boolean))])
const displayedTools = computed(() => props.tools.filter(tool => (!toolCategory.value || tool.category === toolCategory.value) && tool.name.toLowerCase().includes(toolSearch.value.toLowerCase())))
const displayedSkills = computed(() => props.skills.filter(skill => `${skill.name} ${skill.description || ''}`.toLowerCase().includes(skillSearch.value.toLowerCase())))
function jump(id) {
  activeSection.value = id
  content.value?.querySelector(`#agent-${id}`)?.scrollIntoView({ block: 'start', behavior: 'instant' })
}
function trackSection() {
  if (!content.value) return
  const top = content.value.getBoundingClientRect().top
  for (const section of sections) {
    if (content.value.querySelector(`#agent-${section.id}`)?.getBoundingClientRect().top <= top + 100) activeSection.value = section.id
  }
}
function update(key, value) { if (!props.readonly) emit('update:form', { ...props.form, [key]: value }) }
function toggleTool(name) {
  const selected = new Set(props.form.tools)
  if (selected.has(name)) selected.delete(name); else selected.add(name)
  update('tools', [...selected])
}
function selectTools(select) {
  const selected = new Set(props.form.tools)
  for (const tool of displayedTools.value) { if (select) selected.add(tool.name); else selected.delete(tool.name) }
  update('tools', [...selected])
}
function toggleSkill(name) {
  if (props.readonly) return
  const selected = new Set(props.selectedSkills)
  if (selected.has(name)) selected.delete(name); else selected.add(name)
  emit('update:selectedSkills', [...selected])
}
</script>
<template>
  <div class="agent-editor">
    <header class="agent-editor-head">
      <div class="editor-title"><button class="icon-button" aria-label="返回智能体列表" :disabled="busy" @click="emit('close')"><AppIcon class="back-icon" name="chevron" /></button><h1>{{ readonly ? '查看智能体' : agentId ? '编辑智能体' : '创建智能体' }}</h1><span>{{ form.name || '未命名' }}</span></div>
      <div class="page-actions"><button v-if="readonly && canEdit" class="btn" @click="emit('edit')">编辑</button><template v-if="!readonly"><button class="btn ghost" :disabled="busy || !form.name.trim()" @click="emit('save', false)">保存</button><button class="btn" :disabled="busy || !form.name.trim()" @click="emit('save', true)">{{ busy ? '保存中…' : '保存并退出' }}</button></template></div>
    </header>
    <p v-if="error" class="editor-feedback error" role="alert">{{ error }}</p><p v-if="message" class="editor-feedback" role="status">{{ message }}</p>
    <div class="agent-editor-layout">
      <nav class="editor-nav" aria-label="智能体配置分区"><button v-for="section in sections" :key="section.id" :class="{ active: activeSection === section.id }" @click="jump(section.id)"><AppIcon :name="section.icon" />{{ section.label }}</button></nav>
      <div ref="content" class="editor-scroll" @scroll="trackSection">
        <div class="editor-sections">
          <section id="agent-basic"><h2><span class="section-icon"><AppIcon name="user" /></span>基本信息</h2><div class="section-fields">
            <label class="field"><span>名称</span><input :value="form.name" :readonly="readonly" :disabled="busy" required @input="update('name', $event.target.value)" /></label>
            <label class="field"><span>描述</span><textarea :value="form.description" :readonly="readonly" :disabled="busy" rows="3" @input="update('description', $event.target.value)" /></label>
            <label class="field"><span>系统提示词</span><textarea class="mono" :value="form.instructions" :readonly="readonly" :disabled="busy" rows="10" @input="update('instructions', $event.target.value)" /></label>
          </div></section>
          <section id="agent-model"><h2><span class="section-icon"><AppIcon name="model" /></span>模型配置</h2><div class="section-fields"><label class="field"><span>模型</span><select :value="form.model_id" :disabled="readonly || busy" @change="update('model_id', $event.target.value)"><option value="">使用默认模型</option><option v-if="form.model_id && !models.some(model => model.id === form.model_id)" :value="form.model_id">{{ form.model_id }}</option><option v-for="model in models" :key="model.id" :value="model.id">{{ model.model }}</option></select></label></div></section>
          <section id="agent-tools"><h2><span class="section-icon"><AppIcon name="tools" /></span>可用工具<span class="selection-count">{{ form.tools.length }}</span></h2><div class="section-fields">
            <div v-if="form.tools.length" class="selected-tags"><span v-for="name in form.tools" :key="name" class="tag">{{ name }}</span></div>
            <div class="selection-box"><div class="selection-toolbar"><select v-model="toolCategory" aria-label="工具分类"><option value="">全部工具</option><option v-for="category in categories" :key="category">{{ category }}</option></select><input v-model="toolSearch" placeholder="搜索工具" aria-label="搜索工具" /><template v-if="!readonly"><button class="btn ghost" :disabled="busy" @click="selectTools(true)">全选</button><button class="btn ghost" :disabled="busy" @click="selectTools(false)">取消全选</button></template></div>
              <div class="selection-list"><label v-for="tool in displayedTools" :key="tool.name" class="selection-row"><input type="checkbox" :checked="form.tools.includes(tool.name)" :disabled="readonly || busy" @change="toggleTool(tool.name)" /><span>{{ tool.name }}<small>{{ tool.category }}</small></span></label><p v-if="!displayedTools.length" class="empty">没有匹配的工具</p></div>
            </div>
            <p v-if="!form.tools.length" class="muted field-note">未选择时使用服务端默认工具。</p>
            <div v-if="externalTools.length" class="external-tools"><h3>外部工具</h3><div class="selected-tags"><span v-for="name in externalTools" :key="name" class="tag">{{ name }}</span></div></div>
          </div></section>
          <section id="agent-skills"><h2><span class="section-icon"><AppIcon name="skill" /></span>可用技能<span class="selection-count">{{ selectedSkills.length }}</span></h2><div class="section-fields">
            <div v-if="selectedSkills.length" class="selected-tags"><span v-for="name in selectedSkills" :key="name" class="tag">{{ name }}</span></div>
            <div class="selection-box"><div class="selection-toolbar"><input v-model="skillSearch" placeholder="搜索技能" aria-label="搜索技能" /></div>
              <div class="selection-list"><label v-for="skill in displayedSkills" :key="skill.skill_id || skill.name" class="selection-row"><input type="checkbox" :checked="selectedSkills.includes(skill.name)" :disabled="readonly || busy" @change="toggleSkill(skill.name)" /><span>{{ skill.name }}<small>{{ skill.description }}</small></span></label><p v-if="!displayedSkills.length" class="empty">没有匹配的技能</p></div>
            </div>
          </div></section>
          <section id="agent-execution"><h2><span class="section-icon"><AppIcon name="settings" /></span>执行权限</h2><div class="section-fields"><label class="field"><span>命令权限上限</span><select :value="form.execution_policy.shell" :disabled="readonly || busy" @change="update('execution_policy', { ...form.execution_policy, shell: $event.target.value })"><option value="sandboxed">允许用户设置工作区内自动执行</option><option value="ask">命令必须审批</option><option value="deny">禁止命令执行</option></select></label></div></section>
        </div>
      </div>
    </div>
  </div>
</template>
<style scoped>
.agent-editor { display: flex; flex-direction: column; height: 100%; min-height: 0; border: 1px solid var(--border); background: var(--background); overflow: hidden; }
.agent-editor-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 16px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
.editor-title { display: flex; align-items: center; gap: 8px; min-width: 0; }
.editor-title h1 { font-size: 14px; font-weight: 500; margin: 0; white-space: nowrap; }
.editor-title > span { color: var(--muted-foreground); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.back-icon { transform: rotate(180deg); }
.agent-editor-head .btn { padding: 5px 12px; font-size: 12px; }
.editor-feedback { padding: 8px 16px; margin: 0; font-size: 13px; }
.agent-editor-layout { display: flex; flex: 1; min-height: 0; }
.editor-nav { flex: 0 0 192px; padding: 12px 8px; border-right: 1px solid var(--border); background: color-mix(in srgb, var(--muted) 20%, white); overflow-y: auto; }
.editor-nav button { display: flex; gap: 10px; align-items: center; width: 100%; padding: 10px 12px; font-size: 12px; background: transparent; color: var(--muted-foreground); border: 0; border-radius: 6px; text-align: left; }
.editor-nav button.active { background: color-mix(in srgb, var(--primary) 10%, white); color: var(--primary); font-weight: 500; }
.editor-nav .app-icon { width: 14px; height: 14px; }
.editor-scroll { flex: 1; min-width: 0; overflow-y: auto; }
.editor-sections { width: 100%; padding: 32px; }
.editor-sections > section { margin-bottom: 40px; scroll-margin-top: 24px; }
.editor-sections h2 { display: flex; align-items: center; gap: 8px; font-size: 16px; margin: 0 0 20px; }
.section-icon { width: 32px; height: 32px; border-radius: 8px; display: grid; place-items: center; background: color-mix(in srgb, var(--primary) 10%, white); }
.section-fields { padding-left: 40px; }
.field { gap: 8px; margin-bottom: 20px; }
.field > span { color: var(--foreground); font-size: 13px; }
.field input, .field select, .field textarea { font-size: 14px; padding: 10px 12px; }
.field input:read-only, .field textarea:read-only { background: color-mix(in srgb, var(--muted) 30%, white); }
.field textarea { resize: vertical; }
.selection-count { margin-left: auto; color: var(--muted-foreground); font-size: 12px; font-weight: 400; }
.selected-tags { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.selected-tags .tag { margin: 0; border-radius: 6px; padding: 3px 8px; overflow-wrap: anywhere; }
.selection-box { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.selection-toolbar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; padding: 12px; background: color-mix(in srgb, var(--muted) 30%, white); border-bottom: 1px solid var(--border); }
.selection-toolbar input { flex: 1; min-width: 120px; width: 120px; }
.selection-toolbar input, .selection-toolbar select { padding: 6px 8px; font-size: 12px; }
.selection-toolbar .btn { font-size: 12px; padding: 5px 8px; }
.selection-list { max-height: 320px; overflow-y: auto; padding: 12px; }
.selection-row { display: flex; align-items: flex-start; gap: 12px; padding: 12px; margin-bottom: 8px; border: 1px solid var(--border); border-radius: 8px; font-size: 13px; overflow-wrap: anywhere; }
.selection-row input { margin-top: 4px; flex-shrink: 0; }
.selection-row small { display: block; color: var(--muted-foreground); margin-top: 4px; font-size: 12px; }
.field-note { margin-top: 8px; font-size: 12px; }
.external-tools h3 { font-size: 13px; margin-top: 20px; }
@media (max-width: 900px) { .editor-nav { flex-basis: 140px; } .editor-sections { padding: 24px 16px; } .section-fields { padding-left: 0; } }
@media (max-width: 640px) { .agent-editor-head { flex-wrap: wrap; } .editor-title > span { display: none; } .agent-editor-layout { flex-direction: column; } .editor-nav { display: flex; flex: 0 0 auto; overflow-x: auto; padding: 6px; border-right: 0; border-bottom: 1px solid var(--border); } .editor-nav button { width: auto; white-space: nowrap; } }
</style>
