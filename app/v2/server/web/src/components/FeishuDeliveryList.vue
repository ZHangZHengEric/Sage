<script setup>
import { deliveryStates } from '../use-im-connection.js'
import FieldHelp from './FieldHelp.vue'
defineProps({ rows: Array, loading: Boolean, error: String, cursor: Number, busy: Boolean, unresolved: Boolean })
const emit = defineEmits(['filter', 'refresh', 'more', 'retry', 'discard'])
</script>
<template>
  <section class="im-deliveries" aria-label="投递管理">
    <div class="im-section-head"><h2>投递管理</h2><div class="im-actions"><select aria-label="筛选投递状态" :value="String(unresolved)" :disabled="busy" @change="emit('filter', $event.target.value === 'true')"><option value="true">失败与未知</option><option value="false">全部投递</option></select><button class="btn ghost" type="button" :disabled="busy || loading" @click="emit('refresh')">刷新投递</button></div></div>
    <p v-if="error" class="error" role="alert">{{ error }}<button class="btn ghost" type="button" :disabled="busy || loading" @click="emit('refresh')">重试加载</button></p>
    <div v-if="rows.length" class="im-table-wrap">
      <table class="im-table"><caption class="sr-only">{{ unresolved ? '失败与未知投递' : '全部投递' }}</caption><thead><tr><th scope="col">投递</th><th scope="col">状态</th><th scope="col">尝试</th><th scope="col">回执 / 错误</th><th scope="col">操作</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>#{{ row.id }}</td><td><span class="system-badge" :class="row.state === 'unknown' ? 'amber' : row.state === 'failed' ? 'im-failed' : 'neutral'">{{ deliveryStates[row.state] || row.state }}</span><FieldHelp v-if="row.state === 'unknown'" label="结果未知" text="平台可能已接收。该投递会阻塞同一目标的后续发送；检查后重试或丢弃。" /></td><td>{{ row.attempts }}</td><td><code>{{ row.error || row.receipt || '—' }}</code></td><td><div v-if="['failed', 'unknown'].includes(row.state)" class="im-actions"><button class="btn ghost" type="button" :aria-label="`重试投递 ${row.id}`" :disabled="busy || loading" @click="emit('retry', row)">重试</button><button class="btn ghost danger" type="button" :aria-label="`丢弃投递 ${row.id}`" :disabled="busy || loading" @click="emit('discard', row)">丢弃</button></div><span v-else>—</span></td></tr></tbody></table>
    </div>
    <p v-else-if="!loading && !error" class="im-empty" role="status">{{ unresolved ? '暂无失败或未知投递' : '暂无投递记录' }}</p>
    <p v-if="loading" class="im-empty" role="status">正在加载投递…</p>
    <button v-if="cursor !== null" class="btn ghost" type="button" :disabled="busy || loading" @click="emit('more')">加载更多</button>
  </section>
</template>
