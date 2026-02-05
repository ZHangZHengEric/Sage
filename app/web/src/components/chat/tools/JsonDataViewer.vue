<template>
  <div class="json-data-viewer font-mono text-xs">
 
    <!-- Null/Undefined -->
    <span v-if="data === null || data === undefined" class="text-muted-foreground italic">null</span>

    <!-- Max depth reached for Objects/Arrays -->
    <pre v-else-if="typeof data === 'object' && depth >= maxDepth"
      class="bg-muted/30 text-xs p-2 rounded-md overflow-x-auto whitespace-pre-wrap break-all border border-border/40">
{{ JSON.stringify(data, null, 2) }}</pre>

    <!-- Primitives -->
    <span v-else-if="typeof data !== 'object'">
      <a v-if="isImageUrl(data)" :href="data" target="_blank" class="text-blue-500 hover:underline inline-flex items-center gap-1" @click.stop>
        {{ data.split('/').pop() }}
      </a>
      <span v-else :class="getPrimitiveClass(data)">
        {{ formatPrimitive(data) }}
      </span>
    </span>

    <!-- Array -->
    <div v-else-if="Array.isArray(data)" class="w-full">
      <div v-if="data.length === 0" class="text-muted-foreground">[]</div>
      <div v-else class="rounded-md border border-border/40 overflow-hidden">
        <div v-for="(item, index) in data" :key="index" class="flex border-b border-border/40 last:border-0 hover:bg-muted/10">
       
          <div class="p-2 flex-1 min-w-0 overflow-x-auto">
            <JsonDataViewer :data="item" :depth="depth + 1" :maxDepth="maxDepth" />
          </div>
        </div>
      </div>
    </div>

    <!-- Object -->
    <div v-else class="w-full">
      <div v-if="Object.keys(data).length === 0" class="text-muted-foreground">{}</div>
      <div v-else class="rounded-md border border-border/40 overflow-hidden">
        <table class="w-full">
          <tbody>
            <tr v-for="(value, key) in data" :key="key" class="border-b border-border/40 last:border-0 hover:bg-muted/10">
              <td class="p-2 border-r border-border/40 bg-muted/20 text-muted-foreground font-medium align-top w-1/4 min-w-[100px] whitespace-nowrap">
                {{ key }}
              </td>
              <td class="p-2 align-top break-all">
                <JsonDataViewer :data="value" :depth="depth + 1" :maxDepth="maxDepth" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { defineOptions } from 'vue'

// Enable recursive component
defineOptions({
  name: 'JsonDataViewer'
})

const props = defineProps({
  data: {
    required: true
  },
  depth: {
    type: Number,
    default: 0
  },
  maxDepth: {
    type: Number,
    default: 1
  }
})

const getPrimitiveClass = (val) => {

  return 'text-foreground'
}

const isImageUrl = (val) => {
  if (typeof val !== 'string') return false
  return /\.(jpg|jpeg|png|gif|webp|svg|bmp|ico)$/i.test(val)
}

const formatPrimitive = (val) => {
  if (typeof val === 'string') return `${val}`
  return String(val)
}
</script>

<style scoped>
/* Optional: Add some specific styles if needed */
</style>