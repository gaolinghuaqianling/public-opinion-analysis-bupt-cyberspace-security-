<template>
  <div class="event-board-page">
    <!-- 面包屑 -->
    <el-breadcrumb separator="/" class="breadcrumb">
      <el-breadcrumb-item :to="{ path: '/dashboard' }">舆情看板</el-breadcrumb-item>
      <el-breadcrumb-item>事件看板</el-breadcrumb-item>
    </el-breadcrumb>

    <!-- 顶部操作栏 -->
    <el-card shadow="hover" class="toolbar-card">
      <div class="toolbar">
        <div class="toolbar-left pill-group">
          <el-select
            v-model="sortBy"
            placeholder="排序方式"
            size="small"
            class="pill-select"
            @change="onSortSelectChange"
          >
            <el-option label="按热度排序" value="heat" />
            <el-option label="按时间排序" value="time" />
          </el-select>

          <el-button
            :icon="sortOrder === 'desc' ? 'SortDown' : 'SortUp'"
            size="small"
            round
            class="pill-btn"
            @click="toggleSortOrder"
          >
            {{ sortOrder === 'desc' ? '降序' : '升序' }}
          </el-button>

          <el-select
            v-model="filterRisk"
            placeholder="风险等级"
            clearable
            size="small"
            class="pill-select"
            @change="onFilterChange"
          >
            <el-option label="低风险" value="low" />
            <el-option label="中风险" value="medium" />
            <el-option label="高风险" value="high" />
            <el-option label="严重" value="critical" />
          </el-select>

          <el-select
            v-model="filterLifecycle"
            placeholder="生命周期"
            clearable
            size="small"
            class="pill-select"
            @change="onFilterChange"
          >
            <el-option label="潜伏期" value="latent" />
            <el-option label="成长期" value="growth" />
            <el-option label="高潮期" value="peak" />
            <el-option label="衰退期" value="decline" />
          </el-select>

          <el-input
            v-model="searchKeyword"
            placeholder="搜索事件标题..."
            clearable
            prefix-icon="Search"
            size="small"
            class="pill-input"
            @keyup.enter="onFilterChange"
            @clear="onFilterChange"
          />
        </div>

        <div class="toolbar-right">
          <el-button type="primary" :icon="Refresh" size="small" round @click="loadEvents">刷新</el-button>
        </div>
      </div>
    </el-card>

    <!-- 热度折线图 -->
    <el-card shadow="hover" class="chart-card">
      <template #header>
        <div class="card-header">
          <span class="card-title"><el-icon><TrendCharts /></el-icon> 热度趋势折线图</span>
          <el-radio-group v-model="chartRange" size="small" @change="loadEvents">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="top10">TOP 10</el-radio-button>
            <el-radio-button value="top20">TOP 20</el-radio-button>
          </el-radio-group>
        </div>
      </template>
      <div class="chart-bg-decor"></div>
      <div ref="heatChartRef" class="heat-chart"></div>
    </el-card>

    <!-- 事件列表表格 -->
    <el-card shadow="hover" class="table-card">
      <template #header>
        <div class="card-header">
          <span class="card-title"><el-icon><List /></el-icon> 热点事件列表</span>
          <el-tag type="info" size="small">共 {{ total }} 条</el-tag>
        </div>
      </template>

      <el-table
        :data="eventList"
        stripe
        highlight-current-row
        style="width: 100%"
        @row-click="goDetail"
        @sort-change="onSortChange"
        empty-text="暂无事件数据"
        :default-sort="{ prop: 'heat_score', order: 'descending' }"
      >
        <!-- 序号 -->
        <el-table-column label="#" width="50" type="index" align="center" />

        <!-- 事件标题 -->
        <el-table-column prop="title" label="事件标题" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="event-title-cell">
              <el-tag
                :type="riskTagType(row.risk_level)"
                size="small"
                effect="dark"
                class="risk-tag"
              >
                {{ riskLabel(row.risk_level) }}
              </el-tag>
              <span class="event-title-text">{{ row.title }}</span>
            </div>
          </template>
        </el-table-column>

        <!-- 热度指数 -->
        <el-table-column prop="heat_score" label="热度指数" width="160" sortable>
          <template #default="{ row }">
            <div class="heat-cell">
              <el-progress
                :percentage="Number(row.heat_score)"
                :color="heatProgressColor(row.heat_score)"
                :stroke-width="10"
                :show-text="false"
                style="flex: 1"
              />
              <span class="heat-value" :class="{ 'heat-high': row.heat_score >= 70, 'heat-medium': row.heat_score >= 40 }">
                {{ row.heat_score }}
              </span>
            </div>
          </template>
        </el-table-column>

        <!-- 情感占比 -->
        <el-table-column label="情感占比" width="220">
          <template #default="{ row }">
            <div v-if="row.sentiment" class="sentiment-cell">
              <div class="sentiment-bars">
                <div
                  class="sentiment-bar positive"
                  :style="{ width: (row.sentiment.positive_ratio * 100) + '%' }"
                  :title="'正面 ' + (row.sentiment.positive_ratio * 100).toFixed(1) + '%'"
                >
                  <span v-if="row.sentiment.positive_ratio > 0.15">{{ (row.sentiment.positive_ratio * 100).toFixed(0) }}%</span>
                </div>
                <div
                  class="sentiment-bar neutral"
                  :style="{ width: (row.sentiment.neutral_ratio * 100) + '%' }"
                  :title="'中性 ' + (row.sentiment.neutral_ratio * 100).toFixed(1) + '%'"
                >
                  <span v-if="row.sentiment.neutral_ratio > 0.15">{{ (row.sentiment.neutral_ratio * 100).toFixed(0) }}%</span>
                </div>
                <div
                  class="sentiment-bar negative"
                  :style="{ width: (row.sentiment.negative_ratio * 100) + '%' }"
                  :title="'负面 ' + (row.sentiment.negative_ratio * 100).toFixed(1) + '%'"
                >
                  <span v-if="row.sentiment.negative_ratio > 0.15">{{ (row.sentiment.negative_ratio * 100).toFixed(0) }}%</span>
                </div>
              </div>
              <div class="sentiment-legend">
                <span class="legend-dot pos"></span>{{ (row.sentiment.positive_ratio * 100).toFixed(1) }}
                <span class="legend-dot neu"></span>{{ (row.sentiment.neutral_ratio * 100).toFixed(1) }}
                <span class="legend-dot neg"></span>{{ (row.sentiment.negative_ratio * 100).toFixed(1) }}
              </div>
            </div>
            <el-tag v-else type="info" size="small">暂无</el-tag>
          </template>
        </el-table-column>

        <!-- 生命周期 -->
        <el-table-column prop="lifecycle" label="生命周期" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="lifecycleTagType(row.lifecycle)" size="small" effect="plain">
              {{ lifecycleLabel(row.lifecycle) }}
            </el-tag>
          </template>
        </el-table-column>

        <!-- TOP关键词 -->
        <el-table-column label="关键词" width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <div v-if="row.sentiment && row.sentiment.top_keywords" class="keywords-cell">
              <el-tag
                v-for="(kw, idx) in row.sentiment.top_keywords.slice(0, 4)"
                :key="idx"
                :type="['info', 'success', 'warning', 'danger'][idx % 4]"
                size="small"
                class="kw-tag"
              >
                {{ kw }}
              </el-tag>
            </div>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>

        <!-- 创建时间 -->
        <el-table-column prop="created_at" label="创建时间" width="160" sortable />

        <!-- 操作 -->
        <el-table-column label="操作" width="80" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" round @click.stop="goDetail(row)">
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @size-change="loadEvents"
          @current-change="loadEvents"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import axios from 'axios'
