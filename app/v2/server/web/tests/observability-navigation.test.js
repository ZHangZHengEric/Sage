import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, createSSRApp, nextTick, ssrContextKey } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createServer } from 'vite'

const performance = { id: 'performance', label: '运行性能', href: '/performance', external: false }
const traces = { id: 'traces', label: '调用链', href: '/traces', external: false }
const phoenix = { id: 'phoenix', label: 'Phoenix', href: 'https://phoenix.example', external: true }
const settle = async () => { await new Promise(resolve => setImmediate(resolve)); await nextTick() }

async function setup(t) {
  const server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  const { api } = await server.ssrLoadModule('/src/api.js')
  const { default: Component } = await server.ssrLoadModule('/src/components/ObservabilityNav.vue')
  const { default: AppIcon } = await server.ssrLoadModule('/src/components/AppIcon.vue')
  return { api, Component, AppIcon, mount: async () => {
    const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
    const app = renderer.createApp({ ...Component, render: () => null })
    app.provide(ssrContextKey, {})
    const vm = app.mount({})
    t.after(() => app.unmount())
    await settle()
    return vm.$.setupState
  } }
}

test('observability loads backend services and can retry a failed request', async t => {
  const { api, mount } = await setup(t)
  let fail = true
  t.mock.method(api, 'observabilityServices', async () => {
    if (fail) throw Error('offline')
    return [performance, phoenix]
  })
  const state = await mount()
  assert.equal(state.error, true)
  assert.equal(state.loading, false)
  assert.deepEqual(state.services, [])
  fail = false
  await state.load()
  assert.equal(state.error, false)
  assert.deepEqual(state.services, [performance, phoenix])
})

test('observability renders only advertised links and opens consoles in a separate window', async t => {
  const { Component, AppIcon } = await setup(t)
  const render = async services => {
    const app = createSSRApp({ ...Component, setup: () => ({ services, loading: false, error: false, AppIcon }) })
    app.component('router-link', { props: ['to'], template: '<a :href="to"><slot /></a>' })
    return renderToString(app)
  }
  const html = await render([performance, phoenix])
  assert.match(html, /观测/)
  assert.match(html, /href="\/performance"/)
  assert.match(html, /href="https:\/\/phoenix.example" target="_blank" rel="noopener noreferrer"/)
  assert.doesNotMatch(html, /Jaeger|Langfuse/)
  assert.doesNotMatch(await render([]), /观测|运行性能|Phoenix/)
  assert.doesNotMatch(await render([performance]), /Phoenix|target="_blank"/)
})

test('traces is a sibling of performance under the observability menu', async t => {
  const { Component, AppIcon } = await setup(t)
  const app = createSSRApp({ ...Component, setup: () => ({services:[performance,traces],loading:false,error:false,AppIcon}) })
  app.component('router-link', {props:['to'],template:'<a :href="to"><slot /></a>'})
  const html = await renderToString(app)
  assert.match(html, /href="\/performance"/)
  assert.match(html, /href="\/traces"/)
  assert.match(html, /调用链/)
  assert.equal((html.match(/<details/g) || []).length, 1)
})
