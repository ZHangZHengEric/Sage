<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from './api.js'
import { clearSession, getUser, isAdmin } from './auth.js'

const route = useRoute()
const router = useRouter()
const publicPage = computed(() => route.path === '/login')
const user = computed(() => getUser())

async function logout() {
  try {
    await api.logout()
  } catch {
    // local session still has to go even if the cookie clear fails
  }
  clearSession()
  router.push('/login')
}
</script>

<template>
  <div v-if="publicPage">
    <router-view />
  </div>
  <div v-else class="shell">
    <header class="topbar">
      <div class="brand">Sage <span>Server v2</span></div>
      <nav aria-label="主导航">
        <router-link to="/">对话</router-link>
        <router-link to="/models">模型</router-link>
        <router-link v-if="isAdmin()" to="/admin">总览</router-link>
      </nav>
      <div class="userbox">
        <span>{{ user?.username }}</span>
        <button class="btn ghost" type="button" @click="logout">退出</button>
      </div>
    </header>
    <main class="stage" :class="{ 'stage-chat': route.path === '/' }">
      <router-view />
    </main>
  </div>
</template>
