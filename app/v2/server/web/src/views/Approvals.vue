<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
import InteractionPrompt from '../components/InteractionPrompt.vue'

const items = ref([]), offset = ref(0), nextOffset = ref(null), busy = ref(false), error = ref(''), message = ref('')
async function refresh() {
  const page = await api.approvals(offset.value)
  items.value = page.items; nextOffset.value = page.next_offset
}
async function load(next = offset.value) {
  busy.value = true; error.value = ''; offset.value = next
  try { await refresh() } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function decide(item, answer) {
  busy.value = true; error.value = ''; message.value = ''
  try {
    await api.decideApproval(item.run_id, { ...answer, expected: item.expected })
    message.value = '决定已提交，任务在后台继续处理。'
    await refresh()
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
function date(value) { return new Date(value).toLocaleString() }
onMounted(() => load())
</script>

<template>
  <section>
    <header class="page-head"><h1>待审批</h1><button class="btn ghost" :disabled="busy" @click="load()">刷新</button></header>
    <p class="muted">任务已保存并暂停。处理后会重新创建执行资源，无需保持此页面打开。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="busy" role="status">处理中…</p>
    <p v-else-if="!items.length" class="panel muted">本页没有待审批操作。</p>
    <article v-for="item in items" :key="item.interaction.interaction_id" class="panel stack">
      <h2>{{ item.title }}</h2>
      <small class="muted">申请时间：{{ date(item.interaction.requested_at) }} · 有效期至：{{ date(item.expires_at) }}</small>
      <InteractionPrompt :interaction="item.interaction" :busy="busy" @decide="answer => decide(item, answer)" />
    </article>
    <div class="row">
      <button class="btn ghost" :disabled="busy || offset === 0" @click="load(Math.max(0, offset - 50))">上一页</button>
      <button class="btn ghost" :disabled="busy || nextOffset === null" @click="load(nextOffset)">下一页</button>
    </div>
  </section>
</template>
