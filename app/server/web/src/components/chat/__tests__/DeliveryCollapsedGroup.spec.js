import { shallowMount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'

import DeliveryCollapsedGroup from '../DeliveryCollapsedGroup.vue'
import MessageRenderer from '../MessageRenderer.vue'

describe('DeliveryCollapsedGroup', () => {
  it('forwards questionnaire display options with the raw agent message', async () => {
    const message = { id: 'message-1', role: 'assistant', content: 'Questionnaire' }
    const wrapper = shallowMount(DeliveryCollapsedGroup, {
      props: {
        group: {
          id: 'group-1',
          messages: [message],
          messageIndices: [0],
        },
        allMessages: [message],
        open: true,
      },
      global: {
        plugins: [createPinia()],
      },
    })

    wrapper.findComponent(MessageRenderer).vm.$emit(
      'sendMessage',
      '<questionnaire-response />',
      { displayContent: 'Continue' }
    )
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('sendMessage')).toEqual([
      ['<questionnaire-response />', { displayContent: 'Continue' }],
    ])
  })
})
