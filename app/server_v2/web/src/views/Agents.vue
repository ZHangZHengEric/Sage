<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'

const agents = ref([])
const models = ref([])
const mcp = ref([])
const skills = ref([])
const bound = ref([])
const error = ref('')
const pending = ref(false)
const editing = ref('')
const form = ref(emptyForm())

const hasAgents = computed(() => agents.value.length > 0)
const mcpTools = computed(() => [...new Set(mcp.value.flatMap((item) => item.tools || []))])
const boundNames = computed(() => new Set(bound.value.map((item) => item.name)))

function emptyForm() {
  return {
    name: '',
    description: '',
    instructions: 'Be helpful, concise, and explicit about uncertainty.',
    model_id: '',
    tools: [],
  }
}

async function refresh() {
  const [nextAgents, nextModels, nextMcp, nextSkills] = await Promise.all([
    api.listAgents(),
    api.listModels(),
    api.listMcp(),
    api.listSkills(),
  ])
  agents.value = nextAgents
  models.value = nextModels
  mcp.value = nextMcp
  skills.value = nextSkills
  if (editing.value) {
    bound.value = await api.listAgentSkills(editing.value)
  }
}

async function save() {
  error.value = ''
  pending.value = true
  try {
    const payload = { ...form.value }
    const saved = editing.value
      ? await api.updateAgent(editing.value, payload)
      : await api.createAgent(payload)
    editing.value = saved.id
    await refresh()
  } catch (exc) {
    error.value = exc.message
  } finally {
    pending.value = false
  }
}

async function edit(item) {
  const detail = await api.getAgent(item.id)
  editing.value = item.id
  form.value = {
    name: detail.name,
    description: detail.description || '',
    instructions: detail.instructions || '',
    model_id: detail.model_id || '',
    tools: [...(detail.tools || [])],
  }
  bound.value = await api.listAgentSkills(item.id)
}

function startNew() {
  editing.value = ''
  form.value = emptyForm()
  bound.value = []
}

async function remove(id) {
  await api.deleteAgent(id)
  if (editing.value === id) startNew()
  await refresh()
}

function toggleTool(name) {
  const current = new Set(form.value.tools)
  if (current.has(name)) current.delete(name)
  else current.add(name)
  form.value.tools = [...current]
}

async function toggleSkill(item) {
  if (!editing.value) {
    error.value = '请先保存智能体，再关联技能'
    return
  }
  const names = bound.value.map((skill) => skill.name)
  const next = names.includes(item.name)
    ? names.filter((name) => name !== item.name)
    : [...names, item.name]
  await api.bindAgentSkills(editing.value, next)
  bound.value = await api.listAgentSkills(editing.value)
  await refresh()
}

onMounted(async () => {
  try {
    await refresh()
  } catch (exc) {
    error.value = exc.message
  }
})
</script>

<template>
  <section>
    <header class="page-head">
      <h1>智能体</h1>
    </header>
    <form class="panel" @submit.prevent="save">
      <label class="field">
        <span>名称</span>
        <input v-model="form.name" required />
      </label>
      <label class="field">
        <span>描述</span>
        <input v-model="form.description" />
      </label>
      <label class="field">
        <span>提示词</span>
        <textarea v-model="form.instructions" rows="6" />
      </label>
      <label class="field">
        <span>模型</span>
        <select v-model="form.model_id">
          <option value="">使用默认模型</option>
          <option v-for="item in models" :key="item.id" :value="item.id">
            {{ item.model }}
          </option>
        </select>
      </label>
      <div v-if="mcpTools.length" class="field">
        <span>MCP 工具</span>
        <label v-for="name in mcpTools" :key="name" class="row">
          <input
            type="checkbox"
            :checked="form.tools.includes(name)"
            @change="toggleTool(name)"
          />
          {{ name }}
        </label>
      </div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="row">
        <button class="btn cta" type="submit" :disabled="pending">
          {{ editing ? '保存智能体' : '新建智能体' }}
        </button>
        <button v-if="editing" class="btn ghost" type="button" @click="startNew">新建另一份</button>
      </div>
    </form>
    <div v-if="editing && skills.length" class="panel stack">
      <h2>关联技能</h2>
      <label v-for="item in skills" :key="item.skill_id" class="row">
        <input
          type="checkbox"
          :checked="boundNames.has(item.name)"
          @change="toggleSkill(item)"
        />
        {{ item.name }}
        <span class="muted">{{ item.description }}</span>
      </label>
    </div>
    <div class="panel stack">
      <h2>已配置</h2>
      <p v-if="!hasAgents" class="empty">还没有智能体</p>
      <table v-else>
        <thead>
          <tr><th>智能体</th><th>模型</th><th>工具 / 技能</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="item in agents" :key="item.id">
            <td>
              {{ item.name }}
              <div class="muted">{{ item.description || item.id }}</div>
            </td>
            <td class="mono">{{ item.model_id || '默认' }}</td>
            <td class="muted">{{ item.tools.length }} 工具 · {{ item.skills.length }} 技能</td>
            <td class="row">
              <button class="btn ghost" type="button" @click="edit(item)">编辑</button>
              <button class="btn ghost" type="button" @click="remove(item.id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
