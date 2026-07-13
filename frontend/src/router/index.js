import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/login',
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { title: '舆情看板', icon: 'DataLine' },
  },
  {
    path: '/event-board',
    name: 'EventBoard',
    component: () => import('@/views/EventBoard.vue'),
    meta: { title: '事件看板', icon: 'TrendCharts' },
  },
  {
    path: '/event/:id',
    name: 'EventDetail',
    component: () => import('@/views/EventDetailView.vue'),
    meta: { title: '事件详情', icon: 'Document' },
  },
  {
    path: '/qa',
    name: 'QA',
    component: () => import('@/views/QAView.vue'),
    meta: { title: '智能问答', icon: 'ChatDotRound' },
  },
  {
    path: '/data-collection',
    name: 'DataCollection',
    component: () => import('@/views/DataCollectionView.vue'),
    meta: { title: '数据采集', icon: 'FolderOpened' },
  },
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('@/views/ProfileView.vue'),
    meta: { title: '个人中心', icon: 'User' },
  },
  {
    path: '/user-profile',
    name: 'UserProfile',
    component: () => import('@/views/UserProfileView.vue'),
    meta: { title: '用户画像', icon: 'UserFilled' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录跳转到登录页
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (!to.meta.public && !token) {
    next('/login')
  } else {
    next()
  }
})

export default router
