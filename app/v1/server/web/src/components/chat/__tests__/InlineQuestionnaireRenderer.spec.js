import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import InlineQuestionnaireRenderer from '../InlineQuestionnaireRenderer.vue'
import MarkdownRenderer from '../MarkdownRenderer.vue'
import MarkdownRendererWithPreview from '../MarkdownRendererWithPreview.vue'

describe('InlineQuestionnaireRenderer', () => {
  it('preserves artifacts as visible markdown when Server Web has no artifact card', () => {
    const source = '<sage-artifacts>{"title":"Result","items":[{"path":"/tmp/report.pdf"}]}</sage-artifacts>'
    const wrapper = mount(InlineQuestionnaireRenderer, {
      props: { content: source, messageId: 'message-1' },
    })

    expect(wrapper.text()).toContain('"title":"Result"')
    expect(wrapper.text()).toContain('/tmp/report.pdf')
  })

  it('uses the plain markdown renderer when previews are disabled for user content', () => {
    const wrapper = mount(InlineQuestionnaireRenderer, {
      props: {
        content: '[report](/tmp/report.pdf)',
        messageId: 'user-message',
        withPreview: false,
      },
    })

    expect(wrapper.findComponent(MarkdownRenderer).exists()).toBe(true)
    expect(wrapper.findComponent(MarkdownRendererWithPreview).exists()).toBe(false)
    expect(wrapper.find('.file-icons-container').exists()).toBe(false)
  })
})
