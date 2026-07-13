<template>
  <div class="user-profile-page">
    <!-- ==================== 顶部操作栏 ==================== -->
    <el-row :gutter="20" class="toolbar-row">
      <el-col :span="24">
        <el-card shadow="hover" class="toolbar-card">
          <div class="toolbar">
            <div class="toolbar-left">
              <h2 class="page-title">用户画像洞察</h2>
              <el-select
                v-model="selectedEventId"
                placeholder="选择事件"
                size="default"
                style="width: 280px"
                clearable
              >
                <el-option
                  v-if="eventList.length === 0"
                  disabled
                  label="暂无事件，请先加载测试数据"
                  value=""
                />
                <el-option
                  v-for="evt in eventList"
                  :key="evt.id"
                  :label="evt.title"
                  :value="evt.id"
                />
              </el-select>
              <span v-if="eventList.length === 0" class="no-event-hint">
                提示：点击上方「加载测试数据」按钮或前往「数据采集」页面采集数据
              </span>
            </div>
            <div class="toolbar-right">
              <el-button type="warning" :loading="loadingTestData" @click="loadTestData">
                加载测试数据
              </el-button>
              <el-button type="primary" :loading="analyzing" :disabled="!selectedEventId" @click="startAnalyze">
                开始分析
              </el-button>
              <el-button @click="exportAllCharts">
                一键导出图片
              </el-button>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- ==================== 筛选栏 ==================== -->
    <el-row :gutter="20" class="filter-row">
      <el-col :span="24">
        <el-card shadow="hover" class="filter-card">
          <div class="filter-bar">
            <div class="filter-item">
              <span class="filter-label">账号类型:</span>
              <el-checkbox-group v-model="filterTypes" @change="onFilterChange">
                <el-checkbox label="水军" value="水军" />
                <el-checkbox label="营销号" value="营销号" />
                <el-checkbox label="普通网民" value="普通网民" />
                <el-checkbox label="行业利益方" value="行业利益方" />
              </el-checkbox-group>
            </div>
            <div class="filter-item">
              <span class="filter-label">地域:</span>
              <el-select
                v-model="filterRegion"
                placeholder="全部省份"
                size="default"
                style="width: 160px"
                clearable
                @change="onFilterChange"
              >
                <el-option
                  v-for="prov in regionOptions"
                  :key="prov"
                  :label="prov"
                  :value="prov"
                />
              </el-select>
            </div>
            <div class="filter-item">
              <span class="filter-label">兴趣圈层:</span>
              <el-select
                v-model="filterCluster"
                placeholder="全部圈层"
                size="default"
                style="width: 160px"
                clearable
                @change="onFilterChange"
              >
                <el-option
                  v-for="c in clusterOptions"
                  :key="c"
                  :label="c"
                  :value="c"
                />
              </el-select>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- ==================== 第一行：四类账号统计卡片 ==================== -->
    <el-row :gutter="20" class="stats-row">
      <el-col :xs="24" :sm="12" :md="6">
        <div class="profile-card profile-card--water-army">
          <div class="profile-card__bg-icon"></div>
          <div class="profile-card__content">
            <div class="profile-card__count">{{ statsData.waterArmy.count }}</div>
            <div class="profile-card__label">水军</div>
            <div class="profile-card__meta">
              <span class="profile-card__ratio">占比 {{ statsData.waterArmy.ratio }}%</span>
              <span class="profile-card__conf">置信度 {{ statsData.waterArmy.avgConfidence }}%</span>
            </div>
          </div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <div class="profile-card profile-card--marketing">
          <div class="profile-card__bg-icon"></div>
          <div class="profile-card__content">
            <div class="profile-card__count">{{ statsData.marketing.count }}</div>
            <div class="profile-card__label">营销号</div>
            <div class="profile-card__meta">
              <span class="profile-card__ratio">占比 {{ statsData.marketing.ratio }}%</span>
              <span class="profile-card__conf">置信度 {{ statsData.marketing.avgConfidence }}%</span>
            </div>
          </div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <div class="profile-card profile-card--netizen">
          <div class="profile-card__bg-icon"></div>
          <div class="profile-card__content">
            <div class="profile-card__count">{{ statsData.netizen.count }}</div>
            <div class="profile-card__label">普通网民</div>
            <div class="profile-card__meta">
              <span class="profile-card__ratio">占比 {{ statsData.netizen.ratio }}%</span>
              <span class="profile-card__conf">置信度 {{ statsData.netizen.avgConfidence }}%</span>
            </div>
          </div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <div class="profile-card profile-card--stakeholder">
          <div class="profile-card__bg-icon"></div>
          <div class="profile-card__content">
            <div class="profile-card__count">{{ statsData.stakeholder.count }}</div>
            <div class="profile-card__label">行业利益方</div>
            <div class="profile-card__meta">
              <span class="profile-card__ratio">占比 {{ statsData.stakeholder.ratio }}%</span>
              <span class="profile-card__conf">置信度 {{ statsData.stakeholder.avgConfidence }}%</span>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- ==================== 第二行左：账号类型占比柱状图 ==================== -->
    <!-- ==================== 第二行右：品牌人群分布饼图 ==================== -->
    <el-row :gutter="20" class="chart-row">
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover" class="chart-card">
          <template #header>
            <span class="card-title">账号类型占比</span>
          </template>
          <div ref="typeBarChartRef" class="chart-box"></div>
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover" class="chart-card">
          <template #header>
            <span class="card-title">品牌人群分布</span>
          </template>
          <div ref="brandPieChartRef" class="chart-box"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- ==================== 第三行左：地域分布横向柱状图 ==================== -->
    <!-- ==================== 第三行右：关键词权重 + 圈层分布饼图 ==================== -->
    <el-row :gutter="20" class="chart-row">
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover" class="chart-card">
          <template #header>
            <span class="card-title">地域分布 (TOP 10)</span>
          </template>
          <div ref="regionBarChartRef" class="chart-box"></div>
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover" class="chart-card chart-card--split">
          <template #header>
            <span class="card-title">兴趣圈层分析</span>
          </template>
          <div class="split-chart">
            <div class="split-chart__top">
              <div class="split-chart__subtitle">关键词权重 TOP 15</div>
              <div ref="keywordBarChartRef" class="chart-box chart-box--small"></div>
            </div>
            <div class="split-chart__bottom">
              <div class="split-chart__subtitle">圈层分布</div>
              <div ref="clusterPieChartRef" class="chart-box chart-box--small"></div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- ==================== 第四行：传播图谱联动 ==================== -->
    <el-row :gutter="20" class="chart-row">
      <el-col :span="24">
        <el-card shadow="hover" class="chart-card">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">传播图谱</span>
              <div class="graph-controls">
                <el-checkbox v-model="hideWaterArmy" @change="refreshGraphChart">隐藏水军节点</el-checkbox>
              </div>
            </div>
          </template>
          <div ref="graphChartRef" class="chart-box chart-box--large"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- ==================== 第五行：模糊账号复核面板 ==================== -->
    <el-row :gutter="20" class="chart-row">
      <el-col :span="24">
        <el-card shadow="hover" class="chart-card">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">模糊账号复核 (置信度 &lt; 60%)</span>
              <el-tag type="warning" size="small">{{ fuzzyAccounts.length }} 条</el-tag>
            </div>
          </template>
          <el-table :data="fuzzyAccounts" stripe style="width: 100%">
            <el-table-column prop="username" label="用户名" min-width="120" show-overflow-tooltip />
            <el-table-column prop="classification" label="分类" width="110" align="center">
              <template #default="{ row }">
                <el-tag
                  :type="typeTagMap[row.classification] || 'info'"
                  size="small"
                  effect="dark"
                >
                  {{ row.classification }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="confidence" label="置信度" width="100" align="center">
              <template #default="{ row }">
                <span :class="{ 'conf-low': row.confidence < 40 }">{{ row.confidence }}%</span>
              </template>
            </el-table-column>
            <el-table-column label="各维度评分" min-width="280">
              <template #default="{ row }">
                <div class="dimension-scores">
                  <div v-for="(val, dim) in row.dimension_scores" :key="dim" class="dim-item">
                    <span class="dim-label">{{ dim }}</span>
                    <el-progress
                      :percentage="val"
                      :stroke-width="8"
                      :show-text="false"
                      :color="val >= 70 ? '#67c23a' : val >= 40 ? '#e6a23c' : '#f56c6c'"
                      style="flex: 1"
                    />
                    <span class="dim-val">{{ val }}</span>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="reason" label="判定理由" min-width="200" show-overflow-tooltip />
            <el-table-column label="人工调整" width="140" align="center">
              <template #default="{ row }">
                <el-select v-model="row.classification" size="small" placeholder="调整分类" @change="onAdjustClass(row)">
                  <el-option label="水军" value="水军" />
                  <el-option label="营销号" value="营销号" />
                  <el-option label="普通网民" value="普通网民" />
                  <el-option label="行业利益方" value="行业利益方" />
                </el-select>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <!-- ==================== 节点画像弹窗 ==================== -->
    <el-dialog v-model="nodeDialogVisible" title="用户画像详情" width="480px" align-center>
      <div v-if="selectedNode" class="node-detail">
        <div class="node-detail__header">
          <div class="node-detail__avatar" :style="{ backgroundColor: typeColorMap[selectedNode.category] }">
            {{ (selectedNode.name || '?').charAt(0) }}
          </div>
          <div class="node-detail__info">
            <div class="node-detail__name">{{ selectedNode.name }}</div>
            <el-tag :type="typeTagMap[selectedNode.category] || 'info'" size="small" effect="dark">
              {{ selectedNode.category }}
            </el-tag>
          </div>
        </div>
        <el-descriptions :column="2" border size="small" class="node-detail__desc">
          <el-descriptions-item label="分类">{{ selectedNode.category }}</el-descriptions-item>
          <el-descriptions-item label="置信度">{{ selectedNode.confidence }}%</el-descriptions-item>
          <el-descriptions-item label="粉丝数">{{ selectedNode.followers_count }}</el-descriptions-item>
          <el-descriptions-item label="关注数">{{ selectedNode.following_count }}</el-descriptions-item>
          <el-descriptions-item label="发帖数">{{ selectedNode.posts_count }}</el-descriptions-item>
          <el-descriptions-item label="地域">{{ selectedNode.region || '未知' }}</el-descriptions-item>
          <el-descriptions-item label="圈层" :span="2">{{ selectedNode.cluster || '未知' }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </el-dialog>

    <!-- ==================== 底部说明 ==================== -->
    <div class="footer-note">
      本功能仅用于课程项目演示，所有数据均为模拟测试数据。年龄预测结果仅供参考，不作为实际判断依据。
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, nextTick, watch, computed } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'

// ==================== 常量 ====================
const typeColorMap = {
  '水军': '#ff4d4f',
  '营销号': '#faad14',
  '普通网民': '#1890ff',
  '行业利益方': '#722ed1',
}
const typeTagMap = {
  '水军': 'danger',
  '营销号': 'warning',
  '普通网民': '',
  '行业利益方': 'success',
}
const typeOrder = ['水军', '营销号', '普通网民', '行业利益方']
const brandColors = {
  '老客户': '#52c41a',
  '潜在消费者': '#fa8c16',
  '路人围观': '#8c8c8c',
}

// ==================== 响应式状态 ====================
const selectedEventId = ref(null)
const eventList = ref([])
const loadingTestData = ref(false)
const analyzing = ref(false)

// 筛选
const filterTypes = ref(['水军', '营销号', '普通网民', '行业利益方'])
const filterRegion = ref('')
const filterCluster = ref('')
const regionOptions = ref([])
const clusterOptions = ref([])

// 分析结果
const analysisResult = ref(null)
const profileUsers = ref([])

// 图表 ref
const typeBarChartRef = ref(null)
const brandPieChartRef = ref(null)
const regionBarChartRef = ref(null)
const keywordBarChartRef = ref(null)
const clusterPieChartRef = ref(null)
const graphChartRef = ref(null)

// 图表实例
let typeBarChart = null
let brandPieChart = null
let regionBarChart = null
let keywordBarChart = null
let clusterPieChart = null
let graphChart = null

// 传播图谱控制
const hideWaterArmy = ref(false)

// 节点详情弹窗
const nodeDialogVisible = ref(false)
const selectedNode = ref(null)

// ==================== 统计卡片数据 ====================
const defaultStats = () => ({
  waterArmy: { count: 0, ratio: '0.0', avgConfidence: '0.0' },
  marketing: { count: 0, ratio: '0.0', avgConfidence: '0.0' },
  netizen: { count: 0, ratio: '0.0', avgConfidence: '0.0' },
  stakeholder: { count: 0, ratio: '0.0', avgConfidence: '0.0' },
})
const statsData = reactive(defaultStats())

// ==================== 模糊账号列表 ====================
const fuzzyAccounts = ref([])

// ==================== 工具方法 ====================
function getAuthHeaders() {
  const token = localStorage.getItem('token')
  if (!token || token === 'null') {
    return null
  }
  return { Authorization: `Bearer ${token}` }
}

function calcStats(users) {
  const counts = { '水军': 0, '营销号': 0, '普通网民': 0, '行业利益方': 0 }
  const confSum = { '水军': 0, '营销号': 0, '普通网民': 0, '行业利益方': 0 }
  for (const u of users) {
    const c = u.classification || '普通网民'
    if (counts[c] !== undefined) {
      counts[c]++
      confSum[c] += (u.confidence || 0)
    }
  }
  const total = users.length || 1
  statsData.waterArmy = {
    count: counts['水军'],
    ratio: ((counts['水军'] / total) * 100).toFixed(1),
    avgConfidence: counts['水军'] ? (confSum['水军'] / counts['水军']).toFixed(1) : '0.0',
  }
  statsData.marketing = {
    count: counts['营销号'],
    ratio: ((counts['营销号'] / total) * 100).toFixed(1),
    avgConfidence: counts['营销号'] ? (confSum['营销号'] / counts['营销号']).toFixed(1) : '0.0',
  }
  statsData.netizen = {
    count: counts['普通网民'],
    ratio: ((counts['普通网民'] / total) * 100).toFixed(1),
    avgConfidence: counts['普通网民'] ? (confSum['普通网民'] / counts['普通网民']).toFixed(1) : '0.0',
  }
  statsData.stakeholder = {
    count: counts['行业利益方'],
    ratio: ((counts['行业利益方'] / total) * 100).toFixed(1),
    avgConfidence: counts['行业利益方'] ? (confSum['行业利益方'] / counts['行业利益方']).toFixed(1) : '0.0',
  }
}

function getFilteredUsers() {
  let users = [...profileUsers.value]
  if (filterTypes.value.length < 4) {
    users = users.filter(u => filterTypes.value.includes(u.classification))
  }
  if (filterRegion.value) {
    users = users.filter(u => u.region === filterRegion.value)
  }
  if (filterCluster.value) {
    users = users.filter(u => u.cluster === filterCluster.value)
  }
  return users
}

// ==================== API 调用 ====================
async function loadEventList() {
  const headers = getAuthHeaders()
  if (!headers) {
    ElMessage.warning('请先登录后再使用此功能')
    return
  }
  try {
    const res = await axios.get('/api/routes/dashboard', {
      headers,
      params: { page: 1, page_size: 100 },
    })
    if (res.data && res.data.data) {
      const data = res.data.data
      const items = data.items || data.events || (Array.isArray(data) ? data : [])
      eventList.value = items.map(e => ({
        id: e.id,
        title: e.title || '未知事件',
        heat_score: e.heat_score || 0,
      }))
    }
  } catch (err) {
    if (err.response?.status === 401) {
      ElMessage.error('登录已过期，请重新登录')
    } else {
      console.warn('加载事件列表失败:', err)
    }
  }
}

async function loadTestData() {
  const headers = getAuthHeaders()
  if (!headers) {
    ElMessage.warning('请先登录后再使用此功能')
    return
  }
  loadingTestData.value = true
  try {
    const res = await axios.post('/api/user-profile/load-test-data', {}, { headers })
    if (res.data.code === 200) {
      ElMessage.success('测试数据加载成功')
      await loadEventList()
    } else {
      ElMessage.warning(res.data.message || '加载测试数据返回异常')
    }
  } catch (err) {
    if (err.response?.status === 401) {
      ElMessage.error('登录已过期，请重新登录')
    } else {
      ElMessage.error('加载测试数据失败: ' + (err.response?.data?.detail || err.message))
    }
  } finally {
    loadingTestData.value = false
  }
}

async function startAnalyze() {
  const headers = getAuthHeaders()
  if (!headers) {
    ElMessage.warning('请先登录后再使用此功能')
    return
  }
  if (!selectedEventId.value) {
    ElMessage.warning('请先选择一个事件')
    return
  }
  analyzing.value = true
  try {
    const res = await axios.post('/api/user-profile/analyze', {
      event_id: selectedEventId.value,
    }, { headers })
    if (res.data.code === 200) {
      const raw = res.data.data
      analysisResult.value = raw

      try {
        // ========== 字段映射：后端数据 → 前端 profileUsers ==========
        const classifications = raw.user_classifications || raw.users || raw.profiles || []
        const audienceProfile = raw.audience_profile || {}
        const brandAudience = raw.brand_audience || {}

        profileUsers.value = classifications.map((u) => ({
          ...u,
          username: u.user_name || u.username || '',
          classification: u.category_cn || '普通网民',
          confidence: Math.round((u.confidence || 0) * 100),
          scores: u.scores || {},
          reasons: u.reasons || [],
          region: u.ip_location || '',
          cluster: '',
          brand_tag: '',
          age_group: '',
        }))

        // 补充兴趣圈层
        const ic = audienceProfile.interest_clusters || {}
        const clusterList = Array.isArray(ic.clusters) ? ic.clusters : []
        for (const u of profileUsers.value) {
          for (const cl of clusterList) {
            const members = Array.isArray(cl.users) ? cl.users : []
            if (members.includes(u.user_name)) {
              u.cluster = cl.label || ''
              break
            }
          }
        }

        // 补充年龄段
        const ageDist = audienceProfile.age_distribution || {}
        const preds = Array.isArray(ageDist.predictions) ? ageDist.predictions : []
        for (const u of profileUsers.value) {
          const pred = preds.find(p => p.user_name === u.user_name)
          if (pred) u.age_group = pred.age_group || ''
        }

        // 补充品牌标签
        const brandLayers = Array.isArray(brandAudience.layers) ? brandAudience.layers : []
        for (const u of profileUsers.value) {
          for (const layer of brandLayers) {
            const members = Array.isArray(layer.users) ? layer.users : []
            if (members.includes(u.user_name)) {
              u.brand_tag = layer.label || layer.layer || ''
              break
            }
          }
        }

        populateFilterOptions()
        calcStats(profileUsers.value)
        fuzzyAccounts.value = profileUsers.value.filter(u => (u.confidence || 0) < 60)
        await nextTick()
        initAllCharts()
        ElMessage.success('分析完成')
      } catch (mapErr) {
        console.error('数据映射错误:', mapErr)
        ElMessage.warning('分析完成但部分数据展示异常，请查看控制台')
        // 即使映射出错，仍尝试初始化图表
        populateFilterOptions()
        calcStats(profileUsers.value)
        await nextTick()
        initAllCharts()
      }
    } else {
      const msg = res.data.message || '分析返回异常'
      ElMessage.warning(msg)
    }
  } catch (err) {
    const detail = err.response?.data?.detail || err.message || ''
    if (detail.includes('无传播参与用户') || detail.includes('无用户数据')) {
      ElMessage.error('该事件无传播参与用户数据，请先点击「加载测试数据」后选择测试事件（某品牌手机电池爆炸事件）')
    } else {
      ElMessage.error('分析失败: ' + detail)
    }
  } finally {
    analyzing.value = false
  }
}

function populateFilterOptions() {
  const regions = new Set()
  const clusters = new Set()
  for (const u of profileUsers.value) {
    if (u.region) regions.add(u.region)
    if (u.cluster) clusters.add(u.cluster)
  }
  regionOptions.value = [...regions].sort()
  clusterOptions.value = [...clusters].sort()
}

function onFilterChange() {
  const filtered = getFilteredUsers()
  calcStats(filtered)
  fuzzyAccounts.value = filtered.filter(u => (u.confidence || 0) < 60)
  nextTick(() => {
    initTypeBarChart(filtered)
    initRegionBarChart(filtered)
    initKeywordBarChart(filtered)
    initClusterPieChart(filtered)
    refreshGraphChart()
  })
}

function onAdjustClass(row) {
  ElMessage.success(`已将 ${row.username} 调整为 ${row.classification}`)
}

// ==================== 图表初始化 ====================
function initAllCharts() {
  const filtered = getFilteredUsers()
  try { initTypeBarChart(filtered) } catch (e) { console.warn('类型占比图错误:', e) }
  try { initBrandPieChart() } catch (e) { console.warn('品牌饼图错误:', e) }
  try { initRegionBarChart(filtered) } catch (e) { console.warn('地域分布图错误:', e) }
  try { initKeywordBarChart(filtered) } catch (e) { console.warn('关键词图错误:', e) }
  try { initClusterPieChart(filtered) } catch (e) { console.warn('圈层饼图错误:', e) }
  try { initGraphChart() } catch (e) { console.warn('图谱错误:', e) }
}

// ---------- 账号类型占比柱状图 ----------
function initTypeBarChart(users) {
  if (!typeBarChartRef.value) return
  if (!typeBarChart) {
    typeBarChart = echarts.init(typeBarChartRef.value)
  }
  const counts = {}
  for (const t of typeOrder) counts[t] = 0
  for (const u of users) {
    if (counts[u.classification] !== undefined) counts[u.classification]++
  }
  typeBarChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '6%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: typeOrder,
      axisLabel: { color: '#475569' },
      axisLine: { lineStyle: { color: '#475569' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#475569' },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
    },
    series: [{
      type: 'bar',
      barWidth: '50%',
      data: typeOrder.map(t => ({
        value: counts[t],
        itemStyle: { color: typeColorMap[t] },
      })),
      label: { show: true, position: 'top', color: '#1e293b', fontSize: 13, fontWeight: 'bold' },
    }],
  }, true)
}

