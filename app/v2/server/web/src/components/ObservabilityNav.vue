<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'
import AppIcon from './AppIcon.vue'

const services = ref([])
const loading = ref(true)
const error = ref(false)
let active = true
async function load() {
  loading.value = true
  error.value = false
  try {
    const links = await api.observabilityServices()
    if (active) services.value = links
  } catch {
    if (active) error.value = true
  } finally {
    if (active) loading.value = false
  }
}
onMounted(load)
onUnmounted(() => { active = false })
</script>

<template>
  <details v-if="loading || error || services.length" class="nav-group" open :aria-busy="loading">
    <summary class="nav-item" title="观测"><AppIcon name="eye" /><span>观测</span><AppIcon class="nav-chevron" name="chevron" /></summary>
    <div class="nav-children">
      <template v-for="service in services" :key="service.id">
        <a v-if="service.external" class="nav-item" :href="service.href" target="_blank" rel="noopener noreferrer" :title="`${service.label}（新窗口）`"><AppIcon name="link" /><span>{{ service.label }}</span></a>
        <router-link v-else class="nav-item" :to="service.href" :title="service.label"><AppIcon :name="service.id === 'traces' ? 'trace' : 'clock'" /><span>{{ service.label }}</span></router-link>
      </template>
      <button v-if="error" class="nav-item" type="button" @click="load"><AppIcon name="refresh" /><span>重试加载</span></button>
    </div>
  </details>
</template>
