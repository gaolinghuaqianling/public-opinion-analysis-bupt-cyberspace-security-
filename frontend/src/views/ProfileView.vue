<template>
  <div class="user-center-page" v-loading="pageLoading">
    <!-- 面包屑 -->
    <el-breadcrumb separator="/" class="breadcrumb">
      <el-breadcrumb-item :to="{ path: '/dashboard' }">舆情看板</el-breadcrumb-item>
      <el-breadcrumb-item>个人中心</el-breadcrumb-item>
    </el-breadcrumb>

    <el-row :gutter="20">
      <!-- ====== 左侧：用户信息卡 ====== -->
      <el-col :xs="24" :md="7">
        <el-card shadow="hover" class="user-card">
          <div class="avatar-section">
            <el-avatar :size="80" :icon="UserFilled" class="user-avatar" />
            <h3 class="user-name">{{ userInfo.username || '加载中...' }}</h3>
            <el-tag type="info" size="small" effect="plain">舆情分析专员</el-tag>
          </div>

          <el-divider />

          <div class="info-list">
            <div class="info-row">
              <el-icon><User /></el-icon>
              <span>用户ID</span>
              <strong>{{ userInfo.id }}</strong>
            </div>
            <div class="info-row">
              <el-icon><Clock /></el-icon>
              <span>注册时间</span>
              <strong>{{ userInfo.created_at }}</strong>
            </div>
          </div>

          <el-divider />

          <!-- 数据概览 -->
          <div class="stats-grid">
            <div class="stat-block">
              <div class="stat-value blue">{{ stats.total_events || 0 }}</div>
              <div class="stat-label">监控事件</div>
            </div>
            <div class="stat-block">
              <div class="stat-value orange">{{ stats.related_news_count || 0 }}</div>
              <div class="stat-label">关联新闻</div>
            </div>
            <div class="stat-block">
              <div class="stat-value green">{{ platformCount }}</div>
              <div class="stat-label">关注平台</div>
            </div>
            <div class="stat-block">
              <div class="stat-value red">{{ keywordCount }}</div>
              <div class="stat-label">关注关键词</div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- ====== 右侧：配置表单 ====== -->
      <el-col :xs="24" :md="17">
        <!-- 关注平台网址配置 -->
        <el-card shadow="hover" class="form-card">
          <template #header>
            <div class="card-header">
              <span class="card-title"><el-icon><Link /></el-icon> 关注平台网址配置</span>
              <el-button type="primary" link :icon="Plus" @click="addPlatform">添加平台</el-button>
            </div>
          </template>

          <el-alert
            title="配置您需要监控的新闻平台网址，爬虫模块将优先从这些平台抓取数据"
            type="info"
            :closable="false"
            show-icon
            class="form-tip"
          />

          <div v-if="!platformList.some(p => p.name)" class="empty-guide">
            <el-icon :size="40" color="#c0c4cc"><Plus /></el-icon>
            <p class="empty-guide-text">暂未配置关注平台</p>
            <p class="empty-guide-desc">点击上方"添加平台"按钮，添加微博、抖音、知乎等新闻平台网址</p>
          </div>

          <div class="platform-list">
            <transition-group name="list">
              <div
                v-for="(item, idx) in platformList"
                :key="item.id"
                class="platform-row"
              >
                <div class="platform-index">{{ idx + 1 }}</div>

                <div class="platform-fields">
                  <el-form-item class="compact">
                    <el-select
                      v-model="item.name"
                      placeholder="选择平台"
                      filterable
                      allow-create
                      size="default"
                      style="width: 160px"
                    >
                      <el-option label="微博" value="微博" />
                      <el-option label="抖音" value="抖音" />
                      <el-option label="知乎" value="知乎" />
                      <el-option label="微信公众号" value="微信公众号" />
                      <el-option label="人民网" value="人民网" />
                      <el-option label="今日头条" value="今日头条" />
                      <el-option label="B站" value="B站" />
                      <el-option label="澎湃新闻" value="澎湃新闻" />
                      <el-option label="界面新闻" value="界面新闻" />
                      <el-option label="新华网" value="新华网" />
                    </el-select>
                  </el-form-item>

                  <el-form-item class="compact">
                    <el-input
                      v-model="item.url"
                      placeholder="平台网址，如 https://weibo.com"
                      clearable
                      size="default"
                    >
                      <template #prefix>
                        <el-icon><Link /></el-icon>
                      </template>
                    </el-input>
                  </el-form-item>
                </div>

                <div class="platform-actions">
                  <el-switch
                    v-model="item.enabled"
                    size="small"
                    active-text="启用"
                    inactive-text="禁用"
                    inline-prompt
                  />
                  <el-button
                    type="danger"
                    link
                    :icon="Delete"
                    size="small"
                    @click="removePlatform(idx)"
                  />
                </div>
              </div>
            </transition-group>

            <el-empty v-if="!platformList.length" description="暂未配置关注平台，点击上方按钮添加" :image-size="60" />
          </div>
        </el-card>

        <!-- 关注关键词配置 -->
        <el-card shadow="hover" class="form-card">
          <template #header>
            <div class="card-header">
              <span class="card-title"><el-icon><Search /></el-icon> 关注关键词配置</span>
            </div>
          </template>

          <el-alert
            title="配置关注的关键词，系统将优先推送包含这些关键词的新闻和事件"
            type="info"
            :closable="false"
            show-icon
            class="form-tip"
          />

          <div v-if="!keywordList.length" class="empty-guide">
            <el-icon :size="40" color="#c0c4cc"><Edit /></el-icon>
            <p class="empty-guide-text">暂未配置关注关键词</p>
            <p class="empty-guide-desc">在下方输入框添加关键词，或使用批量添加功能（用逗号分隔）</p>
          </div>

          <!-- 已有关键词标签 -->
          <div class="keywords-section">
            <div class="keywords-label">已配置关键词（{{ keywordList.length }}/20）</div>
            <div class="keywords-tags" v-if="keywordList.length">
              <el-tag
                v-for="(kw, idx) in keywordList"
                :key="idx"
                closable
                :type="['', 'success', 'warning', 'danger', 'info'][idx % 5]"
                class="keyword-tag"
                @close="removeKeyword(idx)"
              >
                {{ kw }}
              </el-tag>
            </div>
            <div v-else class="keywords-empty">暂未配置关键词</div>
          </div>

          <!-- 添加关键词输入 -->
          <div class="keyword-add-row">
            <el-input
              ref="keywordInputRef"
              v-model="newKeyword"
              placeholder="输入关键词后按 Enter 添加"
              clearable
              size="default"
              maxlength="20"
              show-word-limit
              @keyup.enter="addKeyword"
            >
              <template #append>
                <el-button :icon="Plus" @click="addKeyword">添加</el-button>
              </template>
            </el-input>
          </div>

          <!-- 批量添加 -->
          <div class="batch-row">
            <el-input
              v-model="batchKeywords"
              type="textarea"
              :rows="2"
              placeholder="批量添加关键词，用逗号或空格分隔（如：人工智能, 芯片, 新能源）"
              resize="none"
              size="small"
            />
            <el-button type="primary" size="small" :icon="Upload" @click="batchAddKeywords">
              批量添加
            </el-button>
          </div>

          <!-- 关键词命中统计 -->
          <div v-if="keywordStatsList.length" class="stats-section">
            <div class="stats-section-title">关键词命中统计</div>
            <div class="stats-bar-list">
              <div v-for="item in keywordStatsList" :key="item.keyword" class="stat-bar-row">
                <span class="stat-bar-label">{{ item.keyword }}</span>
                <el-progress
                  :percentage="item.percentage"
                  :color="statBarColor(item.count)"
                  :stroke-width="14"
                  :show-text="false"
                  class="stat-bar"
                />
                <span class="stat-bar-value">{{ item.count }} 篇</span>
              </div>
            </div>
          </div>
        </el-card>

        <!-- 操作栏 -->
        <div class="action-bar">
          <el-button type="primary" size="large" :icon="Check" :loading="saving" @click="saveAll">
            {{ saving ? '保存中...' : '保存全部配置' }}
          </el-button>
          <el-button size="large" :icon="RefreshLeft" @click="loadProfile">
            重置
          </el-button>
          <el-button size="large" type="danger" plain :icon="Delete" @click="clearAll">
            清空全部
          </el-button>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

