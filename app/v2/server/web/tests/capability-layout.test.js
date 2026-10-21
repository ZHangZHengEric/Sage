import assert from 'node:assert/strict'
import { test } from 'node:test'
import { layoutCapabilityGraph } from '../src/capability-layout.js'

const ids = ['context.reducer', 'context.summarizer', 'tool.selection-policy', 'model.provider', 'memory.recall-query', 'skill.loading', 'agent.continuation-policy']
const nodes = ids.map(id => ({ id, name: id }))
const links = [
  ['context.reducer', 'context.summarizer'],
  ['context.summarizer', 'model.provider'], ['tool.selection-policy', 'model.provider'],
  ['memory.recall-query', 'model.provider'], ['agent.continuation-policy', 'model.provider'],
]
const segments = route => route.points.slice(1).map((point, i) => [route.points[i], point])
function overlapsBox([a, b], box) {
  if (a[0] === b[0]) return a[0] > box.x && a[0] < box.x + box.width && Math.max(a[1], b[1]) > box.y && Math.min(a[1], b[1]) < box.y + box.height
  return a[1] > box.y && a[1] < box.y + box.height && Math.max(a[0], b[0]) > box.x && Math.min(a[0], b[0]) < box.x + box.width
}
function intersects([a, b], [c, d]) {
  const horizontal = a[1] === b[1], otherHorizontal = c[1] === d[1]
  if (horizontal === otherHorizontal) {
    const axis = horizontal ? 0 : 1, fixed = 1 - axis
    return a[fixed] === c[fixed] && Math.max(Math.min(a[axis], b[axis]), Math.min(c[axis], d[axis])) <= Math.min(Math.max(a[axis], b[axis]), Math.max(c[axis], d[axis]))
  }
  if (!horizontal) return intersects([c, d], [a, b])
  return c[0] >= Math.min(a[0], b[0]) && c[0] <= Math.max(a[0], b[0]) && a[1] >= Math.min(c[1], d[1]) && a[1] <= Math.max(c[1], d[1])
}

test('three-column layout shows every node and routes every dependency outside cards without crossing', () => {
  const layout = layoutCapabilityGraph(nodes, links)
  assert.equal(layout.nodes.length, 7)
  assert.equal(new Set(layout.nodes.map(node => node.x)).size, 3)
  assert.equal(layout.routes.length, links.length)
  for (const route of layout.routes) for (const segment of segments(route)) {
    assert.ok(segment[0][0] === segment[1][0] || segment[0][1] === segment[1][1], 'orthogonal routes')
    for (const node of layout.nodes) assert.equal(overlapsBox(segment, node), false, `${route.from} crosses ${node.id}`)
  }
  for (let i = 0; i < layout.routes.length; i++) for (let j = i + 1; j < layout.routes.length; j++) {
    for (const a of segments(layout.routes[i])) for (const b of segments(layout.routes[j])) assert.equal(intersects(a, b), false, `${layout.routes[i].from} intersects ${layout.routes[j].from}`)
  }
})

test('narrow layouts and future dependencies retain all relationships in separate rows', () => {
  for (const columns of [1, 2]) {
    const layout = layoutCapabilityGraph(nodes, links, columns)
    assert.equal(layout.nodes.length, 7)
    assert.equal(layout.routes.length, 0)
    assert.equal(layout.relations.length, links.length)
  }
  const future = layoutCapabilityGraph([...nodes, { id: 'custom' }], [...links, ['custom', 'context.reducer']])
  assert.equal(future.routes.length + future.relations.length, links.length + 1)
})

test('additional agent capabilities are retained across every row', () => {
  const all = Array.from({ length: 31 }, (_, i) => ({ id: `capability-${i}` }))
  const layout = layoutCapabilityGraph(all, [], 3)
  assert.equal(layout.nodes.length, 31)
  assert.equal(layout.nodes[30].row, 10)
  assert.equal(layout.routes.length, 0)
})
