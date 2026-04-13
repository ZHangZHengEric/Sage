import { describe, expect, it, beforeEach, vi } from 'vitest'
import { shallowMount, flushPromises } from '@vue/test-utils'

import LoginModal from '../LoginModal.vue'

const { getSystemInfo } = vi.hoisted(() => ({
  getSystemInfo: vi.fn(),
}))

vi.mock('../../api/system.js', () => ({
  systemAPI: {
    getSystemInfo,
  },
}))

vi.mock('../../utils/auth.js', () => ({
  buildOAuthLoginUrl: vi.fn(() => '/api/auth/upstream/login/corp-sso'),
  loginAPI: vi.fn(),
  registerAPI: vi.fn(),
  sendRegisterVerificationCodeAPI: vi.fn(),
}))

const mountComponent = async () => {
  const wrapper = shallowMount(LoginModal, {
    props: {
      visible: true,
    },
    global: {
      stubs: {
        Teleport: true,
        Dialog: { template: '<div><slot /></div>' },
        DialogContent: { template: '<div><slot /></div>' },
        DialogHeader: { template: '<div><slot /></div>' },
        DialogTitle: { template: '<div><slot /></div>' },
        DialogDescription: { template: '<div><slot /></div>' },
        Button: { template: '<button><slot /></button>' },
        Input: { template: '<input />' },
        Label: { template: '<label><slot /></label>' },
        Loader: { template: '<span />' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('LoginModal', () => {
  beforeEach(() => {
    getSystemInfo.mockReset()
  })

  it('renders trusted proxy guidance with admin login when auth mode is trusted_proxy', async () => {
    getSystemInfo.mockResolvedValue({
      allow_registration: false,
      auth_mode: 'trusted_proxy',
      auth_providers: [
        { id: 'native', type: 'native', name: '账号密码' },
      ],
      oauth_enabled: false,
      oauth_provider_name: null,
    })

    const wrapper = await mountComponent()

    expect(wrapper.text()).toContain('企业身份接入')
    expect(wrapper.text()).toContain('企业身份代理模式')
    expect(wrapper.text()).toContain('管理员登录')
    expect(wrapper.text()).toContain('用户名')
    expect(wrapper.text()).toContain('密码')
  })

  it('renders oauth login flow when auth mode is oauth', async () => {
    getSystemInfo.mockResolvedValue({
      allow_registration: false,
      auth_mode: 'oauth',
      auth_providers: [
        { id: 'corp-sso', type: 'oidc', name: 'Corp SSO' },
      ],
      oauth_enabled: true,
      oauth_provider_name: 'Corp SSO',
    })

    const wrapper = await mountComponent()

    expect(wrapper.text()).toContain('统一登录')
    expect(wrapper.text()).toContain('使用Corp SSO登录')
    expect(wrapper.text()).not.toContain('企业身份代理模式')
  })

  it('renders native login form when auth mode is native', async () => {
    getSystemInfo.mockResolvedValue({
      allow_registration: true,
      auth_mode: 'native',
      auth_providers: [
        { id: 'native', type: 'native', name: '账号密码' },
      ],
      oauth_enabled: false,
      oauth_provider_name: null,
    })

    const wrapper = await mountComponent()

    expect(wrapper.text()).toContain('用户登录')
    expect(wrapper.text()).toContain('用户名')
    expect(wrapper.text()).toContain('密码')
    expect(wrapper.text()).not.toContain('企业身份代理模式')
    expect(wrapper.text()).not.toContain('统一登录')
  })

  it('treats native id as local auth even when type is missing', async () => {
    getSystemInfo.mockResolvedValue({
      allow_registration: true,
      auth_mode: 'native',
      auth_providers: [
        { id: 'native', name: '账号密码' },
      ],
      oauth_enabled: false,
      oauth_provider_name: null,
    })

    const wrapper = await mountComponent()

    expect(wrapper.text()).toContain('用户登录')
    expect(wrapper.text()).toContain('用户名')
    expect(wrapper.text()).toContain('密码')
  })
})