// ---------- 品牌人群分布饼图 ----------
function initBrandPieChart() {
  if (!brandPieChartRef.value) return
  if (!brandPieChart) {
    brandPieChart = echarts.init(brandPieChartRef.value)
  }
  // 品牌人群数据：从 brand_audience.layers 或 profileUsers 统计
  let data = []
  const ba = analysisResult.value?.brand_audience
  if (ba && Array.isArray(ba.layers) && ba.layers.length > 0) {
    data = ba.layers.map(l => ({ name: l.label || l.layer, value: l.count || l.users?.length || 0 }))
  } else {
    // fallback: 从 profileUsers 的 brand_tag 统计
    const tagCounts = {}
    for (const u of profileUsers.value) {
      if (u.brand_tag) tagCounts[u.brand_tag] = (tagCounts[u.brand_tag] || 0) + 1
    }
    data = Object.entries(tagCounts).map(([name, value]) => ({ name, value }))
    if (data.length === 0) {
      data = [
        { name: '老客户', value: 0 },
        { name: '潜在消费者', value: 0 },
        { name: '路人围观', value: 0 },
      ]
    }
  }
  const total = data.reduce((s, d) => s + d.value, 0)
  brandPieChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, textStyle: { color: '#475569' } },
    series: [{
      type: 'pie',
      radius: ['30%', '60%'],
      roseType: 'radius',
      label: {
        formatter: '{b}\n{d}%',
        color: '#1e293b',
      },
      data: data.map(d => ({
        ...d,
        itemStyle: { color: brandColors[d.name] || '#8c8c8c' },
      })),
      emphasis: {
        itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.5)' },
      },
    }],
    graphic: [{
      type: 'text',
      left: 'center',
      top: '38%',
      style: {
        text: String(total),
        fill: '#e2e8f0',
        fontSize: 28,
        fontWeight: 'bold',
      },
    }, {
      type: 'text',
      left: 'center',
      top: '50%',
      style: {
        text: '总人数',
        fill: '#94a3b8',
        fontSize: 13,
      },
    }],
  }, true)
}

