<template>
  <!-- 登录页不显示侧边栏布局 -->
  <template v-if="isLoginPage">
    <router-view />
  </template>

  <!-- 后台管理布局：侧边栏 + 顶部栏 + 内容区 -->
  <el-container v-else class="app-layout">
    <!-- 侧边栏 -->
    <el-aside :width="isCollapse ? '64px' : '220px'" class="sidebar">
      <div class="logo-area">
        <img src="/logo.jpg" alt="智舆Logo" class="logo-img" />
        <span v-if="!isCollapse" class="logo-text">智舆</span>
      </div>

      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapse"
        :collapse-transition="false"
        router
        background-color="transparent"
        text-color="#94a3b8"
        active-text-color="#e2e8f0"
        class="sidebar-menu"
      >
        <el-menu-item index="/dashboard">
          <el-icon><DataLine /></el-icon>
          <template #title>舆情看板</template>
        </el-menu-item>

        <el-menu-item index="/event-board">
          <el-icon><TrendCharts /></el-icon>
          <template #title>事件看板</template>
        </el-menu-item>

        <el-menu-item index="/event/1">
          <el-icon><Document /></el-icon>
          <template #title>事件详情</template>
        </el-menu-item>

        <el-menu-item index="/qa">
          <el-icon><ChatDotRound /></el-icon>
          <template #title>智能问答</template>
        </el-menu-item>

        <el-menu-item index="/data-collection">
          <el-icon><FolderOpened /></el-icon>
          <template #title>数据采集</template>
        </el-menu-item>

        <el-menu-item index="/profile">
          <el-icon><User /></el-icon>
          <template #title>个人中心</template>
        </el-menu-item>

        <el-menu-item index="/user-profile">
          <el-icon><UserFilled /></el-icon>
          <template #title>用户画像</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container class="main-container">
      <!-- 顶部导航栏 -->
      <el-header class="top-header">
        <div class="header-left">
          <el-icon
            class="collapse-btn"
            :size="20"
            @click="toggleCollapse"
          >
            <Fold v-if="!isCollapse" />
            <Expand v-else />
          </el-icon>
          <el-breadcrumb separator="/" class="app-breadcrumb">
            <el-breadcrumb-item :to="{ path: '/dashboard' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item>{{ route.meta?.title || '页面' }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="header-right">
          <!-- 搜索框 -->
          <el-input
            v-model="searchKeyword"
            placeholder="搜索事件..."
            prefix-icon="Search"
            clearable
            class="header-search"
            @keyup.enter="handleSearch"
          />

          <!-- 全屏按钮 -->
          <el-tooltip content="全屏">
            <el-icon class="header-icon" :size="18" @click="toggleFullscreen">
              <FullScreen />
            </el-icon>
          </el-tooltip>

          <!-- 通知 -->
          <el-badge :value="3" class="header-badge">
            <el-icon class="header-icon" :size="18"><Bell /></el-icon>
          </el-badge>

          <!-- 用户信息下拉 -->
          <el-dropdown @command="handleCommand">
            <div class="user-info">
              <el-avatar :size="32" :icon="UserFilled" />
              <span class="username">{{ userInfo.username || '管理员' }}</span>
              <el-icon><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">
                  <el-icon><User /></el-icon> 个人中心
                </el-dropdown-item>
                <el-dropdown-item command="settings">
                  <el-icon><Setting /></el-icon> 系统设置
                </el-dropdown-item>
                <el-dropdown-item divided command="logout">
                  <el-icon><SwitchButton /></el-icon> 退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <!-- 标签页（可选） -->
      <div class="tabs-bar">
        <el-tag
          v-for="tag in visitedTags"
          :key="tag.path"
          :type="activeTag === tag.path ? 'primary' : 'info'"
          :closable="tag.path !== '/dashboard'"
          size="small"
          class="tab-tag"
          @click="$router.push(tag.path)"
          @close="closeTag(tag)"
        >
          {{ tag.title }}
        </el-tag>
      </div>

      <!-- 主内容区 -->
      <el-main class="main-content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Fold, Expand, Search, FullScreen, Bell, UserFilled,
  ArrowDown, Setting, SwitchButton, HomeFilled, FolderOpened,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

// 侧边栏折叠
const isCollapse = ref(false)
const toggleCollapse = () => {
  isCollapse.value = !isCollapse.value
}

// 当前激活的菜单
const activeMenu = computed(() => route.path)

// 是否是登录页
const isLoginPage = computed(() => route.path === '/login')

// 搜索
const searchKeyword = ref('')
const handleSearch = () => {
  if (searchKeyword.value.trim()) {
    router.push(`/dashboard?keyword=${encodeURIComponent(searchKeyword.value)}`)
  }
}

// 全屏
const toggleFullscreen = () => {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen()
  } else {
    document.exitFullscreen()
  }
}

// 用户信息
const userInfo = ref({ username: '' })

onMounted(() => {
  const saved = localStorage.getItem('user')
  if (saved) {
    try { userInfo.value = JSON.parse(saved) } catch {}
  }
})

