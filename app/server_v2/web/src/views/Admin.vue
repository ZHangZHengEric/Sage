<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'
import { messagesFromEvents } from '../agui/replay.js'
import AguiTranscript from '../components/AguiTranscript.vue'

const users = ref([])
const threads = ref([])
const models = ref([])
const selected = ref('')
const error = ref('')
const jaeger = ref(false)
const rawEvents = ref([])
const messages = computed(() => messagesFromEvents(rawEvents.value))

async function load() {
  const health = await api.health()
  jaeger.value = health?.backends?.trace === 'otlp'
  users.value = await api.adminUsers()
  threads.value = await api.adminThreads()
  models.value = await api.adminModels()
}

async function openThread(id) {
  selected.value = id
  rawEvents.value = await api.adminThreadEvents(id)
}

onMounted(async () => {
  try {
    await load()
  } catch (exc) {
    error.value = exc.message
  }
})
</script>

<template>
  <section>
    <header class="page-head">
      <h1>总览</h1>
      <p v-if="jaeger">
        <a class="btn ghost" href="/api/observability/jaeger">打开 Jaeger</a>
      </p>
    </header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div class="panel">
      <h2>用户</h2>
      <p v-if="!users.length" class="empty">还没有用户</p>
      <table v-else>
        <thead><tr><th>用户名</th><th>角色</th><th>ID</th></tr></thead>
        <tbody>
          <tr v-for="user in users" :key="user.user_id">
            <td>{{ user.username }}</td>
            <td>{{ user.role }}</td>
            <td class="mono">{{ user.user_id }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel stack">
      <h2>模型</h2>
      <p v-if="!models.length" class="empty">还没有模型</p>
      <table v-else>
        <thead><tr><th>用户</th><th>模型</th><th>协议</th></tr></thead>
        <tbody>
          <tr v-for="item in models" :key="item.id + item.user_id">
            <td>{{ item.username }}</td>
            <td>{{ item.model }}</td>
            <td class="mono">{{ item.protocol }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel stack">
      <h2>会话</h2>
      <p v-if="!threads.length" class="empty">还没有会话</p>
      <button
        v-for="item in threads"
        :key="item.thread_id"
        class="thread"
        type="button"
        :class="{ active: selected === item.thread_id }"
        @click="openThread(item.thread_id)"
      >
        <span>{{ item.username }} / {{ item.title || '未命名' }}</span>
        <small>{{ item.thread_id }}</small>
      </button>
      <AguiTranscript
        v-if="selected"
        class="admin-transcript"
        :messages="messages"
      />
    </div>
  </section>
</template>
