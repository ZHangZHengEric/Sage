<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'
import { isAdmin } from '../auth.js'
import SchemaField from '../components/SchemaField.vue'
const catalog = ref(null), server = ref(null), error = ref(''), query = ref('')
const plugins = computed(() => (catalog.value?.plugins || []).filter(item => `${item.id} ${item.name} ${item.capabilities.join(' ')}`.toLowerCase().includes(query.value.toLowerCase())))
function defaultsFor(plugin) { return plugin.capabilities.filter(cap => catalog.value.defaults[cap] === plugin.id) }
function bindingsFor(plugin) { return server.value?.providers.filter(item => item.plugin_id === plugin.id) || [] }
function configFor(plugin) { return Object.fromEntries(Object.entries(plugin.schema?.properties || {}).filter(([, field]) => field.default !== undefined).map(([key, field]) => [key, field.default])) }
onMounted(async () => { try { [catalog.value, server.value] = await Promise.all([api.listPlugins(), isAdmin() ? api.serverPlugins() : null]) } catch (e) { error.value = e.message } })
</script>
<template>
  <section>
    <header class="page-head"><h1>插件</h1><input v-model="query" type="search" aria-label="搜索插件" placeholder="搜索插件" /></header>
    <p v-if="error" class="error" role="alert">{{ error }}</p><p v-else-if="!catalog" role="status">加载中…</p>
    <div v-else>
      <details v-if="server" class="panel" open><summary>Server 生效配置</summary><div class="plugin-bindings"><div v-for="binding in server.providers" :key="`${binding.capability}:${binding.name}:${binding.scope}`" class="plugin-binding"><strong>{{ binding.capability }}</strong><code>{{ binding.plugin_id || binding.source }}</code><span>{{ binding.scope }}</span></div></div></details>
    <div class="plugin-grid">
      <article v-for="plugin in plugins" :key="plugin.id" class="panel plugin-card">
        <h2>{{ plugin.name }}</h2><code>{{ plugin.id }}</code>
        <div class="selected-tags"><span v-for="cap in plugin.capabilities" :key="cap" class="tag">{{ cap }}</span><span v-if="defaultsFor(plugin).length" class="tag">默认选择</span><span v-if="bindingsFor(plugin).length" class="tag">线上生效</span><span class="tag">{{ plugin.configurable_capabilities.length ? 'Agent 可配置' : 'Server 管理' }}</span></div>
        <SchemaField v-if="Object.keys(plugin.schema.properties || {}).length" :schema="plugin.schema" :root="plugin.schema" :model-value="configFor(plugin)" label="默认参数" disabled />
        <template v-for="binding in bindingsFor(plugin)" :key="`${binding.capability}:${binding.scope}`"><div class="plugin-binding">{{ binding.capability }} · {{ binding.scope }}</div><SchemaField v-if="server.selections[binding.capability]" :schema="plugin.schema" :root="plugin.schema" :model-value="server.selections[binding.capability].config" label="生效配置" disabled /></template>
      </article>
    </div>
    </div>
    <p v-if="catalog && !plugins.length" class="empty">没有匹配的插件</p>
  </section>
</template>
<style scoped>
.plugin-bindings { display: grid; gap: 12px; margin-top: 16px; }.plugin-bindings .plugin-binding { display: flex; flex-wrap: wrap; gap: 12px; }.plugin-bindings strong { min-width: 230px; }
.plugin-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap: 16px; margin-top: 16px; }
.plugin-card { min-width: 0; background: color-mix(in srgb, var(--card) 90%, transparent); backdrop-filter: blur(14px); }
.plugin-card h2 { font-size: 17px; margin: 0 0 8px; }
.plugin-card code { overflow-wrap: anywhere; font-size: 12px; }
.selected-tags { margin: 12px 0; }.plugin-binding { margin-top: 12px; color: var(--muted-foreground); overflow-wrap: anywhere; }
</style>