const router = useRouter()
import {
  UserFilled, User, Clock, Search, Plus, Delete,
  Upload, Check, RefreshLeft, Edit,
} from '@element-plus/icons-vue'

// ==================== 用户信息 ====================
const pageLoading = ref(true)
const userInfo = ref({})
const stats = ref({})
const saving = ref(false)

// ==================== 平台列表（带网址和启用状态） ====================
let platformIdCounter = 0
const platformList = ref([])

// 预置平台默认网址
const PRESET_URLS = {
  '微博': 'https://weibo.com',
  '抖音': 'https://www.douyin.com',
  '知乎': 'https://www.zhihu.com',
  '微信公众号': 'https://mp.weixin.qq.com',
  '人民网': 'http://www.people.com.cn',
  '今日头条': 'https://www.toutiao.com',
  'B站': 'https://www.bilibili.com',
  '澎湃新闻': 'https://www.thepaper.cn',
  '界面新闻': 'https://www.jiemian.com',
  '新华网': 'http://www.xinhuanet.com',
}

const platformCount = computed(() => platformList.value.filter(p => p.enabled).length)

const addPlatform = () => {
  platformList.value.push({
    id: ++platformIdCounter,
    name: '',
    url: '',
    enabled: true,
  })
}

const removePlatform = (idx) => {
  platformList.value.splice(idx, 1)
}

