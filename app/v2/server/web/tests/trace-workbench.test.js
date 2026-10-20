import test from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, nextTick, ssrContextKey } from 'vue'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

test('changing filters ignores stale pages and raw records are only fetched on selection', async t => {
  const server = await createServer({ configFile:false, plugins:[vue()], server:{middlewareMode:true}, optimizeDeps:{noDiscovery:true,include:[]} })
  t.after(() => server.close())
  const { api } = await server.ssrLoadModule('/src/api.js')
  const { default: Component } = await server.ssrLoadModule('/src/components/TraceWorkbench.vue')
  const params = {start:'2026-10-20T00:00:00Z',end:'2026-10-21T00:00:00Z',agent_id:'writer'}
  t.mock.method(api,'traceSummary',async () => ({tokens:100}))
  let finishOldPage
  t.mock.method(api,'traceSpans',query => query.kind === 'AGENT'
    ? new Promise(resolve => {finishOldPage=resolve})
    : Promise.resolve({items:[{span_id:'new',name:'model.request'}],next_cursor:'cursor-2'}))
  let finishOldDetail
  t.mock.method(api,'traceSpan',id => id==='old'
    ? new Promise(resolve => {finishOldDetail=resolve}) : Promise.resolve({name:'current'}))
  const renderer = createRenderer({createComment:()=>({}),insert(){},remove(){},parentNode:()=>null,nextSibling:()=>null})
  const app = renderer.createApp({...Component,render:()=>null},{params})
  app.provide(ssrContextKey,{})
  const vm = app.mount({}), state=vm.$.setupState
  t.after(() => app.unmount())
  await nextTick()
  assert.equal(api.traceSpan.mock.callCount(),0)
  state.kind='LLM'; await nextTick(); await new Promise(resolve=>setImmediate(resolve))
  finishOldPage({items:[{span_id:'stale'}],next_cursor:null})
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(state.rows[0].span_id,'new')
  assert.deepEqual(api.traceSpans.mock.calls.at(-1).arguments[0],{...params,kind:'LLM',status:''})
  const oldDetail=state.select({span_id:'old'})
  await state.select({span_id:'new'})
  finishOldDetail({name:'stale'}); await oldDetail
  assert.equal(state.detail.name,'current')
  assert.equal(state.selected,'new')
  state.applySession(' session-one ')
  await nextTick(); await new Promise(resolve=>setImmediate(resolve))
  assert.equal(api.traceSpans.mock.calls.at(-1).arguments[0].session_id,'session-one')
  assert.equal(api.traceSummary.mock.calls.at(-1).arguments[0].session_id,'session-one')
  state.applySession(''); await nextTick(); await new Promise(resolve=>setImmediate(resolve))
  assert.equal(Object.hasOwn(api.traceSpans.mock.calls.at(-1).arguments[0],'session_id'),false)
  state.close()
  assert.equal(state.detail,null)
})
