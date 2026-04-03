import { describe, expect, it } from 'vitest'

import {
  collectViolationsFromDiff,
  shouldCheckFile,
} from './check-i18n-literals.mjs'

describe('shouldCheckFile', () => {
  it('accepts frontend source files and ignores locales and tests', () => {
    expect(shouldCheckFile('app/server/web/src/views/Login.vue')).toBe(true)
    expect(shouldCheckFile('app/server/web/src/locales/zh-CN.js')).toBe(false)
    expect(shouldCheckFile('app/server/web/src/components/__tests__/LoginModal.spec.js')).toBe(false)
    expect(shouldCheckFile('app/server/web/src/views/Login.spec.js')).toBe(false)
  })
})

describe('collectViolationsFromDiff', () => {
  it('reports newly added hard-coded Chinese copy', () => {
    const diff = [
      'diff --git a/app/server/web/src/views/Login.vue b/app/server/web/src/views/Login.vue',
      '+++ b/app/server/web/src/views/Login.vue',
      '@@ -10,0 +11,2 @@',
      '+<span>请选择登录方式</span>',
      '+toast.error("请输入密码")',
    ].join('\n')

    const violations = collectViolationsFromDiff(diff)

    expect(violations).toHaveLength(2)
    expect(violations[0].line).toContain('请选择登录方式')
    expect(violations[1].line).toContain('请输入密码')
  })

  it('ignores i18n calls and comment lines', () => {
    const diff = [
      'diff --git a/app/server/web/src/views/Login.vue b/app/server/web/src/views/Login.vue',
      '+++ b/app/server/web/src/views/Login.vue',
      '@@ -10,0 +11,4 @@',
      '+<!-- 登录页中文注释 -->',
      '+// 这是注释',
      '+{{ t(\'auth.chooseProvider\') }}',
      '+toast.error(t(\'auth.requiredFields\'))',
    ].join('\n')

    const violations = collectViolationsFromDiff(diff)

    expect(violations).toHaveLength(0)
  })
})