import { TrendCharts, Refresh } from '@element-plus/icons-vue'

const router = useRouter()

// ==================== 筛选与排序 ====================
const sortBy = ref('heat')
const sortOrder = ref('desc')
const filterRisk = ref('')
const filterLifecycle = ref('')
const searchKeyword = ref('')
const chartRange = ref('all')

// ==================== 分页 ====================
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const eventList = ref([])

// ==================== 工具函数 ====================
const riskTagType = (r) => ({ low: 'success', medium: 'warning', high: 'danger', critical: 'danger' }[r] || 'info')
const riskLabel = (r) => ({ low: '低风险', medium: '中风险', high: '高风险', critical: '严重' }[r] || r)
const lifecycleTagType = (l) => ({ latent: 'info', growth: 'success', peak: 'danger', decline: 'warning' }[l] || 'info')
const lifecycleLabel = (l) => ({ latent: '潜伏期', growth: '成长期', peak: '高潮期', decline: '衰退期' }[l] || l)

const heatProgressColor = (score) => {
  if (score >= 70) return '#f56c6c'
  if (score >= 40) return '#e6a23c'
  return '#67c23a'
}

// ==================== ECharts 热度折线图 ====================
const heatLineOption = computed(() => {
  // 从事件列表生成图表数据（按热度从高到低排列）
  let events = [...eventList.value]
  if (sortBy.value === 'heat') {
    events.sort((a, b) => sortOrder.value === 'desc' ? b.heat_score - a.heat_score : a.heat_score - b.heat_score)
  }

  // 按图表范围截取
  const rangeMap = { all: events.length, top10: 10, top20: 20 }
  events = events.slice(0, rangeMap[chartRange.value] || events.length)

  // 取标题前12字作为X轴标签
  const xData = events.map((e, i) => `#${i + 1} ${e.title.substring(0, 10)}`)
  const heatData = events.map(e => e.heat_score)
  // 从情感数据中提取负面占比作为第二条线
  const negData = events.map(e => e.sentiment ? +(e.sentiment.negative_ratio * 100).toFixed(1) : 0)

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter(params) {
        let tip = `<div style="font-weight:600;margin-bottom:4px">${params[0].axisValueLabel}</div>`
        params.forEach(p => {
          const color = p.seriesIndex === 0 ? '#409eff' : '#f56c6c'
          const unit = p.seriesIndex === 0 ? '' : '%'
          tip += `<div style="color:${color}">${p.marker} ${p.seriesName}: ${p.value}${unit}</div>`
        })
        return tip
      },
    },
    legend: {
      data: ['热度指数', '负面情感占比(%)'],
      top: 0,
      right: 20,
    },
    grid: {
      left: '3%', right: '4%', bottom: '3%', top: 40,
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: xData,
      axisLabel: { rotate: 35, fontSize: 11, color: '#909399' },
      axisLine: { lineStyle: { color: '#e4e7ed' } },
    },
    yAxis: [
      {
        type: 'value',
        name: '热度',
        min: 0,
        max: 100,
        axisLabel: { color: '#909399' },
        splitLine: { lineStyle: { type: 'dashed', color: '#f0f2f5' } },
      },
      {
        type: 'value',
        name: '负面占比%',
        min: 0,
        max: 100,
        axisLabel: { color: '#909399', formatter: '{value}%' },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '热度指数',
        type: 'line',
        data: heatData,
        yAxisIndex: 0,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2.5, color: '#409eff' },
        itemStyle: { color: '#409eff' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(64,158,255,0.25)' },
              { offset: 1, color: 'rgba(64,158,255,0.02)' },
            ],
          },
        },
      },
      {
        name: '负面情感占比(%)',
        type: 'line',
        data: negData,
        yAxisIndex: 1,
        smooth: true,
        symbol: 'diamond',
        symbolSize: 5,
        lineStyle: { width: 2, color: '#f56c6c', type: 'dashed' },
        itemStyle: { color: '#f56c6c' },
      },
    ],
  }
})

