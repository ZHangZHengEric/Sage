// Presentation of the existing Session fields; no derived business state is stored.
export function newestThreads(items) {
  return [...items].sort((a, b) => (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0))
}

export function conversationAgent(item, agents, userId) {
  const ownerId = item._owner?.user_id || item.user_id || userId
  return agents.find(agent => agent.id === item.agent_id &&
    (agent._owner?.user_id || agent.user_id || userId) === ownerId)?.name || item.agent_id || '未绑定智能体'
}
