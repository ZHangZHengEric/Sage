import { createRouter, createWebHistory } from 'vue-router'
import { getToken, isAdmin } from './auth.js'
import Login from './views/Login.vue'
import Chat from './views/Chat.vue'
import Models from './views/Models.vue'
import Agents from './views/Agents.vue'
import Mcp from './views/Mcp.vue'
import Skills from './views/Skills.vue'
import Admin from './views/Admin.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: Login, meta: { public: true } },
    { path: '/', component: Chat },
    { path: '/agents', component: Agents },
    { path: '/models', component: Models },
    { path: '/mcp', component: Mcp },
    { path: '/skills', component: Skills },
    { path: '/admin', component: Admin, meta: { admin: true } },
  ],
})

router.beforeEach((to) => {
  if (to.meta.public) return true
  if (!getToken()) {
    return { path: '/login', query: { next: to.fullPath } }
  }
  if (to.meta.admin && !isAdmin()) return '/'
  return true
})
