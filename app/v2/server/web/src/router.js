import { createRouter, createWebHistory } from 'vue-router'
import { getToken, isAdmin } from './auth.js'
import Login from './views/Login.vue'
import Chat from './views/Chat.vue'
import History from './views/History.vue'
import Tools from './views/Tools.vue'
import Users from './views/Users.vue'
const Models = () => import('./views/Models.vue')
const Agents = () => import('./views/Agents.vue')
const Studio = () => import('./views/Studio.vue')
import Mcp from './views/Mcp.vue'
import A2A from './views/A2A.vue'
import Skills from './views/Skills.vue'
import ApiKeys from './views/ApiKeys.vue'
import ExecutionSettings from './views/ExecutionSettings.vue'
import PersonalSettings from './views/PersonalSettings.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: Login, meta: { public: true } },
    { path: '/', component: Chat },
    { path: '/history', component: History },
    { path: '/tools', component: Tools },
    { path: '/plugins', component: () => import('./views/Plugins.vue'), meta: { admin: true } },
    { path: '/users', component: Users, meta: { admin: true } },
    { path: '/traces', component: () => import('./views/Traces.vue'), meta: { admin: true } },
    { path: '/performance', component: () => import('./views/Performance.vue'), meta: { admin: true } },
    { path: '/agents', component: Agents },
    { path: '/studio', component: Studio },
    { path: '/models', component: Models },
    { path: '/mcp', component: Mcp },
    { path: '/a2a', component: A2A },
    { path: '/keys', redirect: '/settings/keys' },
    { path: '/settings', component: PersonalSettings, children: [
      { path: '', redirect: '/settings/execution' },
      { path: 'execution', component: ExecutionSettings },
      { path: 'keys', component: ApiKeys },
    ] },
    { path: '/approvals', redirect: '/' },
    { path: '/skills', component: Skills },
    { path: '/admin', redirect: '/' },
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
