<template>
  <div class="h-full w-full bg-background p-4 md:p-6 overflow-hidden flex flex-col">
    <div v-if="loading" class="flex-1 flex items-center justify-center">
      <Loader class="h-8 w-8 animate-spin text-primary" />
    </div>
    <div v-else-if="error" class="flex-1 flex flex-col items-center justify-center text-center">
       <p class="text-destructive mb-4">{{ error }}</p>
       <Button @click="goBack">返回列表</Button>
    </div>
    <ToolDetail v-else-if="tool" :tool="tool" @back="goBack" class="flex-1 overflow-hidden" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toolAPI } from '../api/tool.js'
import ToolDetail from '../components/ToolDetail.vue'
import { Loader } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

const route = useRoute()
const router = useRouter()
const tool = ref(null)
const loading = ref(true)
const error = ref('')

const loadTool = async () => {
  try {
    loading.value = true
    const toolName = route.params.toolName
    // Since we don't have a getTool API, we fetch all and find
    const response = await toolAPI.getTools()
    if (response && response.tools) {
      const found = response.tools.find(t => t.name === toolName)
      if (found) {
        tool.value = found
      } else {
        error.value = 'Tool not found'
      }
    } else {
      error.value = 'Failed to load tools'
    }
  } catch (err) {
    console.error(err)
    error.value = err.message || 'Error loading tool'
  } finally {
    loading.value = false
  }
}

const goBack = () => {
  router.push({ name: 'Tools' })
}

onMounted(() => {
  loadTool()
})
</script>