// ---------- 地域分布横向柱状图 ----------
function initRegionBarChart(users) {
  if (!regionBarChartRef.value) return
  if (!regionBarChart) {
    regionBarChart = echarts.init(regionBarChartRef.value)
  }
  const regionCounts = {}
  for (const u of users) {
    const r = u.region || '未知'
    regionCounts[r] = (regionCounts[r] || 0) + 1
  }
  const sorted = Object.entries(regionCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .reverse()
  const provinces = sorted.map(s => s[0])
  const values = sorted.map(s => s[1])
  regionBarChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '6%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#475569' },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
    },
    yAxis: {
      type: 'category',
      data: provinces,
      axisLabel: { color: '#1e293b', fontSize: 12 },
      axisLine: { lineStyle: { color: '#475569' } },
    },
    series: [{
      type: 'bar',
      barWidth: '55%',
      data: values.map((v, i) => ({
        value: v,
        itemStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 1, y2: 0,
            colorStops: [
              { offset: 0, color: 'rgba(96,165,250,0.6)' },
              { offset: 1, color: 'rgba(96,165,250,1)' },
            ],
          },
        },
      })),
      label: { show: true, position: 'right', color: '#1e293b', fontSize: 12 },
    }],
  }, true)
}

// ---------- 关键词权重横向柱状图 ----------
function initKeywordBarChart(users) {
  if (!keywordBarChartRef.value) return
  if (!keywordBarChart) {
    keywordBarChart = echarts.init(keywordBarChartRef.value)
  }
  // 关键词数据：从 audience_profile.interest_clusters.word_cloud 获取
  let kwCounts = {}
  const ap = analysisResult.value?.audience_profile || {}
  const ic = ap.interest_clusters || {}
  const wordCloud = Array.isArray(ic.word_cloud) ? ic.word_cloud : []
  if (wordCloud.length > 0) {
    for (const w of wordCloud) {
      kwCounts[w.word || w.name] = w.weight || w.value || 1
    }
  } else {
    // fallback: 从 profileUsers 的 reasons/keywords 统计
    for (const u of users) {
      const kws = u.keywords || u.interests || []
      for (const kw of kws) {
        kwCounts[kw] = (kwCounts[kw] || 0) + 1
      }
    }
  }
  const sorted = Object.entries(kwCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15)
    .reverse()
  const words = sorted.map(s => s[0])
  const values = sorted.map(s => s[1])
  keywordBarChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '8%', bottom: '3%', top: '3%', containLabel: true },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#475569', fontSize: 11 },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
    },
    yAxis: {
      type: 'category',
      data: words,
      axisLabel: { color: '#1e293b', fontSize: 11 },
      axisLine: { lineStyle: { color: '#475569' } },
    },
    series: [{
      type: 'bar',
      barWidth: '55%',
      data: values.map((v) => ({
        value: v,
        itemStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 1, y2: 0,
            colorStops: [
              { offset: 0, color: 'rgba(167,139,250,0.5)' },
              { offset: 1, color: 'rgba(167,139,250,1)' },
            ],
          },
        },
      })),
      label: { show: true, position: 'right', color: '#1e293b', fontSize: 11 },
    }],
  }, true)
}

