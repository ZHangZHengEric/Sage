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

  it('falls back to native id when provider type is missing', async () => {
    getSystemInfo.mockResolvedValue({
      allow_registration: false,
      auth_providers: [
        { id: 'native', name: '账号密码' },
      ],
    })

    const wrapper = await mountComponent()

    expect(wrapper.find('form').exists()).toBe(true)
    expect(wrapper.text()).toContain('auth.welcomeBack')
    expect(wrapper.text()).not.toContain('Continue with 账号密码')
  })

  it('shows the registration-disabled notice with desktop and contact info when registration is off', async () => {
    getSystemInfo.mockResolvedValue({
      allow_registration: false,
      auth_providers: [
        { id: 'native', type: 'native', name: '账号密码' },
      ],
    })

    const wrapper = await mountComponent()

    expect(wrapper.text()).toContain('auth.registrationDisabledTitle')
    expect(wrapper.text()).toContain('auth.registrationDisabledIntro')
    expect(wrapper.text()).toContain('auth.registrationDisabledContactWeChat1')
    expect(wrapper.text()).toContain('auth.registrationDisabledContactWeChat2')
    const desktopLink = wrapper.find('a[href="https://zavixai.com/html/sage.html"]')
    expect(desktopLink.exists()).toBe(true)
    const repoLink = wrapper.find('a[href="https://github.com/ZHangZHengEric/Sage"]')
    expect(repoLink.exists()).toBe(true)
  })

  it('hides the registration-disabled notice when registration is allowed', async () => {
    getSystemInfo.mockResolvedValue({
      allow_registration: true,
      auth_providers: [
        { id: 'native', type: 'native', name: '账号密码' },
      ],
    })

    const wrapper = await mountComponent()

    expect(wrapper.text()).not.toContain('auth.registrationDisabledTitle')
    expect(wrapper.find('a[href="https://zavixai.com/html/sage.html"]').exists()).toBe(false)
  })
})
