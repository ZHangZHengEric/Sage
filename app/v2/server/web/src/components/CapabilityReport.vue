<script setup>
defineProps({ profile: Object })
const names = { connection: '连接', multimodal: '多模态', structured_output: '结构化输出', json_object: 'JSON 输出', tool_calling: '工具调用', reasoning_control: '推理控制' }
const behaviors = { none: '无推理', always: '始终推理', controllable: '可控制' }
const statuses = { supported: '支持', unsupported: '未通过', error: '探测失败', skipped: '未探测' }
</script>
<template>
  <section v-if="profile" class="glass-config capability-report" aria-label="能力探测结果">
    <h3>能力探测结果</h3>
    <div class="config-grid"><div v-for="outcome in profile.outcomes" :key="outcome.name" class="probe-outcome"><span>{{ names[outcome.name] || outcome.name }}</span><span class="tag" :class="outcome.status">{{ statuses[outcome.status] || outcome.status }}</span><p v-if="outcome.error" class="error">{{ outcome.error }}</p></div></div>
    <dl><dt>有效输出 Token</dt><dd>{{ profile.effective_max_output_tokens }}</dd><dt>探测时间</dt><dd>{{ new Date(profile.verified_at).toLocaleString() }}</dd><template v-if="profile.invocation_strategy?.supported_reasoning_efforts?.length"><dt>可用推理强度</dt><dd>{{ profile.invocation_strategy.supported_reasoning_efforts.join(' / ') }}</dd></template><template v-if="profile.invocation_strategy?.text_only_reasoning_efforts?.length"><dt>仅文本推理强度</dt><dd>{{ profile.invocation_strategy.text_only_reasoning_efforts.join(' / ') }}</dd></template><template v-if="profile.invocation_strategy?.unsupported_reasoning_efforts?.length"><dt>不支持的推理强度</dt><dd>{{ profile.invocation_strategy.unsupported_reasoning_efforts.join(' / ') }}</dd></template><template v-if="profile.invocation_strategy?.reasoning_behavior"><dt>推理行为</dt><dd>{{ behaviors[profile.invocation_strategy.reasoning_behavior] || profile.invocation_strategy.reasoning_behavior }}</dd></template></dl>
  </section>
</template>