// ---------- 圈层分布饼图 ----------
function initClusterPieChart(users) {
  if (!clusterPieChartRef.value) return
  if (!clusterPieChart) {
    clusterPieChart = echarts.init(clusterPieChartRef.value)
  }
  const clusterCounts = {}
  for (const u of users) {
    const c = u.cluster || '未知圈层'
    clusterCounts[c] = (clusterCounts[c] || 0) + 1
  }
  const clusterColors = ['#60a5fa', '#f472b6', '#34d399', '#fbbf24', '#a78bfa']
  const data = Object.entries(clusterCounts).map(([name, value], idx) => ({
    name,
    value,
    itemStyle: { color: clusterColors[idx % clusterColors.length] },
  }))
  clusterPieChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['35%', '65%'],
      center: ['50%', '50%'],
      label: {
        formatter: '{b}\n{d}%',
        color: '#1e293b',
        fontSize: 11,
      },
      data,
    }],
  }, true)
}

// ---------- 传播图谱 ----------
function initGraphChart() {
  if (!graphChartRef.value) return
  if (!graphChart) {
    graphChart = echarts.init(graphChartRef.value)
  }
  buildGraphOption()
  graphChart.off('click')
  graphChart.on('click', (params) => {
    if (params.dataType === 'node' && params.data) {
      selectedNode.value = params.data
      nodeDialogVisible.value = true
    }
  })
}

