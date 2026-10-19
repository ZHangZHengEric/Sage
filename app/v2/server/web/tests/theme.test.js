import assert from 'node:assert/strict'
import { test } from 'node:test'
import { THEME_KEY, createThemeController, readThemePreference } from '../src/theme.js'

function environment(saved, dark = false) {
  const values = new Map(saved ? [[THEME_KEY, saved]] : []), listeners = new Set(), root = { dataset: {} }
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) }
  const media = { matches: dark, addEventListener: (_, fn) => listeners.add(fn), removeEventListener: (_, fn) => listeners.delete(fn) }
  return { root, storage, media, values, listeners, system(value) { media.matches = value; listeners.forEach(fn => fn()) } }
}
test('explicit theme survives system changes and reloads while system mode remains live', () => {
  const env = environment(null, true), controller = createThemeController(env)
  assert.equal(controller.mode, 'system'); assert.equal(env.root.dataset.theme, 'dark')
  controller.setMode('light'); env.system(false); env.system(true)
  assert.equal(env.root.dataset.theme, 'light')
  controller.dispose(); assert.equal(env.listeners.size, 0)
  const restored = createThemeController(env)
  assert.equal(restored.mode, 'light'); assert.equal(env.root.dataset.theme, 'light')
  restored.setMode('dark'); env.system(false)
  assert.equal(env.root.dataset.theme, 'dark')
  restored.setMode('system'); assert.equal(env.root.dataset.theme, 'light')
  env.system(true); assert.equal(env.root.dataset.theme, 'dark')
  restored.dispose()
})
test('invalid or unavailable storage uses system mode and never blocks an explicit choice', () => {
  const env = environment('unknown')
  assert.equal(readThemePreference(env.storage), 'system')
  env.storage = { getItem() { throw Error('blocked') }, setItem() { throw Error('blocked') } }
  const controller = createThemeController(env)
  assert.equal(env.root.dataset.theme, 'light')
  controller.setMode('dark'); assert.equal(env.root.dataset.theme, 'dark')
  controller.setMode('invalid'); assert.equal(controller.mode, 'dark')
  controller.dispose()
})