// 标签页
const visitedTags = ref([
  { path: '/dashboard', title: '舆情看板' },
])
const activeTag = computed(() => route.path)

watch(() => route.path, (newPath) => {
  const meta = route.meta
  if (meta && meta.title) {
    const exists = visitedTags.value.find(t => t.path === newPath)
    if (!exists) {
      visitedTags.value.push({ path: newPath, title: meta.title })
    }
  }
}, { immediate: true })

const closeTag = (tag) => {
  const idx = visitedTags.value.findIndex(t => t.path === tag.path)
  visitedTags.value.splice(idx, 1)
  if (activeTag.value === tag.path) {
    const prev = visitedTags.value[idx - 1] || visitedTags.value[0]
    router.push(prev.path)
  }
}

// 用户下拉菜单
const handleCommand = (cmd) => {
  if (cmd === 'profile') router.push('/profile')
  if (cmd === 'settings') { /* 预留 */ }
  if (cmd === 'logout') {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    router.push('/login')
  }
}
</script>

<style scoped>
/* ========== 整体布局 ========== */
.app-layout {
  height: 100vh;
  width: 100vw;
}

/* ========== 侧边栏 ========== */
.sidebar {
  background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
  transition: width 0.3s;
  display: flex;
  flex-direction: column;
}

.logo-area {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  padding: 0 20px;
  gap: 10px;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  flex-shrink: 0;
}

.logo-img {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  object-fit: cover;
  flex-shrink: 0;
}

.logo-text {
  background: linear-gradient(135deg, #60a5fa, #a78bfa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 2px;
  white-space: nowrap;
}

.sidebar-menu {
  border-right: none;
  flex: 1;
}

.sidebar-menu :deep(.el-menu-item) {
  font-size: 14px;
  height: 50px;
  line-height: 50px;
  position: relative;
  transition: all 0.25s ease;
  border-left: 2px solid transparent;
  margin: 2px 0;
}

.sidebar-menu :deep(.el-menu-item:hover) {
  background: rgba(96, 165, 250, 0.08) !important;
  border-left: 2px solid transparent;
  border-image: linear-gradient(180deg, #60a5fa, #a78bfa) 1;
}

.sidebar-menu :deep(.el-menu-item.is-active) {
  background: rgba(96, 165, 250, 0.12) !important;
  border-right: none;
  border-left: 2px solid transparent;
  border-image: linear-gradient(180deg, #60a5fa, #a78bfa) 1;
  color: #e2e8f0 !important;
  text-shadow: 0 0 12px rgba(96, 165, 250, 0.3);
}

.sidebar-menu :deep(.el-menu-item.is-active .el-icon) {
  color: #60a5fa;
}

/* ========== 顶部栏 ========== */
.top-header {
  height: 60px;
  background: #fff;
  border-bottom: 1px solid rgba(255, 255, 255, 0.6);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  box-shadow:
    0 1px 3px rgba(0, 0, 0, 0.04),
    0 1px 2px rgba(0, 0, 0, 0.02);
  backdrop-filter: blur(8px);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 15px;
}

.collapse-btn {
  cursor: pointer;
  color: #606266;
  transition: color 0.2s;
}

.collapse-btn:hover {
  color: #409eff;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 18px;
}

.header-search {
  width: 220px;
}

.header-search :deep(.el-input__wrapper) {
  border-radius: 20px;
  padding: 0 16px;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.06) inset;
  transition: all 0.3s ease;
}

.header-search :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgba(96, 165, 250, 0.4) inset;
}

.header-search :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px rgba(96, 165, 250, 0.6) inset, 0 0 0 3px rgba(96, 165, 250, 0.1);
}

.header-search :deep(.el-input__inner) {
  font-size: 13px;
}

.header-icon {
  cursor: pointer;
  color: #606266;
  transition: color 0.2s;
}

.header-icon:hover {
  color: #409eff;
}

.header-badge :deep(.el-badge__content) {
  top: 6px;
  right: 6px;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 12px;
  transition: all 0.25s ease;
}

.user-info:hover {
  background: rgba(96, 165, 250, 0.06);
}

.username {
  font-size: 14px;
  color: #606266;
}

/* ========== 标签页 ========== */
.tabs-bar {
  background: #fff;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
  padding: 8px 15px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.tab-tag {
  cursor: pointer;
  transition: all 0.25s ease;
  border-radius: 16px;
  padding: 0 14px;
  font-size: 12px;
  border: 1px solid rgba(0, 0, 0, 0.06);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.tab-tag:hover {
  opacity: 0.9;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
}

.tab-tag :deep(.el-tag__close) {
  border-radius: 50%;
  transition: all 0.2s ease;
  margin-left: 4px;
}

.tab-tag :deep(.el-tag__close:hover) {
  background-color: #f56c6c;
  color: #fff;
}

/* ========== 主内容区 ========== */
.main-content {
  background: #f8fafc;
  padding: 20px;
  overflow-y: auto;
}

/* ========== 过渡动画 ========== */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
