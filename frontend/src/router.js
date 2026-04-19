import { createRouter, createWebHistory } from 'vue-router'
import ChatPage from './components/ChatPage.vue'
import KnowledgeBrowser from './components/KnowledgeBrowser.vue'

const routes = [
  { path: '/', name: 'chat', component: ChatPage },
  { path: '/kb', name: 'kb', component: KnowledgeBrowser },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
