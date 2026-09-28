import { shallowMount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'

import AsyncQuestionnaireCard from '../AsyncQuestionnaireCard.vue'
import InlineQuestionnaireCard from '../InlineQuestionnaireCard.vue'

describe('AsyncQuestionnaireCard', () => {
  it('renders a normalized questionnaire and forwards the structured submission', async () => {
    const wrapper = shallowMount(AsyncQuestionnaireCard, {
      props: {
        toolCall: { id: 'call-1' },
        toolResult: {
          content: {
            success: true,
            validation_passed: true,
            title: 'Continue',
            questions: [{
              id: 'action',
              type: 'single_choice',
              text: 'Continue?',
              options: [{ value: 'continue', label: 'Continue' }],
              default: 'continue',
              allow_other: false,
            }],
          },
        },
        isLatest: true,
      },
      global: {
        plugins: [createPinia()],
      },
    })

    const card = wrapper.findComponent(InlineQuestionnaireCard)
    expect(card.exists()).toBe(true)
    expect(card.props('questionnaire')).toMatchObject({ id: 'call-1', tag: 'questionnaire' })
    expect(card.props('canSubmit')).toBe(true)

    card.vm.$emit('submit', { agentText: '<questionnaire-response />', displayText: 'Continue' })
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('sendMessage')).toEqual([
      ['<questionnaire-response />', { displayContent: 'Continue' }],
    ])
  })
})
