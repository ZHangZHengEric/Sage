<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
import AppIcon from '../components/AppIcon.vue'
import FieldHelp from '../components/FieldHelp.vue'
import { policyHelp } from '../system-settings-presentation.js'

const form = ref({ shell: 'ask', on_approval_required: 'suspend', timeout: 1440 })
const busy = ref(false), ready = ref(false), error = ref(''), message = ref('')
async function save() {
  if (busy.value || !ready.value) return
  busy.value = true; error.value = ''; message.value = ''
  try {
    await api.saveExecutionPolicy({ shell: form.value.shell,
      on_approval_required: form.value.on_approval_required,
      approval_timeout_seconds: form.value.timeout * 60 })
    message.value = '已保存。新任务使用此策略；已有任务的权限不会因放宽设置而扩大。'
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function load() {
  busy.value = true; error.value = ''
  try {
    const policy = await api.executionPolicy()
    form.value = { shell: policy.shell, on_approval_required: policy.on_approval_required,
      timeout: policy.approval_timeout_seconds / 60 }
    ready.value = true
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
onMounted(load)
</script>

<template>
  <section class="execution-settings" aria-label="执行设置">
    <div v-if="error" class="execution-feedback execution-error" role="alert"><span>{{ error }}</span><button v-if="!ready" class="btn ghost" type="button" :disabled="busy" @click="load">重新加载</button></div>
    <p v-if="message" class="execution-feedback" role="status"><AppIcon name="check" /><span>{{ message }}</span></p>
    <div v-if="busy && !ready" class="execution-skeleton" aria-busy="true" aria-label="正在加载执行设置"><i v-for="n in 3" :key="n"></i></div>
    <form v-else-if="ready" class="execution-form" :aria-busy="busy" @submit.prevent="save">
      <fieldset :disabled="busy">
        <legend class="sr-only">执行设置</legend>
        <div class="execution-row">
          <div class="execution-label"><label for="execution-shell">执行权限</label><FieldHelp label="执行权限" :text="policyHelp.shell + ' 此设置也适用于持有你 API 密钥的程序，最终权限仍受服务端和智能体的上限限制。'" /></div>
          <div class="execution-control">
            <select id="execution-shell" v-model="form.shell" aria-describedby="execution-shell-help">
              <option value="ask">每次确认</option>
              <option value="sandboxed">工作区内自动执行</option>
              <option value="deny">禁止命令执行</option>
            </select>
            <p id="execution-shell-help" class="execution-hint" aria-live="polite">
              <template v-if="form.shell === 'sandboxed'">允许在自己的 /workspace 内运行代码、修改和删除文件；此授权也适用于持有你 API 密钥的程序。</template>
              <template v-else-if="form.shell === 'ask'">命令和文件修改执行前等待批准。</template>
              <template v-else>拒绝 Shell 命令，其他工具仍按各自权限审核。</template>
            </p>
          </div>
        </div>
        <div class="execution-row">
          <div class="execution-label"><label for="execution-approval">需要审批时</label><FieldHelp label="需要审批时" :text="policyHelp.approval" /></div>
          <div class="execution-control"><select id="execution-approval" v-model="form.on_approval_required">
            <option value="suspend">暂停，等待用户处理</option>
            <option value="deny">直接拒绝，适合无人值守</option>
          </select></div>
        </div>
        <div class="execution-row">
          <div class="execution-label"><label for="execution-timeout">审批有效期</label><FieldHelp label="审批有效期" :text="policyHelp.timeout" /></div>
          <div class="execution-control">
            <div class="execution-unit-input"><input id="execution-timeout" v-model.number="form.timeout" aria-label="审批有效期（分钟）" aria-describedby="execution-timeout-help" type="number" min="1" max="10080" step="any" required /><span>分钟</span></div>
            <p id="execution-timeout-help" class="execution-hint">等待审批时释放执行资源，记录保留；过期后任务自动取消。</p>
          </div>
        </div>
      </fieldset>
      <footer class="execution-footer"><button class="btn cta" type="submit" :disabled="busy">{{ busy ? '保存中…' : '保存设置' }}</button></footer>
    </form>
  </section>
</template>

<style scoped>
.execution-settings { color: var(--foreground); font-size: 14px; }
.execution-form, .execution-skeleton { width: 100%; max-width: 680px; border: 1px solid var(--border); border-radius: var(--radius-card); background: var(--card); }
.execution-form fieldset { padding-inline: var(--space-5); }
.execution-row { display: grid; grid-template-columns: 104px minmax(0, 1fr); align-items: start; gap: var(--space-4); padding-block: var(--space-5); }
.execution-row + .execution-row { border-top: 1px solid var(--border); }
.execution-label { display: flex; align-items: center; gap: var(--space-1); min-height: var(--control-height); font-size: 13px; font-weight: 550; }
.execution-control { width: 100%; min-width: 0; }
.execution-control select { width: 100%; }
.execution-hint { margin: var(--space-2) 0 0; color: var(--muted-foreground); font-size: 12px; line-height: 1.8; overflow-wrap: anywhere; }
.execution-unit-input { display: flex; align-items: center; gap: var(--space-3); }
.execution-unit-input input { width: 120px; max-width: 100%; min-width: 0; }
.execution-unit-input span { flex-shrink: 0; color: var(--muted-foreground); font-size: 12px; }
.execution-footer { display: flex; padding: var(--space-4) 0 var(--space-5) 120px; margin-inline: var(--space-5); border-top: 1px solid var(--border); }
.execution-feedback { display: flex; align-items: center; gap: var(--space-2); max-width: 680px; padding: var(--space-3) var(--space-4); margin: 0 0 var(--space-4); border-radius: var(--radius); background: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.execution-feedback .app-icon { width: 16px; height: 16px; }
.execution-error { justify-content: space-between; flex-wrap: wrap; color: var(--destructive); background: color-mix(in srgb, var(--destructive) 6%, var(--card)); }
.execution-skeleton { padding: var(--space-5); }
.execution-skeleton i { display: block; width: 70%; height: 15px; margin: var(--space-4) 0 var(--space-6); border-radius: var(--radius); background: var(--muted); }
@media (max-width: 520px) {
  .execution-form fieldset { padding-inline: var(--space-4); }
  .execution-row { gap: var(--space-2); padding-block: var(--space-4); }
  .execution-unit-input { gap: var(--space-2); }
  .execution-footer { margin-inline: var(--space-4); padding-left: 112px; padding-bottom: var(--space-4); }
}
</style>