// ==================== 关键词列表 ====================
const keywordList = ref([])
const newKeyword = ref('')
const batchKeywords = ref('')
const keywordInputRef = ref(null)

const keywordCount = computed(() => keywordList.value.length)

const addKeyword = () => {
  const val = newKeyword.value.trim()
  if (!val) {
    ElMessage.warning('请输入关键词')
    return
  }
  if (val.length < 2) {
    ElMessage.warning('关键词至少2个字符')
    return
  }
  if (keywordList.value.length >= 20) {
    ElMessage.warning('最多配置20个关键词')
    return
  }
  if (keywordList.value.includes(val)) {
    ElMessage.warning(`关键词「${val}」已存在`)
    return
  }
  keywordList.value.push(val)
  newKeyword.value = ''
}

const removeKeyword = (idx) => {
  keywordList.value.splice(idx, 1)
}

const batchAddKeywords = () => {
  const text = batchKeywords.value.trim()
  if (!text) return

  const words = text.split(/[,，、\s\n]+/).map(w => w.trim()).filter(w => w.length >= 2 && !keywordList.value.includes(w))
  const remaining = 20 - keywordList.value.length

  if (remaining <= 0) {
    ElMessage.warning('已达到关键词上限（20个）')
    return
  }

  const toAdd = words.slice(0, remaining)
  if (!toAdd.length) {
    ElMessage.info('没有可添加的新关键词')
    return
  }

  keywordList.value.push(...toAdd)
  batchKeywords.value = ''
  ElMessage.success(`已添加 ${toAdd.length} 个关键词`)
}

// ==================== 关键词命中统计 ====================
const keywordStatsList = computed(() => {
  const hits = stats.value.keyword_hits || {}
  const maxCount = Math.max(...Object.values(hits), 1)
  return Object.entries(hits)
    .map(([keyword, count]) => ({ keyword, count }))
    .sort((a, b) => b.count - a.count)
    .map(item => ({
      ...item,
      percentage: Math.round((item.count / maxCount) * 100),
    }))
})

