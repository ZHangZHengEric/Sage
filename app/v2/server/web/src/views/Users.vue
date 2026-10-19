<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'
import AppIcon from '../components/AppIcon.vue'
import FieldHelp from '../components/FieldHelp.vue'
import FormDrawer from '../components/FormDrawer.vue'
import { executionNames, policyHelp } from '../system-settings-presentation.js'
const users = ref([]), error = ref(''), loading = ref(true), message = ref('')
const policyOpen = ref(false), selectedUser = ref(null), search = ref(''), role = ref('all')
const visibleUsers = computed(() => {
  const query = search.value.trim().toLowerCase()
  return users.value.filter(user => (role.value === 'all' || user.role === role.value) &&
    (!query || `${user.username} ${user.user_id}`.toLowerCase().includes(query)))
})
const roleName = user => ({ admin: '管理员', user: '用户' })[user.role] || user.role || '未指定'
const executionName = user => executionNames[user?.execution_policy?.shell] || user?.execution_policy?.shell || '未提供'
const approvalName = computed(() => ({ suspend: '暂停，等待用户处理', deny: '直接拒绝，适合无人值守' })[selectedUser.value?.execution_policy?.on_approval_required] || '未提供')
const timeout = computed(() => selectedUser.value?.execution_policy?.approval_timeout_seconds != null ? `${selectedUser.value.execution_policy.approval_timeout_seconds / 60} 分钟` : '未提供')
function clearFilters() { search.value = ''; role.value = 'all' }
function showExecutionPolicy(user) { selectedUser.value = user; policyOpen.value = true }
async function copyId(user) {
  try { await navigator.clipboard.writeText(user.user_id); message.value = `${user.username} 的用户 ID 已复制` }
  catch { message.value = '未能自动复制，可在执行配置详情中选取用户 ID' }
}
async function load() {
  loading.value = true; error.value = ''
  try { users.value = await api.adminUsers() } catch (exc) { error.value = exc.message }
  finally { loading.value = false }
}
onMounted(load)
</script>
<template>
  <section class="system-settings users-settings">
    <header class="system-users-head"><h1>用户管理</h1><span v-if="!loading" class="system-badge neutral">{{ users.length }} 人</span></header>
    <p v-if="message" class="system-message" role="status"><span>{{ message }}</span><button class="icon-button" type="button" aria-label="关闭提示" @click="message = ''"><AppIcon name="close" /></button></p>
    <div v-if="users.length" class="system-users-toolbar"><div class="system-role-filters" aria-label="用户角色筛选"><button v-for="[value, label] in [['all', '全部用户'], ['admin', '管理员'], ['user', '普通用户']]" :key="value" type="button" :aria-pressed="role === value" @click="role = value">{{ label }}</button></div><label class="system-user-search"><AppIcon name="search" /><input v-model="search" type="search" placeholder="搜索用户名或用户 ID" aria-label="搜索用户名或用户 ID" /></label></div>
    <div v-if="error" class="system-error" role="alert"><span>{{ error }}</span><button class="btn ghost" type="button" :disabled="loading" @click="load">重新加载</button></div>
    <div v-if="loading" class="system-skeleton" aria-busy="true" aria-label="正在加载用户"><i v-for="n in 4" :key="n"></i></div>
    <div v-else-if="!users.length && !error" class="system-empty"><AppIcon name="user" /><h2>暂无用户</h2></div>
    <div v-else-if="users.length && !visibleUsers.length" class="system-empty"><AppIcon name="search" /><h2>没有找到匹配的用户</h2><button class="btn ghost" type="button" @click="clearFilters">清除筛选</button></div>
    <div v-else-if="users.length" class="system-user-table"><table><thead><tr><th>用户</th><th>角色</th><th class="system-user-id-column">用户 ID</th><th class="system-user-policy-column">用户执行权限</th><th class="system-user-action-column">操作</th></tr></thead><tbody><tr v-for="user in visibleUsers" :key="user.user_id"><td><div class="system-person"><span class="system-avatar" aria-hidden="true">{{ user.username?.[0]?.toUpperCase() || 'U' }}</span><strong>{{ user.username }}</strong></div></td><td><span class="system-badge" :class="{ neutral: user.role !== 'admin' }">{{ roleName(user) }}</span></td><td class="system-user-id-column"><div class="system-id"><code :title="user.user_id">{{ user.user_id }}</code><button class="icon-button" type="button" :aria-label="`复制 ${user.username} 的用户 ID`" @click="copyId(user)"><AppIcon name="copy" /></button></div></td><td class="system-user-policy-column"><span class="system-user-policy"><i></i>{{ executionName(user) }}</span></td><td class="system-user-action-column"><button class="btn ghost" type="button" :aria-label="`查看 ${user.username} 的执行配置`" @click="showExecutionPolicy(user)">执行配置<AppIcon name="chevron" /></button></td></tr></tbody></table></div>
    <FormDrawer v-model="policyOpen" centered panel-class="system-settings system-user-dialog" :title="`${selectedUser?.username || ''} · 执行配置`">
      <section v-if="selectedUser" class="system-person-detail">
        <header class="system-person-head"><span class="system-avatar" aria-hidden="true">{{ selectedUser.username?.[0]?.toUpperCase() || 'U' }}</span><div><h2>{{ selectedUser.username }}</h2><span class="system-badge" :class="{ neutral: selectedUser.role !== 'admin' }">{{ roleName(selectedUser) }}</span><span class="system-badge neutral">只读</span></div></header>
        <div class="system-detail-id"><code>{{ selectedUser.user_id }}</code><button class="icon-button" type="button" aria-label="复制用户 ID" @click="copyId(selectedUser)"><AppIcon name="copy" /></button></div>
        <div class="system-section-title"><h3>用户执行配置</h3><FieldHelp label="用户执行配置" :text="policyHelp.overview" /></div>
        <dl class="system-policy-details"><div><dt>执行权限<FieldHelp label="执行权限" :text="policyHelp.shell" /></dt><dd>{{ executionName(selectedUser) }}</dd></div><div><dt>需要审批时<FieldHelp label="需要审批时" :text="policyHelp.approval" /></dt><dd>{{ approvalName }}</dd></div><div><dt>审批有效期<FieldHelp label="审批有效期" :text="policyHelp.timeout" /></dt><dd>{{ timeout }}</dd></div></dl>
        <p v-if="message" class="system-copy-feedback" role="status">{{ message }}</p>
      </section>
      <template #footer><div class="system-dialog-footer"><button class="btn ghost" type="button" @click="policyOpen = false">关闭</button></div></template>
    </FormDrawer>
  </section>
</template>
<style src="../system-settings.css"></style>
