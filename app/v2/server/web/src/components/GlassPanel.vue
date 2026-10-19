<script setup>
defineProps({ as: { type: String, default: 'section' } })
</script>
<template><component :is="as" class="glass-panel"><slot /></component></template>
<style scoped>
.glass-panel { border: 1px solid var(--border); border-radius: 18px; background: color-mix(in srgb, var(--card) 92%, transparent); backdrop-filter: blur(16px); box-shadow: 0 4px 20px var(--shadow-color); }
@media (prefers-reduced-transparency: reduce) { .glass-panel { backdrop-filter: none; background: var(--card); } }
</style>
