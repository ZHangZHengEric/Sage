<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { layoutCapabilityGraph } from '../capability-layout.js'
const props = defineProps({ nodes: { type: Array, default: () => [] }, links: { type: Array, default: () => [] }, active: String, disabled: Boolean, label: { type: String, default: '能力关系' } })
const emit = defineEmits(['select'])
const viewport = ref(null), zoom = ref(1), columns = ref(3)
let observer
const layout = computed(() => layoutCapabilityGraph(props.nodes, props.links, columns.value))
async function fit() {
  if (!viewport.value) return
  columns.value = viewport.value.clientWidth < 390 ? 1 : viewport.value.clientWidth < 620 ? 2 : 3
  await nextTick()
  zoom.value = Math.min(1, Math.max(.65, (viewport.value.clientWidth - 32) / layout.value.width))
  viewport.value.scrollTo?.({ top: 0, left: 0 })
}
onMounted(() => { if (viewport.value) { observer = new ResizeObserver(fit); observer.observe(viewport.value) } })
onBeforeUnmount(() => observer?.disconnect())
</script>
<template>
  <div class="capability-canvas">
    <header class="canvas-toolbar"><span>{{ label }} <small>{{ nodes.length }} 项</small></span><button class="btn ghost" type="button" @click="fit"><AppIcon name="grid" />适应画布</button></header>
    <div ref="viewport" class="canvas-viewport" aria-label="能力节点画布">
      <div class="canvas-space" :style="{ width: `${layout.width * zoom}px`, height: `${layout.height * zoom}px` }">
        <div class="canvas-board" :style="{ width: `${layout.width}px`, height: `${layout.height}px`, transform: `scale(${zoom})` }">
          <svg class="dependency-lines" :viewBox="`0 0 ${layout.width} ${layout.height}`" aria-hidden="true"><g v-for="route in layout.routes" :key="`${route.from}:${route.to}`" :class="{ related: active === route.from || active === route.to }"><path :d="route.path" /><circle v-for="point in [route.points[0], route.points.at(-1)]" :key="point.join(',')" :cx="point[0]" :cy="point[1]" r="3" /></g></svg>
          <button v-for="node in layout.nodes" :key="node.id" class="capability-node" :class="{ active: active === node.id, unavailable: node.available === false }" :style="{ left: `${node.x}px`, top: `${node.y}px`, width: `${node.width}px`, height: `${node.height}px` }" type="button" :disabled="disabled" :aria-pressed="active === node.id" :aria-label="`${node.name}：${node.choice}`" @click="emit('select', node.id)">
            <span class="node-heading"><span class="node-icon"><AppIcon :name="node.icon" /></span><strong>{{ node.name }}</strong></span>
            <span class="node-choice">{{ node.choice || '未指定' }}</span>
            <span class="node-source">{{ node.sourceText || (node.changed ? '未保存' : node.custom ? '自定义' : node.id === 'model.provider' ? '模型路由' : '跟随默认') }}</span><span v-if="node.available === false" class="node-warning">不可用</span>
          </button>
        </div>
      </div>
      <div v-if="layout.relations.length" class="separate-relations" aria-label="能力依赖关系"><div v-for="relation in layout.relations" :key="`${relation.from}:${relation.to}`" class="relation-row"><button type="button" :disabled="disabled" @click="emit('select', relation.from)">{{ relation.source }}</button><span aria-label="依赖于">→</span><button type="button" :disabled="disabled" @click="emit('select', relation.to)">{{ relation.target }}</button></div></div>
    </div>
    <footer class="canvas-footer"><span>{{ links.length ? '连线表示能力依赖，非执行顺序' : '点击节点查看实现与配置' }}</span><div class="zoom-controls"><button type="button" aria-label="缩小画布" :disabled="zoom <= .5" @click="zoom = Math.max(.5, zoom - .1)">−</button><span>{{ Math.round(zoom * 100) }}%</span><button type="button" aria-label="放大画布" :disabled="zoom >= 1.5" @click="zoom = Math.min(1.5, zoom + .1)">＋</button></div></footer>
  </div>
