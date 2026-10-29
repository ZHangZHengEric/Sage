<script setup>
import { computed, ref, watch } from 'vue'
import { packageChanges, lineDiff } from '../rsi.js'
const props = defineProps({ baseline: Object, candidate: Object })
const changes = computed(() => props.baseline && props.candidate ? packageChanges(props.baseline, props.candidate) : [])
const path = ref('')
watch(changes, value => { if (!value.some(row => row.path === path.value)) path.value = value[0]?.path || '' }, { immediate: true })
const selected = computed(() => changes.value.find(row => row.path === path.value))
const diff = computed(() => selected.value ? lineDiff(selected.value.before, selected.value.after) : null)
</script>

<template>
  <div class="rsi-diff">
    <p v-if="!baseline" class="rsi-feedback" role="status">基线内容不可用</p>
    <p v-else-if="!changes.length" class="rsi-feedback">提示词和技能内容与基线相同</p>
    <template v-else>
      <label class="rsi-field">修改内容<select v-model="path"><option v-for="change in changes" :key="change.path" :value="change.path">{{ change.kind }} · {{ change.path }}</option></select></label>
      <div class="rsi-diff-legend"><span>− 原始内容</span><span>+ 候选内容</span></div>
      <pre class="rsi-code rsi-diff-lines" tabindex="0" :aria-label="`${path} 与基线的差异`"><span v-for="(line, index) in diff.lines" :key="index" :class="`diff-${line.kind}`">{{ ({ same: ' ', remove: '−', add: '+' })[line.kind] }} {{ line.text }}</span></pre>
      <p v-if="diff.truncated" class="rsi-feedback">仅展示前 1000 行；完整内容可下载实验结果查看。</p>
    </template>
  </div>
</template>