function buildGraphOption() {
  const users = getFilteredUsers()
  const filteredNames = new Set(users.map(u => u.username || u.user_name || u.name || ''))

  const gd = analysisResult.value?.graph_data || {}
  const backendNodes = Array.isArray(gd.nodes) ? gd.nodes : []
  const backendLinks = Array.isArray(gd.links) ? gd.links : []
  const backendCats = Array.isArray(gd.categories) ? gd.categories : typeOrder.map(n => ({ name: n }))

  // 用后端节点，但按筛选条件过滤
  const nodes = []
  const nodeNames = new Set()
  for (const n of backendNodes) {
    if (hideWaterArmy.value) {
      const catCn = n.userCategoryCn || ''
      if (catCn === '水军') continue
    }
    // 去重：确保 name 唯一
    let nodeName = n.name || ''
    while (nodeNames.has(nodeName) && nodeName) {
      nodeName = nodeName + '_'
    }
    if (!nodeName) continue
    nodeNames.add(nodeName)

    nodes.push({
      name: nodeName,
      category: n.category ?? 0,
      symbolSize: n.symbolSize || 15,
      value: n.value || 0,
      userCategory: n.userCategory || '',
      userCategoryCn: n.userCategoryCn || '',
      confidence: 0,
      followers_count: 0,
      following_count: 0,
      posts_count: 0,
      region: '',
      cluster: '',
      itemStyle: n.itemStyle || { color: '#1890ff', borderColor: '#fff', borderWidth: 2 },
      label: n.label || { show: true, formatter: '{b}', color: '#1e293b', fontSize: 10 },
    })
  }

  // 如果后端没有节点，从 profileUsers 构建
  if (nodes.length === 0 && users.length > 0) {
    for (let i = 0; i < users.length; i++) {
      const u = users[i]
      const name = u.username || u.user_name || u.name || `user_${i}`
      nodes.push({
        name,
        category: typeOrder.indexOf(u.classification) >= 0 ? typeOrder.indexOf(u.classification) : 0,
        symbolSize: Math.max(8, Math.min(40, (u.followers_count || 10) / 50)),
        value: 0,
        userCategoryCn: u.classification || '普通网民',
        confidence: u.confidence || 0,
        followers_count: u.followers_count || 0,
        following_count: u.following_count || 0,
        posts_count: u.posts_count || 0,
        region: u.region || '',
        cluster: u.cluster || '',
        itemStyle: {
          color: typeColorMap[u.classification] || '#1890ff',
          borderColor: typeColorMap[u.classification] || '#1890ff',
        },
        label: { show: true, formatter: '{b}', color: '#1e293b', fontSize: 10 },
      })
    }
  }

  // 过滤边：两端节点都存在
  const nodeSet = new Set(nodes.map(n => n.name))
  const links = backendLinks
    .filter(l => nodeSet.has(String(l.source)) && nodeSet.has(String(l.target)))
    .slice(0, 200)

  const categories = backendCats.length > 0 ? backendCats : typeOrder.map(name => ({ name }))

  const option = {
    tooltip: {},
    legend: {
      data: categories.map(c => c.name),
      textStyle: { color: '#475569' },
      top: 0,
    },
    animationDuration: 1500,
    animationEasingUpdate: 'quinticInOut',
    series: [{
      type: 'graph',
      layout: 'force',
      data: nodes,
      links: links.map(l => ({
        source: String(l.source),
        target: String(l.target),
        lineStyle: {
          color: 'rgba(0,0,0,0.15)',
          curveness: 0.2,
        },
      })),
      categories,
      roam: true,
      draggable: true,
      force: {
        repulsion: 260,
        edgeLength: [80, 200],
        gravity: 0.05,
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 4 },
      },
    }],
  }

  if (graphChart) {
    try {
      graphChart.setOption(option, true)
    } catch (e) {
      console.warn('图谱渲染错误:', e)
    }
  }
}

