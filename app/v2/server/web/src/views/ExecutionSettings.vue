<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const form = ref({ shell: 'ask', on_approval_required: 'suspend', timeout: 1440 })
const busy = ref(false), ready = ref(false), error = ref(''), message = ref('')
async function save() {
  busy.value = true; error.value = ''; message.value = ''
  try {
    await api.saveExecutionPolicy({ shell: form.value.shell,
      on_approval_required: form.value.on_approval_required,
      approval_timeout_seconds: form.value.timeout * 60 })
    message.value = '已保存。新任务使用此策略；已有任务的权限不会因放宽设置而扩大。'
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
onMounted(async () => {
  busy.value = true
  try {
    const policy = await api.executionPolicy()
    form.value = { shell: policy.shell, on_approval_required: policy.on_approval_required,
      timeout: policy.approval_timeout_seconds / 60 }
    ready.value = true
  } catch (e) { error.value = e.message } finally { busy.value = false }
})
</script>

<template>
  <section>
    <header class="page-head"><h1>执行设置</h1></header>
    <p class="muted">这是当前账号的执行策略，网页对话和所有 API 密钥发起的任务共用。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <form class="panel stack" @submit.prevent="save">
      <fieldset class="stack" :disabled="busy || !ready">
        <legend>用户执行策略</legend>
        <label class="field"><span>执行权限</span><select v-model="form.shell">
          <option value="ask">每次确认</option>
          <option value="sandboxed">工作区内自动执行</option>
          <option value="deny">禁止命令执行</option>
        </select></label>
        <p v-if="form.shell === 'sandboxed'" class="muted">允许在自己的工作区 /workspace 内运行代码、修改和删除文件。此授权也适用于持有你 API 密钥的程序。Shell 网络禁用，外部工具仍按策略审批。</p>
        <p v-else-if="form.shell === 'ask'" class="muted">命令和文件修改执行前等待批准。</p>
        <p v-else class="muted">拒绝 Shell 命令，其他工具仍按各自权限审核。</p>
        <p class="muted">最终权限仍受服务端和智能体的上限限制。</p>
        <label class="field"><span>需要审批时</span><select v-model="form.on_approval_required">
          <option value="suspend">暂停，等待用户处理</option>
          <option value="deny">直接拒绝，适合无人值守</option>
        </select></label>
        <label class="field"><span>审批有效期（分钟）</span><input v-model.number="form.timeout" type="number" min="1" max="10080" step="any" required /></label>
        <small class="muted">等待审批时释放执行资源，记录保留；过期后任务自动取消。</small>
        <button class="btn cta" type="submit">{{ busy ? '处理中…' : '保存设置' }}</button>
      </fieldset>
    </form>
  </section>
</template>
