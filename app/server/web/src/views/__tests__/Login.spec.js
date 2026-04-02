import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'

import Login from '../Login.vue'

const routerReplace = vi.fn()
const { getSystemInfo } = vi.hoisted(() => ({
  getSystemInfo: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    replace: routerReplace,
  }),
  useRoute: () => ({
    query: {},
  }),
}))

vi.mock('@/api/system.js', () => ({
  systemAPI: {
    getSystemInfo,
  },
}))

vi.mock('@/utils/auth.js', () => ({
  buildOAuthLoginUrl: vi.fn((providerId) => `/oauth/${providerId}`),
  loginAPI: vi.fn(),
  registerAPI: vi.fn(),
  sendRegisterVerificationCodeAPI: vi.fn(),
}))

vi.mock('@/utils/i18n.js', () => ({
  useLanguage: () => ({
    toggleLanguage: vi.fn(),
    isZhCN: true,
    t: (key, params = {}) => {
      if (key === 'auth.continueWith') {
        return `Continue with ${params.provider}`
      }
      return key
    },
  }),
}))

vi.mock('vue-sonner', () => ({
  toast: {
    success: vi.fn(),
  },
}))

const mountComponent = async () => {
  const wrapper = shallowMount(Login, {
    global: {
      stubs: {
        AnimatedCharactersStage: { template: '<div />' },
        Button: { template: '<button><slot /></button>' },
        Checkbox: { template: '<input type="checkbox" />' },
        Input: { template: '<input />' },
        Label: { template: '<label><slot /></label>' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('Login view', () => {
  beforeEach(() => {
    getSystemInfo.mockReset()
    routerReplace.mockReset()
  })

  it('treats native auth providers as local login and renders the credentials form', async () => {
    getSystemInfo.mockResolvedValue({
      allow_registration: false,
      auth_providers: [
        { id: 'native', type: 'native', name: '账号密码' },
      ],
    })

    const wrapper = await mountComponent()

    expect(wrapper.find('form').exists()).toBe(true)
    expect(wrapper.text()).toContain('auth.welcomeBack')
    expect(wrapper.text()).not.toContain('Continue with 账号密码')
  })
})
