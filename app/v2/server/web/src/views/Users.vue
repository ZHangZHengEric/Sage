<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
import FormDrawer from '../components/FormDrawer.vue'
const users = ref([]), error = ref(''), loading = ref(true)
const policyOpen = ref(false), selectedUser = ref(null)
function showExecutionPolicy(user) {
  selectedUser.value = user
  policyOpen.value = true
}
onMounted(async () => {
  try { users.value = await api.adminUsers() } catch (exc) { error.value = exc.message }
  finally { loading.value = false }
})
</script>
<template>
  <section><header class="page-head"><h1>用户管理</h1></header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="loading" class="page-loading" role="status">加载中…</p>
    <div v-else-if="!error" class="panel table-panel"><table><thead><tr><th>用户名</th><th>角色</th><th>用户 ID</th><th>操作</th></tr></thead><tbody><tr v-for="user in users" :key="user.user_id"><td>{{ user.username }}</td><td><span class="tag">{{ user.role === 'admin' ? '管理员' : '用户' }}</span></td><td class="mono">{{ user.user_id }}</td><td><button class="btn ghost" type="button" :aria-label="`查看 ${user.username} 的执行配置`" @click="showExecutionPolicy(user)">执行配置</button></td></tr><tr v-if="!users.length"><td colspan="4">暂无用户</td></tr></tbody></table></div>
    <FormDrawer v-model="policyOpen" centered :title="`${selectedUser?.username || ''} · 执行配置`">
      <dl v-if="selectedUser" class="execution-policy-details">
        <dt>执行权限</dt><dd>{{ { ask: '每次确认', sandboxed: '工作区内自动执行', deny: '禁止命令执行' }[selectedUser.execution_policy.shell] }}</dd>
        <dt>需要审批时</dt><dd>{{ selectedUser.execution_policy.on_approval_required === 'suspend' ? '暂停，等待用户处理' : '直接拒绝，适合无人值守' }}</dd>
        <dt>审批有效期（分钟）</dt><dd>{{ selectedUser.execution_policy.approval_timeout_seconds / 60 }}</dd>
      </dl>
    </FormDrawer>
  </section>
</template>

<style scoped>
.execution-policy-details { display: grid; gap: .5rem; margin: 0; }
.execution-policy-details dt { color: var(--muted-foreground); }
.execution-policy-details dd { margin: 0 0 1rem; overflow-wrap: anywhere; }
.execution-policy-details dd:last-child { margin-bottom: 0; }
</style>