function refreshGraphChart() {
  if (!graphChart) return
  buildGraphOption()
}

// ==================== 导出所有图表为图片 ====================
function exportAllCharts() {
  const charts = [
    { instance: typeBarChart, name: '账号类型占比' },
    { instance: brandPieChart, name: '品牌人群分布' },
    { instance: regionBarChart, name: '地域分布' },
    { instance: keywordBarChart, name: '关键词权重' },
    { instance: clusterPieChart, name: '圈层分布' },
    { instance: graphChart, name: '传播图谱' },
  ]
  let exported = 0
  for (const chart of charts) {
    if (chart.instance) {
      try {
        const url = chart.instance.getDataURL({
          type: 'png',
          pixelRatio: 2,
          backgroundColor: '#0f172a',
        })
        const link = document.createElement('a')
        link.download = `用户画像_${chart.name}.png`
        link.href = url
        link.click()
        exported++
      } catch (e) {
        console.error(`导出 ${chart.name} 失败:`, e)
      }
    }
  }
  if (exported > 0) {
    ElMessage.success(`已导出 ${exported} 张图表图片`)
  } else {
    ElMessage.warning('暂无图表可导出，请先完成分析')
  }
}

// ==================== 窗口 resize ====================
function handleResize() {
  typeBarChart?.resize()
  brandPieChart?.resize()
  regionBarChart?.resize()
  keywordBarChart?.resize()
  clusterPieChart?.resize()
  graphChart?.resize()
}