const statBarColor = (count) => {
  if (count > 15) return '#f56c6c'
  if (count > 8) return '#e6a23c'
  return '#67c23a'
}

// ==================== 加载数据（自动回显） ====================
const loadProfile = async () => {
  pageLoading.value = true
  try {
    const token = localStorage.getItem('token')
    const res = await axios.get('/api/routes/profile', {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (res.data.code === 200) {
      const d = res.data.data
      userInfo.value = {
        id: d.id,
        username: d.username,
        created_at: d.created_at,
      }
      stats.value = d.stats || {}

      // 回显关注平台
      const platforms = d.focus_platforms || []
      platformList.value = platforms.map(name => ({
        id: ++platformIdCounter,
        name: name,
        url: PRESET_URLS[name] || '',
        enabled: true,
      }))

      // 如果没有平台，添加一个默认空行
      if (!platformList.value.length) {
        platformList.value.push({ id: ++platformIdCounter, name: '', url: '', enabled: true })
      }

      // 回显关注关键词
      keywordList.value = [...(d.focus_keywords || [])]
    }
  } catch (err) {
    ElMessage.error('加载个人配置失败')
  } finally {
    pageLoading.value = false
  }
}

// ==================== 保存全部配置 ====================
const saveAll = async () => {
  // 校验平台列表
  const validPlatforms = platformList.value.filter(p => p.enabled && p.name.trim())
  for (const p of validPlatforms) {
    if (p.url && !isValidUrl(p.url)) {
      ElMessage.warning(`平台「${p.name}」的网址格式不正确`)
      return
    }
  }

  // 校验关键词
  if (!keywordList.value.length) {
    ElMessage.warning('请至少配置一个关注关键词')
    return
  }

  saving.value = true
  try {
    const token = localStorage.getItem('token')
    const platformNames = validPlatforms.map(p => p.name)
    const platformUrls = validPlatforms.filter(p => p.url).map(p => ({ name: p.name, url: p.url }))

    const res = await axios.put('/api/routes/profile', {
      focus_platforms: platformNames,
      focus_keywords: keywordList.value,
    }, {
      headers: { Authorization: `Bearer ${token}` },
    })

    if (res.data.code === 200) {
      ElMessage.success('配置保存成功')
      setTimeout(() => {
        ElMessageBox.confirm('配置已保存成功！是否前往舆情看板查看个性化内容？', '提示', {
          confirmButtonText: '前往看板',
          cancelButtonText: '留在此页',
          type: 'success',
        }).then(() => {
          router.push('/dashboard')
        }).catch(() => {})
      }, 1500)

      // 同步更新 localStorage
      const saved = JSON.parse(localStorage.getItem('user') || '{}')
      saved.focus_platforms = platformNames
      saved.focus_keywords = keywordList.value
      saved.platform_urls = platformUrls  // 额外存储网址信息
      localStorage.setItem('user', JSON.stringify(saved))
    }
  } catch (err) {
    ElMessage.error('保存失败，请重试')
  } finally {
    saving.value = false
  }
}

const resetForm = () => {
  loadProfile()
  ElMessage.info('已重置为最近保存的配置')
}

const clearAll = () => {
  ElMessageBox.confirm(
    '确定要清空全部关注平台和关键词配置吗？此操作不可恢复。',
    '确认清空',
    { confirmButtonText: '确定清空', cancelButtonText: '取消', type: 'warning' }
  ).then(() => {
    platformList.value = [{ id: ++platformIdCounter, name: '', url: '', enabled: true }]
    keywordList.value = []
    saveAll()
  }).catch(() => {})
}

// 简易 URL 格式校验
const isValidUrl = (url) => {
  if (!url) return true  // 空网址允许
  return /^https?:\/\/.+\..+/.test(url)
}

// ==================== 初始化 ====================
onMounted(() => {
  loadProfile()
})
</script>

<style scoped>
.breadcrumb { margin-bottom: 16px; }

/* ========== 用户信息卡 ========== */
.user-card {
  text-align: center;
  position: relative;
  overflow: hidden;
}
.user-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 100px;
  background: linear-gradient(135deg, #4facfe, #7c6ff7);
  border-radius: var(--el-card-border-radius) var(--el-card-border-radius) 0 0;
  z-index: 0;
}
.avatar-section { padding: 24px 0 16px; position: relative; z-index: 1; }
.user-avatar {
  background: linear-gradient(135deg, #4facfe, #7c6ff7);
  font-size: 36px;
  box-shadow: 0 8px 24px rgba(79, 172, 254, 0.3);
  border: 3px solid transparent;
  background-clip: content-box;
  position: relative;
}
.user-avatar::after {
  content: '';
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  background: linear-gradient(135deg, #4facfe, #7c6ff7, #e040fb);
  z-index: -1;
}
.user-name { margin: 12px 0 6px; font-size: 20px; font-weight: 700; color: #303133; }

.info-list { padding: 0 4px; }
.info-row {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 0; font-size: 13px; color: #606266;
  border-bottom: 1px solid #f5f7fa;
}
.info-row:last-child { border-bottom: none; }
.info-row span { flex: 1; }
.info-row strong { color: #303133; }

.stats-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; padding: 8px 0; }
.stat-block { text-align: center; padding: 12px 8px; border-radius: 8px; background: #f8f9fb; }
.stat-value { font-size: 22px; font-weight: 800; }
.stat-value.blue { color: #409eff; }
.stat-value.orange { color: #e6a23c; }
.stat-value.green { color: #67c23a; }
.stat-value.red { color: #f56c6c; }
.stat-label { font-size: 11px; color: #909399; margin-top: 2px; }

/* ========== 表单卡片 ========== */
.form-card { margin-bottom: 16px; }
.form-card :deep(.el-card__header) { padding: 12px 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.card-title { font-size: 15px; font-weight: 600; color: #303133; display: flex; align-items: center; gap: 6px; }
.form-tip { margin-bottom: 16px; }

/* ========== 平台列表 ========== */
.platform-list { display: flex; flex-direction: column; gap: 10px; }
.platform-row {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 18px; background: #fafbfc;
  border: 1px solid #f0f2f5; border-radius: 12px;
  transition: all 0.3s ease;
}
.platform-row:hover { border-color: #d9ecff; background: #f5f9ff; box-shadow: 0 2px 8px rgba(64, 158, 255, 0.08); }

.platform-index {
  width: 28px; height: 28px; border-radius: 8px;
  background: linear-gradient(135deg, #e8ecf2, #d4dae5); color: #606266;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 600; flex-shrink: 0;
}

.platform-fields {
  flex: 1; display: flex; gap: 10px; align-items: center;
}
.platform-fields .compact { margin-bottom: 0; }

.platform-actions {
  display: flex; align-items: center; gap: 12px; flex-shrink: 0;
}
.platform-actions :deep(.el-switch) {
  --el-switch-on-color: #4facfe;
  font-size: 12px;
}
.platform-actions :deep(.el-button--danger) {
  color: #c0c4cc;
  transition: all 0.2s;
  border-radius: 6px;
}
.platform-actions :deep(.el-button--danger:hover) {
  color: #f56c6c;
  background: #fef0f0;
}

/* 列表过渡动画 */
.list-enter-active,
.list-leave-active {
  transition: all 0.3s ease;
}
.list-enter-from { opacity: 0; transform: translateX(-20px); }
.list-leave-to { opacity: 0; transform: translateX(20px); }

/* ========== 关键词 ========== */
.keywords-section { margin-bottom: 16px; }
.keywords-label { font-size: 13px; font-weight: 600; color: #606266; margin-bottom: 10px; }
.keywords-tags { display: flex; flex-wrap: wrap; gap: 8px; }
.keyword-tag {
  font-size: 14px;
  padding: 6px 16px;
  border-radius: 999px;
  transition: all 0.3s ease;
  border: 1px solid transparent;
}
.keyword-tag:hover {
  transform: scale(1.08);
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.2);
  filter: brightness(0.95);
}
.keyword-tag :deep(.el-tag__close) {
  opacity: 0;
  transition: opacity 0.2s;
}
.keyword-tag:hover :deep(.el-tag__close) {
  opacity: 1;
}
.keywords-empty { font-size: 13px; color: #c0c4cc; padding: 8px 0; }

.keyword-add-row { margin-bottom: 12px; }
.batch-row { display: flex; gap: 10px; align-items: flex-end; }

/* ========== 统计条 ========== */
.stats-section { margin-top: 16px; }
.stats-section-title { font-size: 13px; font-weight: 600; color: #606266; margin-bottom: 10px; }
.stat-bar-list { display: flex; flex-direction: column; gap: 10px; }
.stat-bar-row { display: flex; align-items: center; gap: 10px; }
.stat-bar-label { width: 80px; font-size: 13px; color: #606266; text-align: right; flex-shrink: 0; }
.stat-bar { flex: 1; }
.stat-bar :deep(.el-progress-bar__outer) {
  border-radius: 999px;
  overflow: hidden;
}
.stat-bar :deep(.el-progress-bar__inner) {
  border-radius: 999px;
  position: relative;
}
.stat-bar :deep(.el-progress-bar__inner::after) {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(255,255,255,0.3), transparent, rgba(255,255,255,0.1));
}
.stat-bar-value { width: 60px; font-size: 12px; color: #909399; text-align: right; flex-shrink: 0; }

/* ========== 操作栏 ========== */
.action-bar {
  display: flex; gap: 12px; justify-content: flex-end;
  padding: 16px 0 8px;
}
.action-bar :deep(.el-button) {
  border-radius: 999px;
  padding: 10px 24px;
  font-weight: 500;
  transition: all 0.3s ease;
}
.action-bar :deep(.el-button--primary) {
  background: linear-gradient(135deg, #4facfe, #7c6ff7);
  border: none;
  box-shadow: 0 4px 12px rgba(79, 172, 254, 0.3);
}
.action-bar :deep(.el-button--primary:hover) {
  box-shadow: 0 6px 16px rgba(79, 172, 254, 0.4);
  transform: translateY(-1px);
}
.action-bar :deep(.el-button--default) {
  border: 1px solid #dcdfe6;
}
.action-bar :deep(.el-button--default:hover) {
  border-color: #4facfe;
  color: #4facfe;
  background: #f5f9ff;
}
.action-bar :deep(.el-button--danger.is-plain) {
  border: 1px solid #fde2e2;
}
.action-bar :deep(.el-button--danger.is-plain:hover) {
  background: #fef0f0;
  box-shadow: 0 4px 12px rgba(245, 108, 108, 0.15);
  transform: translateY(-1px);
}

/* ========== 响应式 ========== */
@media (max-width: 768px) {
  .platform-fields { flex-direction: column; }
  .platform-actions { flex-direction: column; gap: 6px; }
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .action-bar { flex-direction: column; }
  .action-bar .el-button { width: 100%; }
}

/* ========== 空状态引导 ========== */
.empty-guide {
  text-align: center;
  padding: 30px 20px;
  border: 2px dashed #e4e7ed;
  border-radius: 12px;
  margin-bottom: 16px;
  background: #fafbfc;
}
.empty-guide-text {
  font-size: 14px;
  color: #909399;
  margin: 12px 0 4px;
  font-weight: 500;
}
.empty-guide-desc {
  font-size: 12px;
  color: #b0b4bc;
  line-height: 1.6;
}
</style>
