<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
const users = ref([]), error = ref(''), loading = ref(true)
onMounted(async () => {
  try { users.value = await api.adminUsers() } catch (exc) { error.value = exc.message }
  finally { loading.value = false }
})
</script>
<template>
  <section><header class="page-head"><h1>用户列表</h1></header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="loading" class="page-loading" role="status">加载中…</p>
    <div v-else class="panel table-panel"><table><thead><tr><th>用户名</th><th>角色</th><th>用户 ID</th></tr></thead><tbody><tr v-for="user in users" :key="user.user_id"><td>{{ user.username }}</td><td><span class="tag">{{ user.role === 'admin' ? '管理员' : '用户' }}</span></td><td class="mono">{{ user.user_id }}</td></tr></tbody></table></div>
  </section>
</template>
