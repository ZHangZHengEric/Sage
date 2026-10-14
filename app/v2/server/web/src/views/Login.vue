<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'
import { setSession } from '../auth.js'
import AnimatedCharactersStage from '../components/auth/AnimatedCharactersStage.vue'

const router = useRouter()
const route = useRoute()
const username = ref('')
const password = ref('')
const mode = ref('login')
const error = ref('')
const pending = ref(false)
const isTyping = ref(false), showPassword = ref(false)

async function submit() {
  error.value = ''
  pending.value = true
  try {
    if (mode.value === 'register') {
      await api.register(username.value, password.value)
    }
    const data = await api.login(username.value, password.value)
    setSession(data.access_token, data.user)
    const next = typeof route.query.next === 'string' ? route.query.next : '/'
    router.push(next.startsWith('/') ? next : '/')
  } catch (exc) {
    error.value = exc.message
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="login">
    <AnimatedCharactersStage :is-typing="isTyping" :password-length="password.length" :show-password="showPassword" />
    <div class="login-form-panel">
    <form class="login-card" @submit.prevent="submit">
      <div class="login-brand mobile-login-brand"><img src="/sage_logo.svg" alt="" />Sage V2</div>
      <h1>{{ mode === 'login' ? '登录' : '注册' }}</h1>
      <label class="field">
        <span>用户名</span>
        <input v-model="username" autocomplete="username" required @focus="isTyping = true" @blur="isTyping = false" />
      </label>
      <label class="field">
        <span>密码</span>
        <div class="password-field"><input v-model="password" aria-label="密码" :type="showPassword ? 'text' : 'password'" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" required /><button type="button" :aria-pressed="showPassword" @click="showPassword = !showPassword">{{ showPassword ? '隐藏' : '显示' }}</button></div>
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="row">
        <button class="btn cta" type="submit" :disabled="pending">
          {{ mode === 'login' ? '登录' : '注册并登录' }}
        </button>
        <button class="btn ghost" type="button" @click="mode = mode === 'login' ? 'register' : 'login'">
          {{ mode === 'login' ? '去注册' : '去登录' }}
        </button>
      </div>
    </form>
    </div>
  </div>
</template>

<style scoped>
.login { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); place-items: stretch; padding: 0; min-height: 100dvh; }
.login-brand { display: flex; align-items: center; gap: 8px; font-size: 18px; font-weight: 600; }
.login-brand img { width: 32px; height: 32px; border-radius: 8px; }
.password-field { position: relative; }
.password-field input { width: 100%; padding-right: 60px; }
.password-field button { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); border: 0; background: transparent; color: var(--muted-foreground); font-size: 12px; padding: 6px; }
.login-form-panel { display: grid; place-items: center; width: 100%; padding: 48px; }
.login-card { width: min(420px, 100%); }
.login-card h1 { font-size: 28px; margin-bottom: 32px; }
.login-card input { height: 44px; }
.login-card .row { flex-direction: column; margin-top: 24px; }
.login-card .btn { height: 44px; }
.mobile-login-brand { display: none; }
@media (max-width: 1023px) { .login { grid-template-columns: 1fr; } .login-form-panel { padding: 32px 24px; } .mobile-login-brand { display: flex; margin-bottom: 32px; } }
</style>
