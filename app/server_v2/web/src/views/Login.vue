<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'
import { setSession } from '../auth.js'

const router = useRouter()
const route = useRoute()
const username = ref('')
const password = ref('')
const mode = ref('login')
const error = ref('')
const pending = ref(false)

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
    <form class="panel login-card" @submit.prevent="submit">
      <h1>{{ mode === 'login' ? '登录' : '注册' }}</h1>
      <label class="field">
        <span>用户名</span>
        <input v-model="username" autocomplete="username" required />
      </label>
      <label class="field">
        <span>密码</span>
        <input v-model="password" type="password" autocomplete="current-password" required />
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
</template>
