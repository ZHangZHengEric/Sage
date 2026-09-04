<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'

const skills = ref([])
const agents = ref([])
const agentId = ref(localStorage.getItem('sage.server_v2.agent') || 'main')
const bound = ref([])
const error = ref('')
const pending = ref(false)
const editing = ref('')
const form = ref({
  name: '',
  content: '---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n\nFollow this skill.\n',
})

const hasSkills = computed(() => skills.value.length > 0)
const boundNames = computed(() => new Set(bound.value.map((item) => item.name)))

async function refresh() {
  const [nextSkills, nextAgents] = await Promise.all([api.listSkills(), api.listAgents()])
  skills.value = nextSkills
  agents.value = nextAgents
  if (!agents.value.some((item) => item.id === agentId.value)) {
    agentId.value = agents.value[0]?.id || 'main'
  }
  bound.value = await api.listAgentSkills(agentId.value)
}

function changeAgent() {
  localStorage.setItem('sage.server_v2.agent', agentId.value)
  refresh()
}

async function save() {
  error.value = ''
  pending.value = true
  try {
    if (editing.value) {
      await api.updateSkill(editing.value, { content: form.value.content })
    } else {
      await api.publishSkill({ name: form.value.name, content: form.value.content })
    }
    editing.value = ''
    form.value = {
      name: '',
      content: '---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n\nFollow this skill.\n',
    }
    await refresh()
  } catch (exc) {
    error.value = exc.message
  } finally {
    pending.value = false
  }
}

async function edit(item) {
  const detail = await api.getSkill(item.skill_id)
  editing.value = item.skill_id
  form.value = { name: item.name, content: detail.content || '' }
}

async function remove(id) {
  await api.deleteSkill(id)
  await refresh()
}

async function toggleBind(item) {
  const names = bound.value.map((skill) => skill.name)
  const next = names.includes(item.name)
    ? names.filter((name) => name !== item.name)
    : [...names, item.name]
  await api.bindAgentSkills(agentId.value, next)
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
      <h1>技能</h1>
      <label class="field" style="margin:0;min-width:12rem">
        <span>关联到智能体</span>
        <select v-model="agentId" @change="changeAgent">
          <option v-for="item in agents" :key="item.id" :value="item.id">
            {{ item.name }}
          </option>
        </select>
      </label>
    </header>
    <form class="panel" @submit.prevent="save">
      <label class="field">
        <span>名称</span>
        <input v-model="form.name" :disabled="Boolean(editing)" required />
      </label>
      <label class="field">
        <span>SKILL.md</span>
        <textarea v-model="form.content" rows="10" required />
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="btn cta" type="submit" :disabled="pending">
        {{ editing ? '保存新版本' : '发布技能' }}
      </button>
    </form>
    <div class="panel stack">
      <h2>已发布</h2>
      <p v-if="!hasSkills" class="empty">还没有技能。发布后勾选即可给对话使用，未修改时不会拷到工作区。</p>
      <table v-else>
        <thead>
          <tr><th>技能</th><th>路径</th><th>对话</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="item in skills" :key="item.skill_id">
            <td>
              {{ item.name }}
              <div class="muted">{{ item.description }}</div>
            </td>
            <td class="mono">{{ item.artifact_path }}</td>
            <td>
              <label>
                <input
                  type="checkbox"
                  :checked="boundNames.has(item.name)"
                  @change="toggleBind(item)"
                />
                关联 main
              </label>
            </td>
            <td class="row">
              <button class="btn ghost" type="button" @click="edit(item)">编辑</button>
              <button class="btn ghost" type="button" @click="remove(item.skill_id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
