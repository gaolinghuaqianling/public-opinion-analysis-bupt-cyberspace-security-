<template>
  <div class="data-collection-page">
    <!-- 面包屑 -->
    <el-breadcrumb separator="/" class="breadcrumb">
      <el-breadcrumb-item :to="{ path: '/dashboard' }">舆情看板</el-breadcrumb-item>
      <el-breadcrumb-item>数据采集</el-breadcrumb-item>
    </el-breadcrumb>

    <!-- 区域1：操作栏 -->
    <el-card shadow="hover" class="action-card">
      <div class="action-header">
        <h2 class="action-title">数据采集</h2>
      </div>
      <div class="action-body">
        <div class="action-left">
          <!-- 平台多选 -->
          <div class="control-group">
            <label class="control-label">采集平台</label>
            <el-checkbox-group v-model="selectedPlatforms" class="platform-group">
              <el-checkbox
                v-for="p in platformOptions"
                :key="p.value"
                :value="p.value"
              >
                {{ p.label }}
              </el-checkbox>
            </el-checkbox-group>
          </div>
          <!-- 关键词输入 -->
          <div class="control-group">
            <label class="control-label">关键词</label>
            <el-input
              v-model="keyword"
              placeholder="输入想采集的关键词（留空则抓热搜）"
              clearable
              class="keyword-input"
              :prefix-icon="Search"
            />
          </div>
        </div>
        <div class="action-right">
          <el-button type="info" plain @click="loadUserConfig">
            使用我的配置
          </el-button>
          <el-button
            type="primary"
            :loading="dispatching"
            @click="handleDispatch"
          >
            <el-icon v-if="!dispatching" class="btn-icon"><Refresh /></el-icon>
            一键采集
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 区域2：统计面板 -->
    <el-row :gutter="20" class="stats-row">
      <el-col :xs="24" :sm="8">
        <div class="stat-card stat-card--blue">
          <div class="stat-icon"><el-icon :size="28"><FolderOpened /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.today_tasks }}</div>
            <div class="stat-label">今日任务数</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="8">
        <div class="stat-card stat-card--green">
          <div class="stat-icon"><el-icon :size="28"><Document /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.today_collected }}</div>
            <div class="stat-label">今日采集量</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="8">
        <div class="stat-card stat-card--orange">
          <div class="stat-icon"><el-icon :size="28"><CircleCheckFilled /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ successRate }}%</div>
            <div class="stat-label">成功率</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 区域3：任务列表 -->
    <el-card shadow="hover" class="task-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">任务列表</span>
          <div class="card-header-right">
            <el-select
              v-model="statusFilter"
              placeholder="状态筛选"
              size="small"
              class="status-filter"
              @change="loadTasks"
            >
              <el-option label="全部" value="all" />
              <el-option label="等待中" value="pending" />
              <el-option label="进行中" value="running" />
              <el-option label="成功" value="success" />
              <el-option label="失败" value="failed" />
            </el-select>
            <el-button :icon="Refresh" size="small" @click="refreshAll" />
          </div>
        </div>
      </template>

      <el-table
        :data="filteredTasks"
        stripe
        highlight-current-row
        style="width: 100%"
        empty-text="暂无任务数据"
      >
        <el-table-column prop="platform_name" label="平台" width="100">
          <template #default="{ row }">
            {{ row.platform_name || platformNameMap[row.platform] || row.platform }}
          </template>
        </el-table-column>
        <el-table-column prop="task_type" label="任务类型" width="100">
          <template #default="{ row }">
            {{ taskTypeLabel(row.task_type) }}
          </template>
        </el-table-column>
        <el-table-column prop="target" label="目标" width="150" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag
              :type="statusTagType(row.status)"
              :class="{ 'status-running': row.status === 'running' }"
              size="small"
            >
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="result_count" label="采集量" width="100" align="center">
          <template #default="{ row }">
            {{ row.result_count ?? 0 }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="180" show-overflow-tooltip />
      </el-table>
    </el-card>

    <!-- 区域4：底部提示 -->
    <div class="bottom-tip">
      采集到的数据将自动进入舆情分析流程，稍后可在「事件看板」中查看。
      <div class="process-tags">
        <el-tag type="info" size="small" effect="plain">自动去重</el-tag>
        <el-tag type="info" size="small" effect="plain">去噪过滤</el-tag>
        <el-tag type="info" size="small" effect="plain">格式标准化</el-tag>
        <el-tag type="info" size="small" effect="plain">情感分析</el-tag>
        <el-tag type="info" size="small" effect="plain">热点发现</el-tag>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { FolderOpened, Document, CircleCheckFilled, Refresh, Search } from '@element-plus/icons-vue'

// ==================== 常量 ====================
const platformOptions = [
  { label: '微博', value: 'weibo' },
  { label: '抖音', value: 'douyin' },
  { label: '知乎', value: 'zhihu' },
  { label: 'B站', value: 'bilibili' },
  { label: '人民网', value: 'people' },
  { label: '小红书', value: 'xiaohongshu' },
]

const platformNameMap = {
  weibo: '微博',
  douyin: '抖音',
  zhihu: '知乎',
  bilibili: 'B站',
  people: '人民网',
  xiaohongshu: '小红书',
}

const taskTypeMap = {
  hotlist: '热搜',
  keyword: '关键词',
  account: '账号',
}

// ==================== 响应式状态 ====================
const selectedPlatforms = ref([...platformOptions.map(p => p.value)])
const keyword = ref('')
const dispatching = ref(false)
const statusFilter = ref('all')

const stats = ref({
  today_tasks: 0,
  today_collected: 0,
  success: 0,
  total: 0,
})

const taskList = ref([])

let pollTimer = null

// ==================== 计算属性 ====================
const successRate = computed(() => {
  if (!stats.value.total || stats.value.total === 0) return 0
  return ((stats.value.success / stats.value.total) * 100).toFixed(1)
})

const filteredTasks = computed(() => {
  if (statusFilter.value === 'all') return taskList.value
  return taskList.value.filter(t => t.status === statusFilter.value)
})

// ==================== 工具函数 ====================
const statusTagType = (status) => {
  const map = { pending: 'info', running: 'warning', success: 'success', failed: 'danger' }
  return map[status] || 'info'
}

const statusLabel = (status) => {
  const map = { pending: '等待中', running: '进行中', success: '成功', failed: '失败' }
  return map[status] || status
}

const taskTypeLabel = (type) => {
  return taskTypeMap[type] || type
}

// ==================== 请求封装 ====================
function getAuthHeaders() {
  const token = localStorage.getItem('token')
  return { Authorization: `Bearer ${token}` }
}

// ==================== 加载统计 ====================
async function loadStats() {
  try {
    const res = await axios.get('/api/crawler/stats', {
      headers: getAuthHeaders(),
    })
    if (res.data && (res.data.code === 200 || res.data.code === undefined)) {
      const data = res.data.data || res.data
      stats.value = {
        today_tasks: data.today_tasks ?? 0,
        today_collected: data.today_collected ?? 0,
        success: data.success ?? 0,
        total: data.total ?? 0,
      }
    }
  } catch {
    // 静默处理
  }
}

// ==================== 加载任务列表 ====================
async function loadTasks() {
  try {
    const res = await axios.get('/api/crawler/tasks', {
      headers: getAuthHeaders(),
    })
    if (res.data && (res.data.code === 200 || res.data.code === undefined)) {
      const payload = res.data.data || res.data
      taskList.value = Array.isArray(payload) ? payload : (payload.tasks || payload.items || [])
    }
  } catch {
    // 静默处理
  }
}

// ==================== 加载用户配置 ====================
async function loadUserConfig() {
  try {
    const res = await axios.get('/api/routes/profile', {
      headers: getAuthHeaders(),
    })
    if (res.data && (res.data.code === 200 || res.data.code === undefined)) {
      const profile = res.data.data || res.data
      if (profile.focus_platforms && Array.isArray(profile.focus_platforms)) {
        selectedPlatforms.value = profile.focus_platforms.filter(p =>
          platformOptions.some(opt => opt.value === p)
        )
      }
      if (profile.focus_keywords) {
        keyword.value = Array.isArray(profile.focus_keywords)
          ? profile.focus_keywords.join('、')
          : profile.focus_keywords
      }
      ElMessage.success('已加载个人配置')
    }
  } catch {
    ElMessage.error('获取个人配置失败')
  }
}

// ==================== 一键采集 ====================
async function handleDispatch() {
  if (selectedPlatforms.value.length === 0) {
    ElMessage.warning('请至少选择一个平台')
    return
  }

  dispatching.value = true

  try {
    // 判断用户是否修改了默认配置：全选且无关键词 => 使用用户配置接口
    const allSelected = selectedPlatforms.value.length === platformOptions.length
    const noKeyword = !keyword.value.trim()

    if (allSelected && noKeyword) {
      // 调用用户配置接口
      await axios.post('/api/crawler/dispatch_user_config', {}, {
        headers: getAuthHeaders(),
      })
      ElMessage.success('采集任务已下发')
    } else {
      // 逐个平台下发任务
      const platforms = selectedPlatforms.value
      const kw = keyword.value.trim()

      for (const platform of platforms) {
        // 下发热搜任务
        await axios.post('/api/crawler/dispatch', {
          platform,
          task_type: 'hotlist',
          target: 'hotlist',
        }, {
          headers: getAuthHeaders(),
        })

        // 如果有关键词，再下发关键词任务
        if (kw) {
          await axios.post('/api/crawler/dispatch', {
            platform,
            task_type: 'keyword',
            target: kw,
          }, {
            headers: getAuthHeaders(),
          })
        }
      }

      ElMessage.success(`已下发 ${platforms.length * (kw ? 2 : 1)} 个采集任务`)
    }

    // 刷新数据
    await refreshAll()
  } catch (err) {
    const msg = err.response?.data?.message || '采集任务下发失败'
    ElMessage.error(msg)
  } finally {
    dispatching.value = false
  }
}

// ==================== 刷新全部 ====================
async function refreshAll() {
  await Promise.all([loadStats(), loadTasks()])
}

// ==================== 轮询 ====================
function startPolling() {
  pollTimer = setInterval(() => {
    // 只在有运行中的任务时轮询
    const hasRunning = taskList.value.some(t => t.status === 'running' || t.status === 'pending')
    if (hasRunning) {
      refreshAll()
    }
  }, 5000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// ==================== 生命周期 ====================
onMounted(() => {
  refreshAll()
  startPolling()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style scoped>
.data-collection-page {
  min-height: 100%;
  padding: 0;
}

.breadcrumb {
  margin-bottom: 16px;
}

/* ========== 区域1：操作栏 ========== */
.action-card {
  margin-bottom: 20px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.action-card :deep(.el-card__body) {
  padding: 20px 24px;
}

.action-header {
  margin-bottom: 16px;
}

.action-title {
  font-size: 20px;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.action-body {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 16px;
}

.action-left {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 20px;
  flex: 1;
}

.action-right {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}

.control-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.control-label {
  font-size: 13px;
  color: #475569;
  font-weight: 500;
}

.platform-group {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.platform-group :deep(.el-checkbox__label) {
  color: #1e293b;
}

.platform-group :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  background-color: #60a5fa;
  border-color: #60a5fa;
}

.platform-group :deep(.el-checkbox__input.is-checked + .el-checkbox__label) {
  color: #60a5fa;
}

.keyword-input {
  width: 300px;
}

.keyword-input :deep(.el-input__wrapper) {
  border-radius: 8px;
  background: #f1f5f9;
  box-shadow: none;
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.keyword-input :deep(.el-input__wrapper:hover) {
  border-color: rgba(96, 165, 250, 0.5);
}

.keyword-input :deep(.el-input__wrapper.is-focus) {
  border-color: #60a5fa;
  box-shadow: 0 0 0 1px rgba(96, 165, 250, 0.25);
}

.keyword-input :deep(.el-input__inner) {
  color: #1e293b;
}

.keyword-input :deep(.el-input__inner::placeholder) {
  color: #64748b;
}

.btn-icon {
  margin-right: 4px;
}

/* ========== 区域2：统计面板 ========== */
.stats-row {
  margin-bottom: 20px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px 24px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}

.stat-card:hover {
  transform: translateY(-2px);
}

.stat-card--blue:hover {
  box-shadow: 0 8px 24px rgba(96, 165, 250, 0.15);
}

.stat-card--green:hover {
  box-shadow: 0 8px 24px rgba(52, 211, 153, 0.15);
}

.stat-card--orange:hover {
  box-shadow: 0 8px 24px rgba(245, 158, 11, 0.15);
}

.stat-icon {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-card--blue .stat-icon {
  background: rgba(96, 165, 250, 0.15);
  color: #60a5fa;
}

.stat-card--green .stat-icon {
  background: rgba(52, 211, 153, 0.15);
  color: #34d399;
}

.stat-card--orange .stat-icon {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.stat-info {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #1e293b;
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: #475569;
  margin-top: 4px;
}

/* ========== 区域3：任务列表 ========== */
.task-card {
  margin-bottom: 20px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.task-card :deep(.el-card__header) {
  padding: 14px 20px;
  border-bottom: 1px solid #e2e8f0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}

.card-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-filter {
  width: 120px;
}

.status-filter :deep(.el-input__wrapper) {
  border-radius: 8px;
  background: #f1f5f9;
  box-shadow: none;
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.status-filter :deep(.el-input__inner) {
  color: #1e293b;
}

/* 表格暗色主题 */
.task-card :deep(.el-table) {
  background: transparent;
  color: #1e293b;
}

.task-card :deep(.el-table th.el-table__cell) {
  background: #f8fafc;
  color: #475569;
  border-bottom: 1px solid #e2e8f0;
}

.task-card :deep(.el-table td.el-table__cell) {
  border-bottom: 1px solid #f1f5f9;
}

.task-card :deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background: #fafbfc;
}

.task-card :deep(.el-table__body tr:hover > td.el-table__cell) {
  background: rgba(96, 165, 250, 0.08) !important;
}

.task-card :deep(.el-table__empty-text) {
  color: #64748b;
}

/* running 状态动画 */
.status-running {
  animation: pulse-tag 1.5s ease-in-out infinite;
}

@keyframes pulse-tag {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* ========== 区域4：底部提示 ========== */
.bottom-tip {
  text-align: center;
  color: #64748b;
  font-size: 13px;
  padding: 16px 0 24px;
  line-height: 1.6;
}

.process-tags {
  display: flex;
  justify-content: center;
  gap: 8px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.process-tags :deep(.el-tag) {
  border-radius: 12px;
  font-size: 12px;
}

/* ========== 响应式 ========== */
@media (max-width: 768px) {
  .action-body {
    flex-direction: column;
    align-items: stretch;
  }

  .action-left {
    flex-direction: column;
  }

  .action-right {
    justify-content: flex-end;
  }

  .keyword-input {
    width: 100%;
  }

  .stat-value {
    font-size: 22px;
  }
}
</style>


