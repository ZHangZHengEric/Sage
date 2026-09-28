<template>
  <div class="pptx-test p-4">
    <h2 class="text-lg font-bold mb-4">PPTX Preview Test</h2>

    <div class="mb-4">
      <input
        type="file"
        accept=".pptx"
        @change="handleFileSelect"
        class="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
      />
    </div>

    <div class="mb-4">
      <button
        @click="testWithSample"
        class="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 mr-2"
      >
        Test Init
      </button>
      <button
        @click="clearContainer"
        class="px-4 py-2 bg-gray-500 text-white rounded hover:bg-gray-600"
      >
        Clear
      </button>
    </div>

    <div class="status mb-4 p-2 bg-gray-100 rounded">
      <p class="text-sm">Status: {{ status }}</p>
      <p class="text-sm text-red-500" v-if="error">Error: {{ error }}</p>
    </div>

    <div ref="container" class="pptx-container border border-gray-300 rounded" style="width: 960px; height: 540px;">
      <p class="text-center text-gray-400 mt-20">PPTX will be rendered here</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { init as initPptxPreview } from 'pptx-preview'

const container = ref(null)
const status = ref('Ready')
const error = ref('')
let previewer = null

const testWithSample = () => {
  try {
    status.value = 'Testing init...'
    error.value = ''

    if (!container.value) {
      error.value = 'Container not found'
      return
    }

    console.log('Container:', container.value)
    console.log('Container innerHTML:', container.value.innerHTML)

    // Test init
    previewer = initPptxPreview(container.value, {
      width: 960,
      height: 540
    })

    console.log('Previewer:', previewer)
    status.value = 'Init successful'
  } catch (err) {
    console.error('Test error:', err)
    error.value = err.message
    status.value = 'Init failed'
  }
}

const handleFileSelect = async (event) => {
  const file = event.target.files[0]
  if (!file) return

  try {
    status.value = 'Loading file...'
    error.value = ''

    const arrayBuffer = await file.arrayBuffer()
    console.log('File loaded, size:', arrayBuffer.byteLength)

    if (!previewer) {
      if (!container.value) {
        error.value = 'Container not found'
        return
      }
      previewer = initPptxPreview(container.value, {
        width: 960,
        height: 540
      })
    }

    status.value = 'Rendering...'
    await previewer.preview(arrayBuffer)
    status.value = 'Render successful'
  } catch (err) {
    console.error('File render error:', err)
    error.value = err.message
    status.value = 'Render failed'
  }
}

const clearContainer = () => {
  if (container.value) {
    container.value.innerHTML = '<p class="text-center text-gray-400 mt-20">PPTX will be rendered here</p>'
  }
  previewer = null
  status.value = 'Cleared'
  error.value = ''
}

onMounted(() => {
  console.log('PptxTest mounted')
  console.log('Container on mount:', container.value)
})
</script>

<style scoped>
.pptx-test {
  max-width: 1000px;
  margin: 0 auto;
}

.pptx-container {
  background: #f5f5f5;
  overflow: auto;
}
</style>