</template>
<style scoped>
.capability-canvas { display: flex; flex-direction: column; min-width: 0; min-height: 0; background: color-mix(in srgb, var(--muted) 35%, var(--background)); background-image: radial-gradient(var(--border) 1px, transparent 1px); background-size: 20px 20px; }
.canvas-toolbar, .canvas-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; flex: 0 0 auto; }
.canvas-toolbar > span { font-size: 12px; padding: 5px 10px; background: var(--card); border: 1px solid var(--border); border-radius: 6px; }.canvas-toolbar small { margin-left: 6px; color: var(--muted-foreground); font-size: 10px; }
.canvas-toolbar .btn { padding: 5px 8px; font-size: 11px; background: var(--card); }.canvas-toolbar .app-icon { width: 14px; height: 14px; }
.canvas-viewport { flex: 1; min-height: 0; overflow: auto; padding: 0 16px 16px; }.canvas-space { position: relative; margin: 0 auto; }.canvas-board { position: relative; transform-origin: top left; }
.dependency-lines { position: absolute; inset: 0; width: 100%; height: 100%; fill: none; stroke: var(--muted-foreground); stroke-width: 1.2; pointer-events: none; }.dependency-lines .related { stroke: var(--capability-accent); stroke-width: 1.8; }.dependency-lines circle { fill: var(--card); }
.capability-node { position: absolute; padding: 11px 12px; text-align: left; border: 1px solid var(--border); border-radius: 8px; background: var(--card); color: var(--foreground); cursor: pointer; transition: border-color 120ms ease-out, background 120ms ease-out; }
.capability-node.active { border-color: var(--capability-accent); box-shadow: inset 0 0 0 1px var(--capability-accent); background: color-mix(in srgb, var(--capability-soft) 45%, var(--card)); }.capability-node:hover { border-color: var(--capability-accent); }.capability-node:disabled { cursor: default; }
.node-heading { display: flex; gap: 7px; align-items: center; }.node-heading strong { font-size: 12px; font-weight: 550; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }.node-icon { width: 22px; height: 22px; display: grid; place-items: center; border-radius: 5px; color: var(--muted-foreground); background: var(--muted); flex-shrink: 0; }.node-icon .app-icon { width: 14px; height: 14px; }.active .node-icon { color: var(--capability-accent); background: var(--capability-soft); }
.node-source { display: inline-block; margin-top: 3px; font-size: 9px; color: var(--muted-foreground); }.active .node-source { color: var(--capability-accent); }.node-choice { display: block; margin-top: 5px; color: var(--muted-foreground); font-size: 10px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }.node-warning { margin-left: 6px; font-size: 9px; color: var(--destructive); }.unavailable { border-style: dashed; }
.canvas-footer { color: var(--muted-foreground); font-size: 10px; padding-top: 8px; }.zoom-controls { display: flex; align-items: center; gap: 8px; padding: 2px 4px; background: var(--card); border: 1px solid var(--border); border-radius: 6px; white-space: nowrap; }.zoom-controls button { background: none; border: 0; color: inherit; padding: 4px; }.zoom-controls span { min-width: 34px; text-align: center; }
.separate-relations { display: grid; gap: 8px; margin: 16px 0 0; }.relation-row { display: grid; grid-template-columns: minmax(0, 1fr) 22px minmax(0, 1fr); align-items: center; gap: 6px; font-size: 11px; }.relation-row > span { text-align: center; color: var(--capability-accent); }.relation-row button { min-width: 0; padding: 6px; border: 1px solid var(--border); border-radius: 6px; background: var(--card); color: var(--foreground); }
button:focus-visible { outline: 2px solid var(--capability-accent); outline-offset: 3px; }@media (prefers-reduced-motion: reduce) { .capability-node { transition: none; } }
</style>
