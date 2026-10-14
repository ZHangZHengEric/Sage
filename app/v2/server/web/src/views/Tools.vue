<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'
import AppIcon from '../components/AppIcon.vue'
import ToolSources from '../components/ToolSources.vue'
const tools = ref([]), search = ref(''), category = ref(''), error = ref(''), loading = ref(true)
const categories = computed(() => [...new Set(tools.value.map(item => item.category).filter(Boolean))])
const visible = computed(() => tools.value.filter(item => (!category.value || item.category === category.value) && `${item.name} ${item.description || ''}`.toLowerCase().includes(search.value.toLowerCase())))
onMounted(async () => { try { tools.value = await api.listTools() } catch (exc) { error.value = exc.message } finally { loading.value = false } })
</script>
<template>
  <section><header class="page-head"><h1>工具</h1><input v-model="search" class="search-input" placeholder="搜索工具" aria-label="搜索工具" /></header><ToolSources />
    <div class="source-tabs" aria-label="工具分类"><button :aria-pressed="!category" @click="category = ''">全部</button><button v-for="item in categories" :key="item" :aria-pressed="category === item" @click="category = item">{{ item }}</button></div>
    <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="loading" class="page-loading" role="status">加载中…</p><p v-else-if="!visible.length" class="empty">没有匹配的工具</p>
    <div v-else class="resource-grid"><article v-for="item in visible" :key="item.name" class="resource-card"><div class="resource-card-head"><span class="resource-icon"><AppIcon name="tools" /></span><h2>{{ item.name }}</h2></div><p v-if="item.description">{{ item.description }}</p><div class="resource-card-foot"><span>{{ item.category }}</span><span v-if="item.default" class="tag">默认启用</span></div></article></div>
  </section>
</template>
