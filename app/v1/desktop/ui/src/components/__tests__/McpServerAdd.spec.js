import { describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'

import McpServerAdd from '../McpServerAdd.vue'

vi.mock('../../utils/i18n.js', () => ({
  useLanguage: () => ({
    t: (key) => key,
  }),
}))

const mountComponent = () => shallowMount(McpServerAdd, {
  global: {
    stubs: {
      Database: { template: '<span />' },
      Code: { template: '<span />' },
      Globe: { template: '<span />' },
      Loader: { template: '<span />' },
      Plus: { template: '<span />' },
      Trash2: { template: '<span />' },
      Sparkles: { template: '<span />' },
      WandSparkles: { template: '<span />' },
      Play: { template: '<span />' },
      Button: { template: '<button><slot /></button>' },
      Input: {
        props: ['id', 'modelValue', 'type', 'placeholder', 'readonly', 'required'],
        emits: ['update:modelValue'],
        template: '<input :id="id" :type="type" :value="modelValue" :placeholder="placeholder" :readonly="readonly" :required="required" @input="$emit(\'update:modelValue\', $event.target.value)" />',
      },
      Label: { template: '<label><slot /></label>' },
      Textarea: { template: '<textarea />' },
      Badge: { template: '<span><slot /></span>' },
      Select: { template: '<div><slot /></div>' },
      SelectContent: { template: '<div><slot /></div>' },
      SelectItem: { template: '<div><slot /></div>' },
      SelectTrigger: { template: '<div><slot /></div>' },
      SelectValue: { template: '<div />' },
      Switch: { template: '<button />' },
      AnyToolSchemaFieldEditor: { template: '<div />' },
    },
  },
})

describe('McpServerAdd', () => {
  it('submits api_key for SSE MCP servers', async () => {
    const wrapper = mountComponent()

    wrapper.vm.setFormData({
      name: 'secure-sse',
      protocol: 'sse',
      sse_url: 'https://mcp.example/sse',
      api_key: 'sse-token',
    })
    await wrapper.find('form').trigger('submit')

    expect(wrapper.emitted('submit')[0][0]).toEqual(expect.objectContaining({
      name: 'secure-sse',
      kind: 'external',
      protocol: 'sse',
      sse_url: 'https://mcp.example/sse',
      api_key: 'sse-token',
    }))
  })

  it('submits api_key for Streamable HTTP MCP servers', async () => {
    const wrapper = mountComponent()

    wrapper.vm.setFormData({
      name: 'secure-http',
      protocol: 'streamable_http',
      streamable_http_url: 'https://mcp.example/mcp',
      api_key: 'http-token',
    })
    await wrapper.find('form').trigger('submit')

    expect(wrapper.emitted('submit')[0][0]).toEqual(expect.objectContaining({
      name: 'secure-http',
      kind: 'external',
      protocol: 'streamable_http',
      streamable_http_url: 'https://mcp.example/mcp',
      api_key: 'http-token',
    }))
  })

  it('does not submit api_key for stdio MCP servers', async () => {
    const wrapper = mountComponent()

    wrapper.vm.setFormData({
      name: 'stdio-server',
      protocol: 'stdio',
      command: 'node',
      args: ['server.js'],
      api_key: 'unused-token',
    })
    await wrapper.find('form').trigger('submit')

    expect(wrapper.emitted('submit')[0][0]).toEqual({
      name: 'stdio-server',
      kind: 'external',
      protocol: 'stdio',
      description: '',
      command: 'node',
      args: ['server.js'],
    })
  })
})
