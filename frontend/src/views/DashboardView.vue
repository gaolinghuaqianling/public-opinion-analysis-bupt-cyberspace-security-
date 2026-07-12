<template>
  <div class="dashboard-page">
    <!-- 统计卡片 -->
    <el-row :gutter="20" class="stats-row">
      <el-col :xs="24" :sm="12" :md="6">
        <div class="stat-card stat-card--blue">
          <div class="stat-card__bg-icon"><el-icon :size="80"><DataLine /></el-icon></div>
          <div class="stat-icon"><el-icon :size="28"><DataLine /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.totalEvents }}</div>
            <div class="stat-label">热点事件</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <div class="stat-card stat-card--purple">
          <div class="stat-card__bg-icon"><el-icon :size="80"><Document /></el-icon></div>
          <div class="stat-icon"><el-icon :size="28"><Document /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.totalNews }}</div>
            <div class="stat-label">新闻总量</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <div class="stat-card stat-card--green">
          <div class="stat-card__bg-icon"><el-icon :size="80"><Warning /></el-icon></div>
          <div class="stat-icon"><el-icon :size="28"><Warning /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.highRisk }}</div>
            <div class="stat-label">高风险事件</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <div class="stat-card stat-card--orange">
          <div class="stat-card__bg-icon"><el-icon :size="80"><TrendCharts /></el-icon></div>
          <div class="stat-icon"><el-icon :size="28"><TrendCharts /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.analyzed }}</div>
            <div class="stat-label">已分析</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- ECharts 图表区 -->
    <el-row :gutter="20" class="chart-row">
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover" class="chart-card">
          <template #header>
            <span class="card-title">舆情情感分布</span>
          </template>
          <v-chart class="chart" :option="sentimentOption" autoresize />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover" class="chart-card">
          <template #header>
            <span class="card-title">事件风险等级分布</span>
          </template>
          <v-chart class="chart" :option="riskOption" autoresize />
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="chart-row">
      <el-col :xs="24" :lg="16">
        <el-card shadow="hover" class="chart-card">
          <template #header>
            <span class="card-title">舆情生命周期趋势</span>
          </template>
          <v-chart class="chart" :option="lifecycleOption" autoresize />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="8">
        <el-card shadow="hover" class="chart-card">
          <template #header>
            <span class="card-title">平台报道占比</span>
          </template>
          <v-chart class="chart" :option="platformOption" autoresize />
        </el-card>
      </el-col>
    </el-row>

    <!-- 事件列表 -->
    <el-card shadow="hover" class="table-card">
      <template #header>
        <div class="table-header">
          <span class="card-title">热点事件列表</span>
          <div class="table-filters">
            <el-select v-model="filterRisk" placeholder="风险等级" clearable size="small" style="width:120px">
              <el-option label="低风险" value="low" />
              <el-option label="中风险" value="medium" />
              <el-option label="高风险" value="high" />
              <el-option label="严重" value="critical" />
            </el-select>
            <el-select v-model="filterLifecycle" placeholder="生命周期" clearable size="small" style="width:120px">
              <el-option label="萌芽期" value="latent" />
              <el-option label="成长期" value="growth" />
              <el-option label="峰值期" value="peak" />
              <el-option label="衰退期" value="decline" />
            </el-select>
            <el-input v-model="searchKeyword" placeholder="搜索事件" clearable size="small" style="width:180px" prefix-icon="Search" />
            <el-button type="primary" size="small" round @click="loadEvents">查询</el-button>
          </div>
        </div>
      </template>

      <el-table :data="eventList" stripe highlight-current-row @row-click="goDetail">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="title" label="事件标题" min-width="200" show-overflow-tooltip>
          <template #default="scope">
            <el-tag v-if="scope.row.is_focus_hit" type="warning" size="small" effect="plain" style="margin-right:6px">推荐</el-tag>
            <span>{{ scope.row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="heat_score" label="热度" width="100">
          <template #default="{ row }">
            <span class="heat-badge" :class="{ 'heat-badge--high': row.heat_score >= 70, 'heat-badge--medium': row.heat_score >= 40 }">{{ row.heat_score }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="risk_level" label="风险" width="90">
          <template #default="{ row }">
            <el-tag :type="riskTagType(row.risk_level)" size="small">{{ riskLabel(row.risk_level) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="lifecycle" label="生命周期" width="100">
          <template #default="{ row }">
            <el-tag :type="lifecycleTagType(row.lifecycle)" size="small">{{ lifecycleLabel(row.lifecycle) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="160" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click.stop="goDetail(row)">详情</el-button>
            <el-button link type="success" size="small" @click.stop="goQA(row)">问答</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next, jumper"
        class="pagination"
        @change="loadEvents"
      />
    </el-card>

    <!-- 引导弹窗 -->
    <el-dialog
      v-model="guideVisible"
      title="欢迎使用智舆平台 🎯"
      width="520px"
      align-center
      :show-close="false"
      :close-on-click-modal="false"
    >
      <div style="line-height:1.8; color:#606266; font-size:14px;">
        <p style="font-size:16px; font-weight:600; color:#303133; margin-bottom:12px;">📋 使用指引</p>
        <p>请先完成以下配置，系统将为您推送个性化的舆情内容：</p>
        <div style="margin-top:16px;">
          <p><strong>步骤一：设置关注平台</strong><br/>在【个人中心】页面添加您要监控的新闻平台网址<br/>例如：微博、抖音、知乎、微信公众号等</p>
          <p style="margin-top:12px;"><strong>步骤二：设置关注关键词</strong><br/>在【个人中心】页面添加您感兴趣的关键词<br/>例如：人工智能、芯片、新能源（支持批量添加，用逗号分隔）</p>
          <p style="margin-top:12px;"><strong>步骤三：查看个性化看板</strong><br/>配置完成后，系统会优先展示与您关注内容相关的舆情事件<br/>匹配事件将在看板中标注 🌟 推荐标记</p>
        </div>
      </div>
      <template #footer>
        <el-button @click="guideVisible = false; guideDismissed = true">我知道了</el-button>
        <el-button type="primary" style="background:linear-gradient(135deg,#3b82f6,#6366f1);border:none;" @click="router.push('/profile'); guideVisible = false">前往个人中心配置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, BarChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import axios from 'axios'
import { Document, Warning, TrendCharts } from '@element-plus/icons-vue'

use([CanvasRenderer, PieChart, BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent])

const router = useRouter()
const route = useRoute()

// 统计
const stats = reactive({ totalEvents: 0, totalNews: 0, highRisk: 0, analyzed: 0 })

// 筛选
const filterRisk = ref('')
const filterLifecycle = ref('')
const searchKeyword = ref(route.query.keyword || '')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const eventList = ref([])
const guideVisible = ref(false)
const guideDismissed = ref(false)

const heatColor = [{ offset: 0, color: '#67c23a' }, { offset: 0.5, color: '#e6a23c' }, { offset: 1, color: '#f56c6c' }]

const riskTagType = (r) => ({ low: 'success', medium: 'warning', high: 'danger', critical: 'danger' }[r] || 'info')
const riskLabel = (r) => ({ low: '低风险', medium: '中风险', high: '高风险', critical: '严重' }[r] || r)
const lifecycleTagType = (l) => ({ latent: 'info', growth: 'primary', peak: 'danger', decline: 'warning' }[l] || 'info')
const lifecycleLabel = (l) => ({ latent: '萌芽期', growth: '成长期', peak: '峰值期', decline: '衰退期' }[l] || l || '未知')

// ECharts 配置
const sentimentOption = ref({
  tooltip: { trigger: 'item' },
  legend: { bottom: 0 },
  series: [{
    type: 'pie',
    radius: ['40%', '70%'],
    avoidLabelOverlap: false,
    label: { show: true, formatter: '{b}\n{d}%' },
    data: [],
  }],
})

const riskOption = ref({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
  xAxis: { type: 'category', data: ['低风险', '中风险', '高风险', '严重'] },
  yAxis: { type: 'value' },
  series: [{
    data: [0, 0, 0, 0],
    type: 'bar',
    barWidth: '50%',
    label: { show: true, position: 'top' },
  }],
})

const lifecycleOption = ref({
  tooltip: { trigger: 'axis' },
  grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
  xAxis: { type: 'category', data: [] },
  yAxis: { type: 'value' },
  series: [
    { name: '萌芽期', type: 'line', smooth: true, data: [], itemStyle: { color: '#909399' } },
    { name: '成长期', type: 'line', smooth: true, data: [], itemStyle: { color: '#409eff' } },
    { name: '峰值期', type: 'line', smooth: true, data: [], itemStyle: { color: '#f56c6c' } },
    { name: '衰退期', type: 'line', smooth: true, data: [], itemStyle: { color: '#e6a23c' } },
  ],
})

const platformOption = ref({
  tooltip: { trigger: 'item' },
  legend: { orient: 'vertical', left: 'left' },
  series: [{
    type: 'pie',
    radius: '60%',
    data: [],
    label: { formatter: '{b}\n{d}%' },
  }],
})

// 平台颜色映射
const platformColors = {
  '微博': '#e6162d', '抖音': '#000000', '知乎': '#0066ff',
  '微信': '#07c160', '小红书': '#fe2c55', 'B站': '#00a1d6',
  '人民网': '#ff0000',
}

// 风险等级颜色映射
const riskColors = { low: '#67c23a', medium: '#e6a23c', high: '#f56c6c', critical: '#303133' }

// 加载事件列表并更新图表
const loadEvents = async () => {
  try {
    const token = localStorage.getItem('token')
    const res = await axios.get('/api/routes/dashboard', {
      headers: { Authorization: `Bearer ${token}` },
      params: {
        page: page.value,
        page_size: pageSize.value,
        sort_by: 'heat',
        order: 'desc',
        risk_level: filterRisk.value || undefined,
        lifecycle: filterLifecycle.value || undefined,
        keyword: searchKeyword.value || undefined,
      },
    })
    if (res.data.code === 200) {
      const events = res.data.data.items || []
      eventList.value = events
      total.value = res.data.data.total
      if (!res.data.data.has_focus_config && !guideDismissed.value) {
        guideVisible.value = true
      }

      // ---- 更新情感分布饼图（基于真实 sentiment 数据） ----
      let totalPositive = 0, totalNegative = 0, totalNeutral = 0
      let sentimentCount = 0
      for (const evt of events) {
        if (evt.sentiment && evt.sentiment.positive_ratio != null) {
          totalPositive += evt.sentiment.positive_ratio
          totalNegative += evt.sentiment.negative_ratio
          totalNeutral += evt.sentiment.neutral_ratio
          sentimentCount++
        }
      }
      if (sentimentCount > 0) {
        sentimentOption.value.series[0].data = [
          { value: Math.round(totalPositive * 100), name: '正面', itemStyle: { color: '#67c23a' } },
          { value: Math.round(totalNeutral * 100), name: '中性', itemStyle: { color: '#909399' } },
          { value: Math.round(totalNegative * 100), name: '负面', itemStyle: { color: '#f56c6c' } },
        ]
      }

      // ---- 更新风险等级分布柱状图（基于真实数据） ----
      const riskCounts = { low: 0, medium: 0, high: 0, critical: 0 }
      for (const evt of events) {
        const rl = evt.risk_level || 'low'
        if (riskCounts[rl] !== undefined) riskCounts[rl]++
      }
      riskOption.value.series[0].data = [
        { value: riskCounts.low, itemStyle: { color: riskColors.low } },
        { value: riskCounts.medium, itemStyle: { color: riskColors.medium } },
        { value: riskCounts.high, itemStyle: { color: riskColors.high } },
        { value: riskCounts.critical, itemStyle: { color: riskColors.critical } },
      ]

      // ---- 更新生命周期趋势图（基于真实数据按 created_at 统计） ----
      const lifecycleByDate = {}
      const lifecycleOrder = ['latent', 'growth', 'peak', 'decline']
      for (const evt of events) {
        const dateStr = (evt.created_at || '').slice(5, 10) // 取 MM-DD
        if (!dateStr) continue
        if (!lifecycleByDate[dateStr]) lifecycleByDate[dateStr] = { latent: 0, growth: 0, peak: 0, decline: 0 }
        const lc = evt.lifecycle || 'growth'
        if (lifecycleByDate[dateStr][lc] !== undefined) lifecycleByDate[dateStr][lc]++
      }
      const sortedDates = Object.keys(lifecycleByDate).sort()
      lifecycleOption.value.xAxis.data = sortedDates
      lifecycleOption.value.series[0].data = sortedDates.map(d => lifecycleByDate[d].latent)
      lifecycleOption.value.series[1].data = sortedDates.map(d => lifecycleByDate[d].growth)
      lifecycleOption.value.series[2].data = sortedDates.map(d => lifecycleByDate[d].peak)
      lifecycleOption.value.series[3].data = sortedDates.map(d => lifecycleByDate[d].decline)

      // ---- 更新平台分布饼图（基于 sentiment 中的 platform_coverage 或事件分布） ----
      const platformCounts = {}
      let hasPlatformCoverage = false
      for (const evt of events) {
        if (evt.sentiment && evt.sentiment.top_keywords) {
          // top_keywords 来自 event_analysis，但平台分布需要单独接口
        }
        // 从事件数据中尝试获取平台信息
        const source = evt.source_platform || ''
        if (source) {
          platformCounts[source] = (platformCounts[source] || 0) + 1
        }
      }
      if (Object.keys(platformCounts).length > 0) {
        platformOption.value.series[0].data = Object.entries(platformCounts).map(([name, value]) => ({
          value,
          name,
          itemStyle: { color: platformColors[name] || '#409eff' },
        }))
      }
    }
  } catch (err) {
    console.error('加载数据失败:', err)
    ElMessage.error('加载数据失败')
  }
}

// 加载统计
const loadStats = async () => {
  try {
    const token = localStorage.getItem('token')
    const res = await axios.get('/api/routes/dashboard', {
      headers: { Authorization: `Bearer ${token}` },
      params: { page: 1, page_size: 1 },
    })
    if (res.data.code === 200) {
      const data = res.data.data
      stats.totalEvents = data.total
      // 已分析数量：有 sentiment 的事件数 / 总事件数
      stats.analyzed = data.items ? data.items.filter(e => e.sentiment).length : 0
      // 从后端返回的聚合字段中读取新闻总量和高风险事件数
      stats.totalNews = data.total_news || 0
      stats.highRisk = data.high_risk_count || 0
    }
  } catch {}
}

const goDetail = (row) => {
  router.push(`/event/${row.id}`)
}

const goQA = (row) => {
  router.push(`/qa?eventId=${row.id}`)
}

onMounted(() => {
  loadEvents()
  loadStats()
})
</script>

<style scoped>
/* ========== 统计卡片 ========== */
.stats-row { margin-bottom: 24px; }

.stat-card {
  position: relative;
  border-radius: 16px;
  padding: 22px 24px;
  display: flex;
  align-items: center;
  overflow: hidden;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
  cursor: default;
}
.stat-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
}

/* 半透明图标背景装饰 */
.stat-card__bg-icon {
  position: absolute;
  top: -12px;
  left: -8px;
  opacity: 0.12;
  color: #fff;
  pointer-events: none;
}

/* 渐变色 */
.stat-card--blue {
  background: linear-gradient(135deg, #3b82f6, #6366f1);
  color: #fff;
  box-shadow: 0 6px 20px rgba(59, 130, 246, 0.35);
}
.stat-card--purple {
  background: linear-gradient(135deg, #8b5cf6, #a855f7);
  color: #fff;
  box-shadow: 0 6px 20px rgba(139, 92, 246, 0.35);
}
.stat-card--green {
  background: linear-gradient(135deg, #10b981, #34d399);
  color: #fff;
  box-shadow: 0 6px 20px rgba(16, 185, 129, 0.35);
}
.stat-card--orange {
  background: linear-gradient(135deg, #f97316, #fb923c);
  color: #fff;
  box-shadow: 0 6px 20px rgba(249, 115, 22, 0.35);
}

.stat-icon {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  margin-right: 16px;
  background: rgba(255, 255, 255, 0.2);
  backdrop-filter: blur(4px);
  flex-shrink: 0;
}

.stat-value {
  font-size: 32px;
  font-weight: 800;
  color: #fff;
  line-height: 1.1;
}
.stat-label {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.8);
  margin-top: 4px;
}

/* ========== 图表卡片 ========== */
.chart-row { margin-bottom: 24px; }
.chart-card {
  border-radius: 16px;
  transition: box-shadow 0.35s ease, transform 0.35s ease;
  overflow: hidden;
}
.chart-card:hover {
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.12);
  transform: translateY(-2px);
}
.chart-card :deep(.el-card__header) { padding: 14px 22px; border-bottom: 1px solid #ebeef5; }
.card-title { font-size: 15px; font-weight: 600; color: #303133; }
.chart { height: 300px; }

/* ========== 表格卡片 ========== */
.table-card {
  margin-bottom: 20px;
  border-radius: 16px;
  overflow: hidden;
}
.table-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
.table-filters { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

/* 表格行 hover 柔和 */
:deep(.el-table__row) {
  cursor: pointer;
  transition: background-color 0.3s ease;
}
:deep(.el-table__row:hover > td) {
  background-color: #f0f7ff !important;
}
:deep(.el-table--striped .el-table__row--striped:hover > td) {
  background-color: #e8f4fd !important;
}

/* 热度渐变徽章 */
.heat-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  padding: 3px 10px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #67c23a, #95d475);
}
.heat-badge--medium {
  background: linear-gradient(135deg, #e6a23c, #f0c78a);
}
.heat-badge--high {
  background: linear-gradient(135deg, #f56c6c, #ff8a80);
}

.pagination { margin-top: 16px; justify-content: flex-end; }
</style>
