<script setup>
import PageToolbar from '../components/PageToolbar.vue'
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'
import AppIcon from '../components/AppIcon.vue'
import ToolSources from '../components/ToolSources.vue'
import ToolDetail from '../components/ToolDetail.vue'
import { toolCategories, toolPresentation } from '../resource-presentation.js'
const tools = ref([]), search = ref(''), category = ref(''), error = ref(''), loading = ref(true)
const selected = ref(null), detailOpen = ref(false)
const categories = computed(() => [...new Set(tools.value.map(item => item.category).filter(Boolean))])
const visible = computed(() => tools.value.map(item => ({ item, ...toolPresentation(item) })).filter(view =>
  (!category.value || view.item.category === category.value) && `${view.item.name} ${view.title} ${view.item.description || ''} ${view.description}`.toLowerCase().includes(search.value.trim().toLowerCase())))
async function load() {
  loading.value = true; error.value = ''
  try { tools.value = (await api.listTools()).filter(item => item.source === 'official') } catch (exc) { error.value = exc.message } finally { loading.value = false }
}
function inspect(item) { selected.value = item; detailOpen.value = true }
onMounted(load)
</script>
<template>
  <section class="resource-page" aria-label="工具">
    <PageToolbar aria-label="工具操作">
      <ToolSources />
      <template #actions><label class="rs-search"><AppIcon name="search" /><input v-model="search" type="search" placeholder="搜索工具" aria-label="搜索工具" /></label></template>
      <template #filters><div class="rs-filters" aria-label="工具分类"><button type="button" :aria-pressed="!category" @click="category = ''">全部</button><button v-for="item in categories" :key="item" type="button" :aria-pressed="category === item" @click="category = item">{{ toolCategories[item]?.[0] || item }}</button></div></template>
    </PageToolbar>
    <div v-if="loading" class="rs-grid" aria-busy="true" aria-label="正在加载工具"><div v-for="n in 3" :key="n" class="rs-skeleton"><i></i><i></i><i></i></div></div>
    <div v-else-if="error" class="rs-empty" role="alert"><span class="rs-icon"><AppIcon name="link" /></span><h2>暂时无法加载工具</h2><p>{{ error }}</p><button class="btn cta" type="button" @click="load">重新加载</button></div>
    <div v-else-if="!visible.length" class="rs-empty"><span class="rs-icon"><AppIcon name="search" /></span><h2>{{ search || category ? '没有找到匹配的工具' : '暂无可用工具' }}</h2><button v-if="search || category" class="btn ghost" type="button" @click="search = ''; category = ''">清除筛选</button><router-link v-else class="btn cta" to="/mcp">连接 MCP 服务</router-link></div>
    <div v-else class="rs-grid"><article v-for="view in visible" :key="`${view.item.source}:${view.item.name}`" class="rs-card"><header class="rs-card-head"><span class="rs-icon" :data-tone="view.tone"><AppIcon :name="view.icon" /></span><div><h2>{{ view.title }}</h2><div class="rs-technical">{{ view.item.name }}</div></div></header><p class="rs-description">{{ view.description || '暂无用途说明' }}</p><div class="rs-tags"><span class="rs-badge neutral">{{ view.category }}</span><span v-if="view.item.default" class="rs-badge">默认工具集</span></div><footer class="rs-card-footer"><span>{{ view.item.source === 'mcp' ? 'MCP 工具' : view.item.source === 'host' ? '主机工具' : '官方工具' }}</span><button class="btn ghost" type="button" :aria-label="`查看 ${view.title} 详情`" @click="inspect(view.item)">查看<AppIcon name="chevron" /></button></footer></article></div>
    <ToolDetail v-model="detailOpen" :item="selected" />
  </section>
</template>
<style src="../resource-surfaces.css"></style>
