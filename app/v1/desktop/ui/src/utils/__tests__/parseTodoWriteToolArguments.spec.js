import { describe, expect, it } from 'vitest'
import { parseTodoWriteToolCallArguments } from '../parseTodoWriteToolArguments.js'

describe('parseTodoWriteToolCallArguments', () => {
  it('parses complete JSON string', () => {
    const raw = '{"tasks":[{"id":"a","content":"x"}],"session_id":"s1"}'
    const { taskIdsOrdered, tasks } = parseTodoWriteToolCallArguments(raw)
    expect(taskIdsOrdered).toEqual(['a'])
    expect(tasks).toHaveLength(1)
  })

  it('extracts ids from incomplete JSON (streaming)', () => {
    const raw = '{"tasks":[{"id":"t1","content":"等待用户'
    const { taskIdsOrdered, tasks } = parseTodoWriteToolCallArguments(raw)
    expect(taskIdsOrdered).toEqual(['t1'])
    expect(tasks).toEqual([])
  })

  it('handles object arguments', () => {
    const raw = { tasks: [{ id: 'u1', content: 'c' }] }
    const { taskIdsOrdered } = parseTodoWriteToolCallArguments(raw)
    expect(taskIdsOrdered).toEqual(['u1'])
  })

  it('dedupes ids in fragment', () => {
    const raw = '"tasks":[{"id":"x"},{"id":"x","status"'
    const { taskIdsOrdered } = parseTodoWriteToolCallArguments(raw)
    expect(taskIdsOrdered).toEqual(['x'])
  })
})
