<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'

const skills = ref([])
const agents = ref([])
const agentId = ref(localStorage.getItem('sage.server_v2.agent') || 'main')
const bound = ref([])
const error = ref('')
const pending = ref(false)
const files = ref([])
const results = ref([])
const dragging = ref(false)
const picker = ref(null)

const hasSkills = computed(() => skills.value.length > 0)
const boundNames = computed(() => new Set(bound.value.map((item) => item.name)))
const currentAgent = computed(
  () => agents.value.find((item) => item.id === agentId.value)?.name || agentId.value
)

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

function isZip(file) {
  return Boolean(file?.name?.toLowerCase().endsWith('.zip'))
}

function addFiles(list) {
  const incoming = Array.from(list || [])
  const rejected = incoming.filter((item) => !isZip(item))
  const accepted = incoming.filter(isZip)
  const seen = new Set(files.value.map((item) => `${item.name}:${item.size}`))
  for (const item of accepted) {
    const key = `${item.name}:${item.size}`
    if (seen.has(key)) continue
    seen.add(key)
    files.value.push(item)
  }
  results.value = rejected.map((item) => ({
    filename: item.name,
    success: false,
    message: '仅支持 ZIP 文件',
  }))
  error.value = accepted.length ? '' : rejected[0] ? '仅支持 ZIP 文件' : error.value
}

function onPick(event) {
  addFiles(event.target.files)
  event.target.value = ''
}

function onDrop(event) {
  dragging.value = false
  addFiles(event.dataTransfer?.files)
}

function removeFile(index) {
  files.value.splice(index, 1)
}

async function upload() {
  if (!files.value.length || pending.value) return
  error.value = ''
  pending.value = true
  try {
    const payload = await api.uploadSkills(files.value)
    results.value = payload.results || []
    files.value = []
    if (payload.failed_count) {
      error.value = `${payload.success_count} 个成功，${payload.failed_count} 个失败`
    }
    await refresh()
  } catch (exc) {
    error.value = exc.message
  } finally {
    pending.value = false
  }
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
    <div class="panel">
      <input
        ref="picker"
        class="sr-only"
        type="file"
        accept=".zip,application/zip"
        multiple
        @change="onPick"
      />
      <button
        class="dropzone"
        type="button"
        :class="{ active: dragging }"
        @click="picker?.click()"
        @dragenter.prevent="dragging = true"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <strong>批量选择 ZIP 技能包</strong>
        <span>可一次选多个，或拖到这里。每个 ZIP 需包含 SKILL.md。</span>
      </button>
      <ul v-if="files.length" class="file-list">
        <li v-for="(item, index) in files" :key="`${item.name}-${index}`">
          <span>{{ item.name }}</span>
          <button class="btn ghost" type="button" @click="removeFile(index)">移除</button>
        </li>
      </ul>
      <ul v-if="results.length" class="file-list">
        <li v-for="item in results" :key="item.filename" :class="{ fail: !item.success }">
          <span>{{ item.filename }}</span>
          <small :class="item.success ? 'muted' : 'error'">{{ item.message }}</small>
        </li>
      </ul>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="btn cta" type="button" :disabled="pending || !files.length" @click="upload">
        {{ pending ? '正在上传…' : '上传技能包' }}
      </button>
    </div>
    <div class="panel stack">
      <h2>已发布</h2>
      <p v-if="!hasSkills" class="empty">还没有技能。上传 ZIP 后勾选即可给对话使用，未修改时不会拷到工作区。</p>
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
                关联 {{ currentAgent }}
              </label>
            </td>
            <td class="row">
              <button class="btn ghost" type="button" @click="remove(item.skill_id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