// ==================== 生命周期 ====================
onMounted(async () => {
  await loadEventList()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  typeBarChart?.dispose()
  brandPieChart?.dispose()
  regionBarChart?.dispose()
  keywordBarChart?.dispose()
  clusterPieChart?.dispose()
  graphChart?.dispose()
  typeBarChart = null
  brandPieChart = null
  regionBarChart = null
  keywordBarChart = null
  clusterPieChart = null
  graphChart = null
})
</script>

<style scoped>
/* ==================== 页面根容器 ==================== */
.user-profile-page {
  min-height: 100%;
}

/* ==================== 顶部操作栏 ==================== */
.toolbar-row { margin-bottom: 16px; }
.toolbar-card {
  border-radius: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  backdrop-filter: blur(8px);
}
.toolbar-card :deep(.el-card__body) { padding: 14px 20px; }
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.page-title {
  font-size: 20px;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
  white-space: nowrap;
}

/* ==================== 筛选栏 ==================== */
.filter-row { margin-bottom: 16px; }
.filter-card {
  border-radius: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}
.filter-card :deep(.el-card__body) { padding: 12px 20px; }
.filter-bar {
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
}
.filter-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.filter-label {
  color: #475569;
  font-size: 13px;
  white-space: nowrap;
}
.filter-item :deep(.el-checkbox__label) {
  color: #1e293b;
}
.filter-item :deep(.el-checkbox__input.is-checked + .el-checkbox__label) {
  color: #60a5fa;
}

/* ==================== 统计卡片 ==================== */
.stats-row { margin-bottom: 20px; }
.profile-card {
  position: relative;
  border-radius: 16px;
  padding: 20px 22px;
  overflow: hidden;
  cursor: default;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.profile-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
}
.profile-card__bg-icon {
  position: absolute;
  top: -15px;
  right: -10px;
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: #e2e8f0;
  pointer-events: none;
}
.profile-card__content {
  position: relative;
  z-index: 1;
}
.profile-card__count {
  font-size: 36px;
  font-weight: 800;
  color: #1e293b;
  line-height: 1.2;
}
.profile-card__label {
  font-size: 14px;
  color: #1e293b;
  margin-top: 2px;
  font-weight: 500;
}
.profile-card__meta {
  margin-top: 8px;
  display: flex;
  gap: 12px;
  font-size: 12px;
}
.profile-card__ratio,
.profile-card__conf {
  color: #475569;
  background: #cbd5e1;
  padding: 2px 8px;
  border-radius: 10px;
}