// ==================== ECharts 图表实例 ====================
const heatChartRef = ref(null)
let heatChartInstance = null

function initOrUpdateHeatChart() {
  if (!heatChartRef.value) return
  const option = heatLineOption.value
  if (!option) return
  if (!heatChartInstance) {
    heatChartInstance = echarts.init(heatChartRef.value)
  }
  heatChartInstance.setOption(option, true)
}

watch(heatLineOption, () => {
  nextTick(() => initOrUpdateHeatChart())
})

onBeforeUnmount(() => {
  if (heatChartInstance) {
    try { heatChartInstance.dispose() } catch {}
    heatChartInstance = null
  }
})

// ==================== 加载事件列表 ====================
const loadEvents = async () => {
  try {
    const token = localStorage.getItem('token')
    const res = await axios.get('/api/routes/dashboard', {
      headers: { Authorization: `Bearer ${token}` },
      params: {
        page: page.value,
        page_size: pageSize.value,
        sort_by: sortBy.value,
        order: sortOrder.value,
        risk_level: filterRisk.value || undefined,
        lifecycle: filterLifecycle.value || undefined,
        keyword: searchKeyword.value || undefined,
      },
    })
    if (res.data.code === 200) {
      eventList.value = res.data.data.items || []
      total.value = res.data.data.total || 0
    }
  } catch (err) {
    ElMessage.error('加载事件列表失败')
  }
}

