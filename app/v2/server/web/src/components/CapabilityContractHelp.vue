<script setup>
import { computed, ref } from 'vue'
import FormDrawer from './FormDrawer.vue'

const props = defineProps({ capability: String, inventory: Object })
const open = ref(false)
const contracts = computed(() => {
  const selected = props.inventory?.[props.capability]
  return selected ? Object.entries(props.inventory).filter(([, item]) => item.module === selected.module) : []
})
const statuses = { declared: '已声明', unsupported: '不支持', not_declared: '未声明' }
</script>

<template>
  <button v-if="contracts.length" class="contract-help" type="button" aria-label="查看插件契约" @click="open = true">?</button>
  <FormDrawer v-if="contracts.length" v-model="open" centered title="插件契约">
    <section v-for="[id, contract] in contracts" :key="id" class="contract-section">
      <h3><code>{{ id }}</code> <small>API {{ contract.api_version }}</small></h3>
      <p v-if="contract.sdk_managed">SDK 管理</p>
      <p v-if="contract.nullable_provider">按 Run 授权启用</p>
      <p v-if="contract.required_members.length">必需接口 <code>{{ contract.required_members.join(' · ') }}</code></p>
      <ul v-if="contract.features.length">
        <li v-for="feature in contract.features" :key="feature.id">
          <code>{{ feature.id }}</code>
          <span v-if="feature.required_when"> · {{ feature.required_when }} 启用时必需</span>
          <span v-else> · 可选</span>
          <span v-if="feature.members.length"> · <code>{{ feature.members.join(' · ') }}</code></span>
        </li>
      </ul>
      <p v-if="contract.conformance">契约检查 <code>sagents.v2.testing.{{ contract.conformance }}</code></p>
      <h4 v-if="contract.implementations.length">已注册实现</h4>
      <ul>
        <li v-for="plugin in contract.implementations" :key="`${plugin.id}:${plugin.provider_name}`">
          <code>{{ plugin.id }}</code>
          <span v-if="plugin.provider_name !== 'default'"> · {{ plugin.provider_name }}</span>
          <span v-if="plugin.api_version !== contract.api_version"> · API {{ plugin.api_version }}</span>
          <span v-if="plugin.sdk_managed"> · SDK 管理</span>
          <span v-if="!plugin.available"> · 当前不可用</span>
          <ul v-if="plugin.features.length">
            <li v-for="feature in plugin.features" :key="feature.id">
              <code>{{ feature.id }}</code> · {{ statuses[feature.status] }}
            </li>
          </ul>
        </li>
      </ul>
    </section>
  </FormDrawer>
</template>

<style scoped>
.contract-help { display: inline-grid; place-items: center; flex: none; width: 1.6rem; height: 1.6rem; border-radius: 50%; border: 1px solid var(--border); background: var(--surface); color: inherit; cursor: pointer; font: inherit; font-size: .8rem; }
.contract-section + .contract-section { border-top: 1px solid var(--border); padding-top: 1rem; margin-top: 1rem; }
.contract-section h3, .contract-section h4 { margin-block: 0 .5rem; }
.contract-section p, .contract-section ul { margin-block: .5rem; }
.contract-section code { overflow-wrap: anywhere; }
.contract-section small { color: var(--muted-foreground); }
</style>
