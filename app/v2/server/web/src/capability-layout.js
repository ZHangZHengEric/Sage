const agentOrder = ['skill.loading', 'context.reducer', 'context.summarizer', 'tool.selection-policy', 'model.provider', 'memory.recall-query', null, 'agent.continuation-policy']

// The Agent dependency tree has a planar three-column embedding. Keep these
// slots stable as implementations change; new capabilities fill unused slots.
export function layoutCapabilityGraph(nodes, links = [], columns = 3) {
  const width = 208, height = 92, gap = 52, rowGap = 92, margin = 24
  let ordered = [...nodes]
  if (columns === 3) {
    ordered = agentOrder.map(id => nodes.find(node => node.id === id) || null)
    for (const node of nodes.filter(node => !agentOrder.includes(node.id))) {
      const empty = ordered.indexOf(null)
      if (empty === -1) ordered.push(node); else ordered[empty] = node
    }
    while (ordered.length && !ordered.at(-1)) ordered.pop()
  }
  const positioned = ordered.flatMap((node, i) => node ? [{ ...node, row: Math.floor(i / columns), column: i % columns,
    x: margin + (i % columns) * (width + gap), y: margin + Math.floor(i / columns) * (height + rowGap), width, height }] : [])
  const byId = new Map(positioned.map(node => [node.id, node]))
  const routes = [], relations = []
  for (const [from, to] of links) {
    const a = byId.get(from), b = byId.get(to)
    if (!a || !b) continue
    let points
    if (columns === 3) {
      if ((from === 'context.reducer' && to === 'context.summarizer') || (from === 'tool.selection-policy' && to === 'model.provider')) points = [[a.x + width, a.y + height / 2], [b.x, b.y + height / 2]]
      if (from === 'memory.recall-query' && to === 'model.provider') points = [[a.x, a.y + height / 2], [b.x + width, b.y + height / 2]]
      if (from === 'context.summarizer' && to === 'model.provider') {
        const lane = a.y + height + rowGap / 2
        points = [[a.x + width / 2, a.y + height], [a.x + width / 2, lane], [b.x + width / 2, lane], [b.x + width / 2, b.y]]
      }
      if (from === 'agent.continuation-policy' && to === 'model.provider') points = [[a.x + width / 2, a.y], [b.x + width / 2, b.y + height]]
    }
    const edge = { from, to, source: a.name, target: b.name }
    if (points) routes.push({ ...edge, points, path: points.map(([x, y], i) => `${i ? 'L' : 'M'}${x} ${y}`).join(' ') })
    else relations.push(edge)
  }
  const count = Math.max(1, Math.ceil(ordered.length / columns))
  return { nodes: positioned, routes, relations, width: margin * 2 + columns * width + (columns - 1) * gap,
    height: margin * 2 + count * height + (count - 1) * rowGap }
}