/* 水军 - 红色 */
.profile-card--water-army {
  background: linear-gradient(135deg, #ff4d4f, #cf1322);
  box-shadow: 0 6px 20px rgba(255, 77, 79, 0.35);
}
/* 营销号 - 黄色 */
.profile-card--marketing {
  background: linear-gradient(135deg, #faad14, #d48806);
  box-shadow: 0 6px 20px rgba(250, 173, 20, 0.35);
}
/* 普通网民 - 蓝色 */
.profile-card--netizen {
  background: linear-gradient(135deg, #1890ff, #096dd9);
  box-shadow: 0 6px 20px rgba(24, 144, 255, 0.35);
}
/* 行业利益方 - 紫色 */
.profile-card--stakeholder {
  background: linear-gradient(135deg, #722ed1, #531dab);
  box-shadow: 0 6px 20px rgba(114, 46, 209, 0.35);
}

/* ==================== 图表卡片通用 ==================== */
.chart-row { margin-bottom: 20px; }
.chart-card {
  border-radius: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  transition: box-shadow 0.3s ease, transform 0.3s ease;
  overflow: hidden;
}
.chart-card:hover {
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.2);
  transform: translateY(-2px);
}
.chart-card :deep(.el-card__header) {
  padding: 12px 20px;
  border-bottom: 1px solid #e2e8f0;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}
.card-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.graph-controls :deep(.el-checkbox__label) {
  color: #475569;
}
.graph-controls :deep(.el-checkbox__input.is-checked + .el-checkbox__label) {
  color: #60a5fa;
}

.chart-box {
  height: 320px;
  width: 100%;
}
.chart-box--small {
  height: 200px;
}
.chart-box--large {
  height: 450px;
}

/* 拆分图表（词云 + 圈层饼图） */
.chart-card--split :deep(.el-card__body) {
  padding: 0 16px 16px;
}
.split-chart {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.split-chart__top,
.split-chart__bottom {
  display: flex;
  flex-direction: column;
}
.split-chart__subtitle {
  font-size: 13px;
  color: #475569;
  margin-bottom: 4px;
  padding-left: 4px;
}

/* ==================== 模糊账号复核表格 ==================== */
.fuzzy-table-row {
  margin-bottom: 20px;
}
.conf-low {
  color: #ff4d4f;
  font-weight: 700;
}
.dimension-scores {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dim-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.dim-label {
  font-size: 11px;
  color: #475569;
  min-width: 50px;
  flex-shrink: 0;
}
.dim-val {
  font-size: 11px;
  color: #1e293b;
  min-width: 22px;
  text-align: right;
  flex-shrink: 0;
}

/* ==================== Element Plus 暗色覆盖 ==================== */
:deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.03);
  --el-table-row-hover-bg-color: rgba(96, 165, 250, 0.08);
  --el-table-border-color: #e2e8f0;
  --el-table-text-color: #1e293b;
  --el-table-header-text-color: #475569;
}
:deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background: #f8fafc;
}

:deep(.el-select .el-input__wrapper),
:deep(.el-input__wrapper) {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  box-shadow: none;
}
:deep(.el-select .el-input__wrapper:hover),
:deep(.el-input__wrapper:hover) {
  border-color: rgba(96, 165, 250, 0.4);
}
:deep(.el-select .el-input__wrapper.is-focus),
:deep(.el-input__wrapper.is-focus) {
  border-color: #60a5fa;
  box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.15);
}
:deep(.el-input__inner) {
  color: #1e293b;
}
:deep(.el-input__inner::placeholder) {
  color: #475569;
}

:deep(.el-button) {
  --el-button-text-color: #1e293b;
}

:deep(.el-tag) {
  --el-tag-bg-color: rgba(255, 255, 255, 0.08);
  --el-tag-border-color: #cbd5e1;
  --el-tag-text-color: #1e293b;
}

:deep(.el-checkbox) {
  --el-checkbox-text-color: #475569;
}

:deep(.el-pagination) {
  --el-pagination-bg-color: rgba(255, 255, 255, 0.06);
  --el-pagination-text-color: #475569;
  --el-pagination-button-bg-color: rgba(255, 255, 255, 0.06);
  --el-pagination-hover-color: #60a5fa;
}

:deep(.el-descriptions) {
  --el-descriptions-table-border: #e2e8f0;
}
:deep(.el-descriptions__label) {
  color: #475569;
  background: #f8fafc;
}
:deep(.el-descriptions__content) {
  color: #1e293b;
}

/* ==================== 节点画像弹窗 ==================== */
.node-detail__header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}
.node-detail__avatar {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
  flex-shrink: 0;
}
.node-detail__info {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.node-detail__name {
  font-size: 18px;
  font-weight: 700;
  color: #303133;
}
.node-detail__desc {
  margin-top: 12px;
}

/* ==================== 底部说明 ==================== */
.footer-note {
  text-align: center;
  color: #475569;
  font-size: 12px;
  padding: 20px 0 10px;
  border-top: 1px solid #e2e8f0;
  margin-top: 12px;
}

/* ==================== 空数据提示 ==================== */
.no-event-hint {
  display: block;
  color: #475569;
  font-size: 13px;
  margin-left: 12px;
}

/* ==================== 响应式 ==================== */
@media (max-width: 768px) {
  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  .toolbar-left,
  .toolbar-right {
    flex-direction: column;
  }
  .toolbar-right {
    align-items: stretch;
  }
  .toolbar-right .el-button {
    width: 100%;
  }
  .filter-bar {
    flex-direction: column;
    align-items: flex-start;
  }
  .chart-box {
    height: 260px;
  }
  .chart-box--large {
    height: 350px;
  }
  .chart-box--small {
    height: 180px;
  }
  .split-chart {
    flex-direction: column;
  }
}
</style>



