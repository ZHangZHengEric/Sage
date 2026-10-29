<script setup>
import { computed, reactive, ref } from 'vue'
import FormDrawer from './FormDrawer.vue'
import FieldHelp from './FieldHelp.vue'
import { defaultRsiForm, rsiFields, rsiPayload } from '../rsi.js'

defineProps({ open: Boolean, busy: Boolean, error: String, models: { type: Array, default: () => [] } })
const emit = defineEmits(['update:open', 'start'])
const form = reactive(defaultRsiForm()), validation = ref(''), importing = ref(false)
const visibleFields = computed(() => rsiFields.slice(0, 5).filter(([key]) => form.datasetMode !== 'import' || key !== 'validation_case_count'))
const example = JSON.stringify({ cases: [
  { id: 'train-1', input: '6 × 7 等于多少？', rubric: '结果为 42', split: 'training' },
  { id: 'dev-1', input: '40 + 2 等于多少？', rubric: '结果为 42', split: 'validation' },
] }, null, 2)
function submit() {
  validation.value = ''
  try { emit('start', rsiPayload(form)) } catch (exc) { validation.value = exc.message }
}
function revealInvalid(event) {
  const details = event.target.closest('details')
  if (details) details.open = true
}
async function importFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  importing.value = true; validation.value = ''
  try {
    if (file.size > 4 * 1024 * 1024) throw Error('题集文件不能超过 4 MiB')
    const text = await file.text(); JSON.parse(text); form.suiteText = text
  } catch (exc) { validation.value = exc instanceof SyntaxError ? '题集文件须为有效 JSON' : exc.message }
  finally { importing.value = false; event.target.value = '' }
}
</script>

<template>
  <FormDrawer :model-value="open" title="新建 RSI 实验" :busy="busy || importing" @update:model-value="emit('update:open', $event)">
    <form id="rsi-setup" class="rsi-form" @submit.prevent="submit" @invalid.capture="revealInvalid">
      <fieldset :disabled="busy || importing">
        <label class="rsi-field">优化目标<textarea v-model="form.goal" rows="4" required maxlength="16000" placeholder="例如：提高算术回答的正确率，同时保持原有权限与职责" /></label>
        <div class="rsi-field"><span>优化范围 <FieldHelp label="优化范围" text="提示词和技能只在候选包内修改。评测使用独立空工作区，进程与外部业务工具暂不执行；候选须手动应用。" /></span><div class="rsi-options"><label><input v-model="form.scope" type="checkbox" value="instructions" />提示词</label><label><input v-model="form.scope" type="checkbox" value="skills" />技能</label></div></div>
        <label class="rsi-field">内部角色模型<select v-model="form.model_id"><option value="">使用默认模型</option><option v-for="m in models" :key="m.id" :value="m.id">{{ m.model || m.id }}</option></select></label>
        <label class="rsi-field">题集来源<select v-model="form.datasetMode"><option value="generate">自动出题</option><option value="import">导入题集</option></select></label>
        <template v-if="form.datasetMode === 'import'">
          <label class="rsi-field">题集文件<input type="file" accept=".json,application/json" @change="importFile" /></label>
          <label class="rsi-field">题集 JSON<textarea v-model="form.suiteText" class="mono" rows="8" required maxlength="4194304" :placeholder="example" spellcheck="false" /></label>
          <details><summary>题集格式</summary><pre class="rsi-code">{{ example }}</pre></details>
        </template>
        <div class="rsi-form-grid"><label v-for="[key, label, min, max] in visibleFields" :key="key" class="rsi-field">{{ label }}<input v-model.number="form[key]" type="number" :min="min" :max="max" step="1" required /></label></div>
        <details class="rsi-advanced"><summary>高级设置</summary><div class="rsi-form-grid">
          <label v-for="[key, label, min, max] in rsiFields.slice(5)" :key="key" class="rsi-field">{{ label }}<input v-model.number="form[key]" type="number" :min="min" :max="max" step="1" required /></label>
          <label class="rsi-field">目标得分<input v-model.number="form.target_score" type="number" min="0.001" max="1" step="0.001" required /></label>
          <label class="rsi-field">停滞轮数<input v-model.number="form.patience" type="number" min="1" max="100" step="1" required /></label>
          <label class="rsi-field">稳定复测次数<input v-model.number="form.stability_passes" type="number" min="2" max="5" step="1" required /></label>
        </div></details>
      </fieldset>
      <p v-if="validation || error" class="rsi-feedback error" role="alert">{{ validation || error }}</p>
    </form>
    <template #footer><div class="rsi-actions"><button class="btn ghost" :disabled="busy || importing" @click="emit('update:open', false)">取消</button><button class="btn cta" type="submit" form="rsi-setup" :disabled="busy || importing">{{ busy ? '正在启动…' : '开始优化' }}</button></div></template>
  </FormDrawer>
</template>