// ==================== 表格列头排序（触发后端排序） ====================
const onSortChange = ({ prop, order }) => {
  if (!prop || !order) {
    // 取消排序时恢复默认
    sortBy.value = 'heat'
    sortOrder.value = 'desc'
  } else {
    sortBy.value = prop === 'created_at' ? 'time' : 'heat'
    sortOrder.value = order === 'ascending' ? 'asc' : 'desc'
  }
  page.value = 1
  loadEvents()
}

// 工具栏排序下拉框变更
const onSortSelectChange = () => {
  page.value = 1
  loadEvents()
}

// 工具栏升降序切换按钮
const toggleSortOrder = () => {
  sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
  page.value = 1
  loadEvents()
}

// ==================== 筛选变更 ====================
const onFilterChange = () => {
  page.value = 1
  loadEvents()
}

// ==================== 行为辅助 ====================
const goDetail = (row) => {
  router.push(`/event/${row.id}`)
}

// ==================== 初始化 ====================
onMounted(() => {
  loadEvents()
})
</script>

<style scoped>
.breadcrumb { margin-bottom: 16px; }

/* ========== 工具栏 - pill 形状 ========== */
.toolbar-card {
  margin-bottom: 16px;
  border-radius: 16px;
  overflow: hidden;
}
.toolbar-card :deep(.el-card__body) { padding: 10px 16px; }
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.toolbar-left { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.pill-group {
  background: #f4f6fa;
  border-radius: 24px;
  padding: 4px 6px;
}
.pill-select {
  width: 120px !important;
}
.pill-btn {
  border-radius: 16px;
  font-size: 12px;
  padding: 0 12px;
}
.pill-select :deep(.el-input__wrapper),
.pill-select :deep(.el-input),
.pill-input :deep(.el-input__wrapper),
.pill-input :deep(.el-input) {
  border-radius: 20px !important;
  box-shadow: none !important;
  background: #fff !important;
  border: 1px solid #e4e7ed;
  font-size: 12px;
}
.pill-select :deep(.el-input__wrapper):hover,
.pill-input :deep(.el-input__wrapper):hover {
  border-color: #a0cfff;
}
.pill-select :deep(.el-input__wrapper.is-focus),
.pill-input :deep(.el-input__wrapper.is-focus) {
  border-color: #409eff !important;
}
.pill-input {
  width: 180px !important;
}

/* ========== 图表卡片 ========== */
.chart-card {
  margin-bottom: 16px;
  border-radius: 16px;
  overflow: hidden;
  transition: box-shadow 0.35s ease, transform 0.35s ease;
}
.chart-card:hover {
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}
.chart-card :deep(.el-card__header) { padding: 12px 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.card-title { font-size: 15px; font-weight: 600; color: #303133; display: flex; align-items: center; gap: 6px; }

/* 图表渐变背景装饰 */
.chart-bg-decor {
  position: absolute;
  top: 60px;
  right: 0;
  width: 260px;
  height: 200px;
  background: linear-gradient(135deg, rgba(64, 158, 255, 0.06), rgba(139, 92, 246, 0.06));
  border-radius: 50%;
  filter: blur(40px);
  pointer-events: none;
  z-index: 0;
}
.chart-card :deep(.el-card__body) {
  position: relative;
  overflow: hidden;
}

.heat-chart { height: 280px; }

/* ========== 表格 ========== */
.table-card {
  margin-bottom: 16px;
  border-radius: 16px;
  overflow: hidden;
}
.table-card :deep(.el-card__header) { padding: 12px 20px; }

.event-title-cell { display: flex; align-items: center; gap: 8px; }
.risk-tag { flex-shrink: 0; border-radius: 12px; }
.event-title-text { color: #303133; cursor: pointer; transition: color 0.2s; }
.event-title-text:hover { color: #409eff; }

/* 热度 - 渐变进度条 */
.heat-cell { display: flex; align-items: center; gap: 8px; }
.heat-cell :deep(.el-progress-bar__outer) {
  border-radius: 10px;
  overflow: hidden;
  background: #f0f2f5;
}
.heat-cell :deep(.el-progress-bar__inner) {
  border-radius: 10px;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6) !important;
  transition: width 0.6s ease;
}
.heat-value {
  font-size: 14px; font-weight: 700; color: #606266;
  min-width: 32px; text-align: right;
}
.heat-value.heat-high { color: #f56c6c; }
.heat-value.heat-medium { color: #e6a23c; }

/* 情感占比 - 圆角药丸形状 */
.sentiment-cell { padding: 4px 0; }
.sentiment-bars {
  display: flex;
  height: 20px;
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 4px;
  width: 100%;
  gap: 2px;
}
.sentiment-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  color: #fff;
  font-weight: 600;
  min-width: 0;
  transition: width 0.5s ease;
  border-radius: 10px;
}
.sentiment-bar.positive {
  background: linear-gradient(135deg, #10b981, #34d399);
}
.sentiment-bar.neutral {
  background: linear-gradient(135deg, #8b95a5, #b0b8c4);
}
.sentiment-bar.negative {
  background: linear-gradient(135deg, #f56c6c, #ff8a80);
}

.sentiment-legend {
  display: flex; gap: 10px; font-size: 11px; color: #606266;
}
.legend-dot {
  display: inline-block; width: 8px; height: 8px;
  border-radius: 50%; margin-right: 2px; vertical-align: middle;
}
.legend-dot.pos { background: linear-gradient(135deg, #10b981, #34d399); }
.legend-dot.neu { background: linear-gradient(135deg, #8b95a5, #b0b8c4); }
.legend-dot.neg { background: linear-gradient(135deg, #f56c6c, #ff8a80); }

/* 关键词 */
.keywords-cell { display: flex; gap: 4px; flex-wrap: wrap; }
.kw-tag {
  font-size: 11px;
  border-radius: 12px;
}

.text-muted { color: #c0c4cc; }

/* 分页 */
.pagination-wrapper {
  display: flex; justify-content: flex-end;
  margin-top: 16px; padding-top: 12px;
  border-top: 1px solid #f0f2f5;
}

/* 表格行悬停 */
:deep(.el-table__row) {
  cursor: pointer;
  transition: background-color 0.3s ease;
}
:deep(.el-table__row:hover > td) {
  background-color: #f5f0ff !important;
}
:deep(.el-table--striped .el-table__row--striped:hover > td) {
  background-color: #ede5ff !important;
}

/* ========== 响应式 ========== */
@media (max-width: 768px) {
  .pill-group {
    flex-direction: column;
    border-radius: 16px;
    padding: 8px;
  }
  .toolbar-left {
    flex-direction: column;
    align-items: stretch;
  }
  .pill-select,
  .pill-input {
    width: 100% !important;
  }
  .sentiment-bars { height: 14px; }
}
</style>
