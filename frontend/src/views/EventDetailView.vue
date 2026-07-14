<template>
  <div class="event-detail-page" v-loading="pageLoading">
    <!-- 面包屑导航 -->
    <el-breadcrumb separator="/" class="breadcrumb">
      <el-breadcrumb-item :to="{ path: '/event-board' }">事件看板</el-breadcrumb-item>
      <el-breadcrumb-item>事件详情</el-breadcrumb-item>
    </el-breadcrumb>

    <!-- ====== 1. 事件概述区域 ====== -->
    <el-card shadow="hover" class="summary-card">
      <div class="summary-header">
        <div class="summary-left">
          <h2 class="event-title">{{ eventData.title || '加载中...' }}</h2>
          <div class="event-tags">
            <span class="pill-tag" :class="'risk-' + (eventData.risk_level || 'info')">
              {{ riskLabel(eventData.risk_level) }}
            </span>
            <span class="pill-tag" :class="'lifecycle-' + (eventData.lifecycle || 'info')">
              {{ lifecycleLabel(eventData.lifecycle) }}
            </span>
            <span class="pill-tag heat-pill">
              热度 <strong>{{ eventData.heat_score }}</strong>
            </span>
            <span class="pill-tag" :class="'credibility-' + credibilityLevel" v-if="credibilityScore !== null">
              <el-icon><Warning /></el-icon>
              可信度 {{ credibilityScore != null ? (credibilityScore * 100).toFixed(0) + '%' : '未知' }}
            </span>
          </div>
        </div>
        <div class="summary-actions">
          <el-button type="primary" :icon="ChatDotRound" @click="goQA">智能问答</el-button>
        </div>
      </div>

      <el-divider />

      <!-- 概述文本区域（支持编辑） -->
      <div class="summary-text-area">
        <!-- 非编辑模式 -->
        <template v-if="!isEditingSummary">
          <div class="event-summary-text">
            <el-icon :size="16" color="#409eff"><InfoFilled /></el-icon>
            <span v-if="cleanSummary" v-html="cleanSummary"></span>
            <span v-else class="no-summary-hint">暂无概述，点击编辑按钮添加</span>
          </div>
          <div class="summary-edit-row">
            <el-button type="primary" link size="small" @click="startEditSummary">
              <el-icon><Edit /></el-icon> 编辑
            </el-button>
          </div>
        </template>
        <!-- 编辑模式 -->
        <template v-else>
          <el-input
            v-model="editingSummaryText"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 8 }"
            placeholder="请输入事件概述..."
            class="summary-edit-input"
          />
          <div class="summary-edit-actions">
            <el-button type="primary" size="small" :loading="savingSummary" @click="saveSummary">
              <el-icon><Check /></el-icon> 保存
            </el-button>
            <el-button size="small" @click="cancelEditSummary">取消</el-button>
          </div>
        </template>
      </div>

      <div class="event-meta">
        <span><el-icon><Clock /></el-icon> 创建: {{ eventData.created_at }}</span>
        <span><el-icon><Refresh /></el-icon> 更新: {{ eventData.updated_at }}</span>
      </div>
    </el-card>

    <!-- ====== 交互数据指标卡片 ====== -->
    <el-card v-if="interactionData" shadow="hover" class="interaction-card">
      <template #header>
        <span class="card-title"><el-icon><DataAnalysis /></el-icon> 交互数据指标</span>
      </template>
      <div class="interaction-metrics-grid">
        <!-- 热度值 -->
        <div class="interaction-metric-item heat-metric">
          <div class="metric-label">热度值</div>
          <div class="metric-value heat-value">{{ formatHeat(interactionData.heat) }}</div>
          <div class="metric-sub" v-if="interactionData.heat != null">原始值: {{ interactionData.heat.toLocaleString() }}</div>
        </div>
        <!-- 情感标签 -->
        <div class="interaction-metric-item">
          <div class="metric-label">情感标签</div>
          <el-tag
            :type="sentimentTagType(interactionData.label)"
            :effect="'dark'"
            size="large"
            class="metric-tag"
          >
            {{ sentimentTagLabel(interactionData.label) }}
          </el-tag>
        </div>
        <!-- 来源渠道 -->
        <div class="interaction-metric-item" v-if="interactionData.source != null">
          <div class="metric-label">来源渠道</div>
          <el-tag
            type="info"
            effect="plain"
            size="large"
            class="metric-tag"
          >
            {{ sourceTagLabel(interactionData.source) }}
          </el-tag>
        </div>
        <!-- 视频数量 -->
        <div class="interaction-metric-item" v-if="interactionData.video_count != null">
          <div class="metric-label">视频数量</div>
          <div class="metric-value">{{ interactionData.video_count.toLocaleString() }}</div>
        </div>
      </div>
    </el-card>

    <!-- ====== 2. 报道量折线图（全宽） ====== -->
    <el-card shadow="hover" class="chart-card">
      <template #header>
        <span class="card-title"><el-icon><TrendCharts /></el-icon> 事件报道量趋势</span>
      </template>
      <div v-if="timelineOption" ref="timelineChartRef" class="wide-chart"></div>
      <el-empty v-else description="暂无报道量数据" />
    </el-card>

    <!-- ====== 3. 情感饼图 + 4. 平台环形图 + 5. 词云 ====== -->
    <el-row :gutter="20" class="charts-row">
      <!-- 情感饼图 -->
      <el-col :xs="24" :md="8">
        <el-card shadow="hover" class="chart-card mini-card">
          <template #header>
            <span class="card-title"><el-icon><PieChart /></el-icon> 情感分布</span>
          </template>
          <div v-if="sentimentOption" ref="sentimentChartRef" class="square-chart"></div>
          <el-empty v-else description="暂无分析" :image-size="80" />
        </el-card>
      </el-col>

      <!-- 平台环形图 -->
      <el-col :xs="24" :md="8">
        <el-card shadow="hover" class="chart-card mini-card">
          <template #header>
            <span class="card-title"><el-icon><Histogram /></el-icon> 平台报道占比</span>
          </template>
          <div v-if="platformOption" ref="platformChartRef" class="square-chart"></div>
          <el-empty v-else description="暂无平台数据" :image-size="80" />
        </el-card>
      </el-col>

      <!-- 词云 -->
      <el-col :xs="24" :md="8">
        <el-card shadow="hover" class="chart-card mini-card">
          <template #header>
            <span class="card-title"><el-icon><Tickets /></el-icon> 高频关键词</span>
          </template>
          <div v-if="analysisData?.high_freq_keywords?.length" class="wordcloud-tags">
            <el-tag v-for="(word, idx) in analysisData.high_freq_keywords" :key="idx"
              :effect="idx < 3 ? 'dark' : 'plain'"
              :type="['primary','success','warning','danger','info'][idx % 5]"
              :size="idx < 3 ? 'large' : idx < 6 ? 'default' : 'small'"
              class="word-tag">
              {{ word }}
            </el-tag>
          </div>
          <el-empty v-else description="暂无关键词" :image-size="80" />
        </el-card>
      </el-col>
    </el-row>

    <!-- ====== 情感占比进度条详情 ====== -->
    <el-card v-if="analysisData" shadow="hover" class="chart-card">
      <template #header>
        <span class="card-title"><el-icon><DataAnalysis /></el-icon> 情感分析详情</span>
      </template>
      <div class="sentiment-detail-grid">
        <div class="sentiment-card positive-card">
          <div class="sentiment-icon">😊</div>
          <div class="sentiment-info">
            <div class="sentiment-percentage">{{ (analysisData.positive_ratio * 100).toFixed(1) }}%</div>
            <div class="sentiment-label">正面情感</div>
          </div>
          <el-progress
            :percentage="Math.round(analysisData.positive_ratio * 100)"
            :color="'rgba(255,255,255,0.8)'"
            :stroke-width="8"
            :show-text="false"
            class="sentiment-progress"
          />
        </div>
        <div class="sentiment-card neutral-card">
          <div class="sentiment-icon">😐</div>
          <div class="sentiment-info">
            <div class="sentiment-percentage">{{ (analysisData.neutral_ratio * 100).toFixed(1) }}%</div>
            <div class="sentiment-label">中性情感</div>
          </div>
          <el-progress
            :percentage="Math.round(analysisData.neutral_ratio * 100)"
            :color="'rgba(255,255,255,0.8)'"
            :stroke-width="8"
            :show-text="false"
            class="sentiment-progress"
          />
        </div>
        <div class="sentiment-card negative-card">
          <div class="sentiment-icon">😟</div>
          <div class="sentiment-info">
            <div class="sentiment-percentage">{{ (analysisData.negative_ratio * 100).toFixed(1) }}%</div>
            <div class="sentiment-label">负面情感</div>
          </div>
          <el-progress
            :percentage="Math.round(analysisData.negative_ratio * 100)"
            :color="'rgba(255,255,255,0.8)'"
            :stroke-width="8"
            :show-text="false"
            class="sentiment-progress"
          />
        </div>
      </div>
    </el-card>

    <!-- ====== 文本可信度评分 ====== -->
    <el-card v-if="analysisData && analysisData.credibility_score != null" shadow="hover" class="chart-card">
      <template #header>
        <span class="card-title"><el-icon><Lock /></el-icon> 文本可信度评分</span>
      </template>

      <div class="credibility-section">
        <!-- 左侧：分数圆环 -->
        <div class="credibility-score-wrap">
          <div class="credibility-ring" :class="credibilityLevel">
            <div class="ring-bg"></div>
            <div class="ring-fill" :style="{ '--pct': analysisData.credibility_score * 100 + '%' }"></div>
            <div class="ring-text">
              <div class="ring-value">{{ (analysisData.credibility_score * 100).toFixed(0) }}</div>
              <div class="ring-unit">分</div>
            </div>
          </div>
          <div class="credibility-label" :class="credibilityLevel">
            {{ credibilityLabel }}
          </div>
        </div>

        <!-- 右侧：特征详情 -->
        <div class="credibility-details">
          <div class="detail-desc">
            {{ credibilityDesc }}
          </div>

          <!-- 虚假特征标记 -->
          <div v-if="analysisData.fake_flags && analysisData.fake_flags.length" class="fake-flags">
            <div class="flags-title">检测到的风险标记</div>
            <div class="flags-list">
              <el-tag
                v-for="(flag, idx) in analysisData.fake_flags"
                :key="idx"
                type="warning"
                effect="plain"
                class="fake-flag-tag"
              >
                <el-icon><WarningFilled /></el-icon>
                {{ flag }}
              </el-tag>
            </div>
          </div>
          <div v-else class="no-flags">
            <el-icon :size="16" color="#67c23a"><CircleCheckFilled /></el-icon>
            <span>未检测到虚假文本风险标记</span>
          </div>
        </div>
      </div>
    </el-card>

    <!-- ====== 传播链路关系图 ====== -->
    <el-card v-if="spreadData && spreadData.graph_data && spreadData.graph_data.nodes?.length" shadow="hover" class="chart-card">
      <template #header>
        <div class="card-header-row">
          <span class="card-title"><el-icon><Share /></el-icon> 传播链路分析</span>
          <div class="spread-legend">
            <span class="legend-item"><i class="legend-dot" style="background:#c7000b"></i>官方媒体</span>
            <span class="legend-item"><i class="legend-dot" style="background:#409eff"></i>社交平台</span>
            <span class="legend-item"><i class="legend-dot" style="background:#67c23a"></i>新闻门户</span>
            <el-divider direction="vertical" />
            <el-tag type="info" size="small" effect="plain">深度 {{ spreadData.spread_depth }}层</el-tag>
            <el-tag type="info" size="small" effect="plain">转发 ~{{ formatNum(spreadData.total_reposts) }}</el-tag>
            <el-tag type="info" size="small" effect="plain">阅读 ~{{ formatNum(spreadData.total_reads) }}</el-tag>
          </div>
        </div>
      </template>
      <div class="spread-chart-wrapper">
        <!-- ECharts 力导向图容器 -->
        <div ref="spreadChartRef" class="spread-chart-container" style="width: 100%; height: 400px;"></div>
      </div>
    </el-card>

    <!-- ====== 情绪量化分析 ====== -->
    <el-row :gutter="20" class="charts-row" v-if="emotionData">
      <!-- 情绪占比饼图 -->
      <el-col :xs="24" :md="10">
        <el-card shadow="hover" class="chart-card mini-card">
          <template #header>
            <span class="card-title"><el-icon><DataAnalysis /></el-icon> 舆情情绪量化</span>
          </template>
          <div class="emotion-overview">
            <div class="emotion-bar-group">
              <div class="emotion-bar-item">
                <span class="emotion-label positive-label">正面</span>
                <el-progress :percentage="Math.round((emotionData.emotion_ratios?.positive || 0) * 100)" :color="'#67c23a'" :stroke-width="12" :show-text="true" />
              </div>
              <div class="emotion-bar-item">
                <span class="emotion-label neutral-label">中性</span>
                <el-progress :percentage="Math.round((emotionData.emotion_ratios?.neutral || 0) * 100)" :color="'#e6a23c'" :stroke-width="12" :show-text="true" />
              </div>
              <div class="emotion-bar-item">
                <span class="emotion-label negative-label">负面</span>
                <el-progress :percentage="Math.round((emotionData.emotion_ratios?.negative || 0) * 100)" :color="'#f56c6c'" :stroke-width="12" :show-text="true" />
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 情绪激化节点 + 波动诱因 -->
      <el-col :xs="24" :md="14">
        <el-card shadow="hover" class="chart-card mini-card">
          <template #header>
            <span class="card-title"><el-icon><Lightning /></el-icon> 情绪波动分析</span>
          </template>
          <div class="emotion-detail">
            <div v-if="emotionData.agitated_nodes?.length" class="agitated-section">
              <div class="detail-sub-title">情绪激化节点</div>
              <div v-for="(node, idx) in emotionData.agitated_nodes.slice(0, 3)" :key="idx" class="agitated-node">
                <el-tag type="danger" size="small" effect="plain" class="agitated-tag">
                  <el-icon><WarningFilled /></el-icon> {{ node.platform || '未知' }}
                </el-tag>
                <span class="agitated-text">{{ node.node }}</span>
                <div class="agitated-cause">{{ node.cause }}</div>
              </div>
            </div>
            <div v-if="emotionData.fluctuation_causes?.length" class="fluctuation-section">
              <div class="detail-sub-title">情绪波动诱因</div>
              <div v-for="(cause, idx) in emotionData.fluctuation_causes.slice(0, 3)" :key="idx" class="fluctuation-item">
                <el-icon :size="14" color="#e6a23c"><TrendCharts /></el-icon>
                <span>{{ cause }}</span>
              </div>
            </div>
            <div v-if="!emotionData.agitated_nodes?.length && !emotionData.fluctuation_causes?.length" class="no-data-hint">
              <el-icon :size="16" color="#67c23a"><CircleCheckFilled /></el-icon>
              <span>舆论情绪整体稳定，未检测到明显激化节点</span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- ====== 热度走势预判 ====== -->
    <el-card v-if="heatPrediction" shadow="hover" class="chart-card">
      <template #header>
        <div class="card-header-row">
          <span class="card-title"><el-icon><TrendCharts /></el-icon> 短期热度走势预判</span>
          <div class="spread-legend">
            <el-tag :type="heatPrediction.trend_prediction === '上涨' ? 'danger' : heatPrediction.trend_prediction === '回落' ? 'success' : 'warning'" size="small" effect="plain">
              预测趋势：{{ heatPrediction.trend_prediction }}
            </el-tag>
            <el-tag type="info" size="small" effect="plain">置信度 {{ (heatPrediction.confidence * 100).toFixed(0) }}%</el-tag>
          </div>
        </div>
      </template>
      <div class="heat-prediction-section">
        <div class="heat-summary-text">{{ heatPrediction.summary }}</div>
        <el-row :gutter="20" class="heat-detail-row">
          <el-col :span="12">
            <div class="heat-time-block">
              <div class="heat-time-title">
                <el-icon :size="16" color="#409eff"><Clock /></el-icon> 未来24小时
              </div>
              <div class="heat-direction" :class="'dir-' + (heatPrediction.prediction_details?.['24h']?.direction || 'stable')">
                {{ {up:'上涨',down:'回落',stable:'平稳'}[heatPrediction.prediction_details?.['24h']?.direction || 'stable'] }}
              </div>
              <div class="heat-desc">{{ heatPrediction.prediction_details?.['24h']?.description }}</div>
            </div>
          </el-col>
          <el-col :span="12">
            <div class="heat-time-block">
              <div class="heat-time-title">
                <el-icon :size="16" color="#7c3aed"><Clock /></el-icon> 未来72小时
              </div>
              <div class="heat-direction" :class="'dir-' + (heatPrediction.prediction_details?.['72h']?.direction || 'stable')">
                {{ {up:'上涨',down:'回落',stable:'平稳'}[heatPrediction.prediction_details?.['72h']?.direction || 'stable'] }}
              </div>
              <div class="heat-desc">{{ heatPrediction.prediction_details?.['72h']?.description }}</div>
            </div>
          </el-col>
        </el-row>
        <div v-if="heatPrediction.potential_variables?.length" class="heat-variables">
          <div class="detail-sub-title">影响热度的潜在变量</div>
          <div class="variable-list">
            <el-tag v-for="(v, idx) in heatPrediction.potential_variables.slice(0, 4)" :key="idx"
              size="small" effect="plain" class="variable-tag">
              {{ v.factor }}
              <span class="var-prob">({{ v.probability }})</span>
            </el-tag>
          </div>
        </div>
      </div>
    </el-card>

    <!-- ====== 处置建议 ====== -->
    <el-card v-if="actionAdvice" shadow="hover" class="chart-card">
      <template #header>
        <div class="card-header-row">
          <span class="card-title"><el-icon><MagicStick /></el-icon> 智能处置建议</span>
        </div>
      </template>
      <div class="advice-section">
        <!-- 辟谣话术 -->
        <div v-if="actionAdvice.rumor_refute" class="advice-block rumor-block">
          <div class="advice-block-title">
            <el-icon :size="16" color="#f56c6c"><Warning /></el-icon> 辟谣话术参考
          </div>
          <div class="advice-block-content rumor-content">{{ actionAdvice.rumor_refute }}</div>
        </div>

        <el-row :gutter="20">
          <!-- 普通用户建议 -->
          <el-col :xs="24" :md="12">
            <div class="advice-block">
              <div class="advice-block-title">
                <el-icon :size="16" color="#409eff"><Sunny /></el-icon> 普通用户建议
              </div>
              <div v-for="(item, idx) in actionAdvice.public_advice.slice(0, 3)" :key="'pub-'+idx" class="advice-item">
                <div class="advice-item-title">{{ item.title }}</div>
                <div class="advice-item-content">{{ item.content }}</div>
              </div>
              <div v-if="!actionAdvice.public_advice?.length" class="no-data-hint">暂无特别建议</div>
            </div>
          </el-col>
          <!-- 运营方建议 -->
          <el-col :xs="24" :md="12">
            <div class="advice-block">
              <div class="advice-block-title">
                <el-icon :size="16" color="#e6a23c"><Cloudy /></el-icon> 运营方建议
              </div>
              <div v-for="(item, idx) in actionAdvice.operation_advice.slice(0, 3)" :key="'ops-'+idx" class="advice-item">
                <div class="advice-item-title">{{ item.title }}</div>
                <div class="advice-item-content">{{ item.content }}</div>
              </div>
            </div>
          </el-col>
        </el-row>

        <!-- 规避次生谣言贴士 -->
        <div v-if="actionAdvice.risk_tips?.length" class="advice-block tips-block">
          <div class="advice-block-title">
            <el-icon :size="16" color="#67c23a"><Lock /></el-icon> 规避次生谣言贴士
          </div>
          <div v-for="(tip, idx) in actionAdvice.risk_tips" :key="'tip-'+idx" class="tip-item">
            <el-icon :size="14" color="#67c23a"><CircleCheckFilled /></el-icon>
            <span>{{ tip }}</span>
          </div>
        </div>

        <!-- 重点监测节点 -->
        <div v-if="actionAdvice.monitor_nodes?.length" class="advice-block">
          <div class="advice-block-title">
            <el-icon :size="16" color="#409eff"><Share /></el-icon> 重点监测节点清单
          </div>
          <el-table :data="actionAdvice.monitor_nodes.slice(0, 5)" stripe size="small">
            <el-table-column prop="node_name" label="节点名称" min-width="150" show-overflow-tooltip />
            <el-table-column prop="platform" label="平台" width="100" />
            <el-table-column prop="role" label="角色" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="row.role === '核心放大' ? 'danger' : row.role === '首发来源' ? 'warning' : 'info'" effect="plain">
                  {{ row.role }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="priority" label="优先级" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="row.priority === '高' ? 'danger' : 'warning'" effect="plain">
                  {{ row.priority }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </el-card>

    <!-- ====== 关联新闻列表 ====== -->
    <el-card shadow="hover" class="chart-card">
      <template #header>
        <div class="card-header-row">
          <span class="card-title"><el-icon><Document /></el-icon> 关联新闻报道</span>
          <el-tag type="info" size="small">共 {{ relatedNews.length }} 条</el-tag>
        </div>
      </template>
      <el-table :data="relatedNews" stripe highlight-current-row size="default">
        <el-table-column type="index" label="#" width="50" align="center" />
        <el-table-column prop="title" label="标题" min-width="300" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link v-if="row.original_url" :href="row.original_url" target="_blank" type="primary" :underline="false">
              {{ row.title }}
            </el-link>
            <span v-else>{{ row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="source_platform" label="来源平台" width="130">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.source_platform }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="published_at" label="发布时间" width="170" sortable />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import axios from 'axios'
import {
  ChatDotRound, InfoFilled, Clock, Refresh, TrendCharts, Histogram,
  Tickets, DataAnalysis, Lock, WarningFilled, CircleCheckFilled,
  Share, Document, Warning, Sunny, Cloudy, Lightning, MagicStick,
  Edit, Check,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const eventId = route.params.id

const pageLoading = ref(true)
const eventData = ref({})
const analysisData = ref(null)
const spreadData = ref(null)
const relatedNews = ref([])
const emotionData = ref(null)
const heatPrediction = ref(null)
const actionAdvice = ref(null)

// ==================== 概述编辑相关 ====================
const isEditingSummary = ref(false)
const editingSummaryText = ref('')
const savingSummary = ref(false)

// ==================== ECharts 图表实例 ====================
const timelineChartRef = ref(null)
const sentimentChartRef = ref(null)
const platformChartRef = ref(null)
let chartInstances = []

function initChart(domRef, option) {
  if (!domRef) return null
  const instance = echarts.init(domRef)
  instance.setOption(option)
  chartInstances.push(instance)
  return instance
}

function disposeCharts() {
  chartInstances.forEach(c => { try { c.dispose() } catch {} })
  chartInstances = []
}

onBeforeUnmount(disposeCharts)

// ==================== 工具函数 ====================
const riskTagType = (r) => ({ low: 'success', medium: 'warning', high: 'danger', critical: 'danger' }[r] || 'info')
const riskLabel = (r) => ({ low: '低风险', medium: '中风险', high: '高风险', critical: '严重' }[r] || r)
const lifecycleTagType = (l) => ({ latent: 'info', growth: 'success', peak: 'danger', decline: 'warning' }[l] || 'info')
const lifecycleLabel = (l) => ({ latent: '潜伏期', growth: '成长期', peak: '高潮期', decline: '衰退期' }[l] || l)

const goQA = () => router.push(`/qa?eventId=${eventId}`)

// ==================== 2. 报道量折线图 ====================
// 从关联新闻的发布时间统计每日报道量
const timelineOption = computed(() => {
  if (!relatedNews.value.length) return null

  // 按日期统计报道量
  const dateCount = {}
  relatedNews.value.forEach(n => {
    const day = (n.published_at || '').substring(0, 10) // YYYY-MM-DD
    if (day) dateCount[day] = (dateCount[day] || 0) + 1
  })

  const sorted = Object.entries(dateCount).sort((a, b) => a[0].localeCompare(b[0]))
  if (!sorted.length) return null

  const xData = sorted.map(d => d[0])
  const yData = sorted.map(d => d[1])

  // 找峰值日和首报日索引
  let peakIdx = 0
  let maxVal = 0
  yData.forEach((v, i) => { if (v > maxVal) { maxVal = v; peakIdx = i } })
  const firstIdx = 0

  // 构建关键节点标注
  const markPoints = []
  if (yData.length >= 1) {
    markPoints.push({
      coord: [xData[peakIdx], yData[peakIdx]],
      name: '峰值',
      value: `${xData[peakIdx].substring(5)}\n${yData[peakIdx]}篇`,
      itemStyle: { color: '#f56c6c' },
      symbolSize: 55,
      label: { fontSize: 11, color: '#fff', fontWeight: 700, formatter: '{b}' },
    })
  }
  if (yData.length >= 2) {
    markPoints.push({
      coord: [xData[firstIdx], yData[firstIdx]],
      name: '首报',
      value: `${xData[firstIdx].substring(5)}\n首报`,
      itemStyle: { color: '#67c23a' },
      symbolSize: 48,
      label: { fontSize: 11, color: '#fff', fontWeight: 700, formatter: '{b}' },
    })
  }

  return {
    tooltip: {
      trigger: 'axis',
      formatter(params) {
        const p = params[0]
        return `<b>${p.axisValue}</b><br/>报道量: <span style="color:#409eff;font-weight:700">${p.value}</span> 篇`
      },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', top: 30, containLabel: true },
    xAxis: {
      type: 'category',
      data: xData,
      axisLabel: { color: '#909399', fontSize: 11 },
      axisLine: { lineStyle: { color: '#e4e7ed' } },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: '#909399' },
      splitLine: { lineStyle: { type: 'dashed', color: '#f0f2f5' } },
    },
    series: [{
      name: '报道量',
      type: 'line',
      data: yData,
      smooth: true,
      symbol: 'circle',
      symbolSize: 8,
      lineStyle: { width: 3, color: '#409eff' },
      itemStyle: { color: '#409eff', borderColor: '#fff', borderWidth: 2 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(64,100,255,0.35)' },
            { offset: 1, color: 'rgba(160,60,220,0.03)' },
          ],
        },
      },
      markPoint: {
        data: markPoints,
        animation: true,
      },
      markLine: {
        data: [{ type: 'average', name: '平均' }],
        lineStyle: { type: 'dashed', color: '#e6a23c' },
        label: { fontSize: 11 },
      },
    }],
  }
})

// ==================== 3. 情感饼图 ====================
const sentimentOption = computed(() => {
  if (!analysisData.value) return null
  const a = analysisData.value
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, left: 'center', textStyle: { fontSize: 12 } },
    color: ['#67c23a', '#909399', '#f56c6c'],
    series: [{
      type: 'pie',
      radius: ['42%', '72%'],
      center: ['50%', '42%'],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
      label: { show: true, formatter: '{b}\n{d}%', fontSize: 12, lineHeight: 16 },
      labelLine: { length: 12, length2: 16 },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.15)' } },
      data: [
        { value: +(a.positive_ratio * 100).toFixed(1), name: '正面', itemStyle: { color: '#67c23a' } },
        { value: +(a.neutral_ratio * 100).toFixed(1), name: '中性', itemStyle: { color: '#909399' } },
        { value: +(a.negative_ratio * 100).toFixed(1), name: '负面', itemStyle: { color: '#f56c6c' } },
      ],
    }],
  }
})

// ==================== 4. 平台报道占比环形图 ====================
const platformOption = computed(() => {
  if (!analysisData.value || !analysisData.value.platform_coverage) return null
  const pc = analysisData.value.platform_coverage
  // 平台对应品牌色
  const colorMap = {
    '微博': '#e6162d', '人民网-时政': '#c7000b', '人民网-国际': '#1a73e8',
    '人民网-财经': '#ff8c00', '人民网-社会': '#1a73e8', '人民网-教育': '#34a853',
    '人民网-科技': '#5865f2', '抖音': '#000000', '知乎': '#0066ff',
    '微信公众号': '#07c160', '今日头条': '#ff0000', 'B站': '#fb7299',
  }
  const entries = Object.entries(pc)
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c}篇 ({d}%)' },
    legend: { bottom: 0, left: 'center', textStyle: { fontSize: 11 } },
    color: entries.map(([name]) => colorMap[name] || '#409eff'),
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['50%', '42%'],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 5, borderColor: '#fff', borderWidth: 2 },
      label: { show: true, formatter: '{b}\n{d}%', fontSize: 11, lineHeight: 16 },
      labelLine: { length: 10, length2: 14 },
      data: entries.map(([name, value]) => ({ name, value })),
    }],
  }
})

// ==================== 图表 watch：option 变化时初始化/更新 ECharts 实例 ====================
watch(timelineOption, (opt) => {
  nextTick(() => {
    if (opt && timelineChartRef.value) {
      const existing = chartInstances.find(c => c.getDom() === timelineChartRef.value)
      if (existing) { existing.setOption(opt, true) }
      else { initChart(timelineChartRef.value, opt) }
    }
  })
})

watch(sentimentOption, (opt) => {
  nextTick(() => {
    if (opt && sentimentChartRef.value) {
      const existing = chartInstances.find(c => c.getDom() === sentimentChartRef.value)
      if (existing) { existing.setOption(opt, true) }
      else { initChart(sentimentChartRef.value, opt) }
    }
  })
})

watch(platformOption, (opt) => {
  nextTick(() => {
    if (opt && platformChartRef.value) {
      const existing = chartInstances.find(c => c.getDom() === platformChartRef.value)
      if (existing) { existing.setOption(opt, true) }
      else { initChart(platformChartRef.value, opt) }
    }
  })
})

// ==================== 可信度相关 ====================
const credibilityScore = computed(() => {
  return analysisData.value?.credibility_score ?? null
})

// ==================== 传播链路力导向图 ====================
const formatNum = (n) => {
  if (n == null) return '0'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

// 力导向图 DOM 引用与实例
const spreadChartRef = ref(null)
let spreadChartInstance = null

// 节点角色中文映射
const nodeRoleMap = { origin: '首发', amplifier: '放大', secondary: '传播' }

// 初始化传播链路力导向图
function initSpreadChart() {
  const graphData = spreadData.value?.graph_data
  // 数据或 DOM 未就绪时不初始化
  if (!spreadChartRef.value || !graphData || !graphData.nodes?.length) return

  // 若已有实例，先销毁再重建，避免重复渲染
  if (spreadChartInstance) {
    spreadChartInstance.dispose()
    spreadChartInstance = null
  }

  spreadChartInstance = echarts.init(spreadChartRef.value)
  spreadChartInstance.setOption({
    // 提示框：展示节点角色与平台信息
    tooltip: {
      formatter(params) {
        if (params.dataType === 'node') {
          const d = params.data || {}
          const role = nodeRoleMap[d.type] || d.type || '未分类'
          const lines = [`<b>${d.name || d.platform || '未知节点'}</b>`]
          lines.push(`角色：${role}`)
          if (d.platform) lines.push(`平台：${d.platform}`)
          if (d.value != null) lines.push(`权重：${d.value}`)
          return lines.join('<br/>')
        }
        if (params.dataType === 'edge') {
          const d = params.data || {}
          return `${d.source} → ${d.target}`
        }
        return params.name || ''
      },
    },
    // 分类图例（从 categories 数据中取）
    legend: [
      {
        data: (graphData.categories || []).map(c => c.name),
        textStyle: { fontSize: 12, color: '#606266' },
        bottom: 4,
      },
    ],
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true, // 允许拖拽缩放
        categories: graphData.categories || [],
        data: graphData.nodes || [], // symbolSize 从节点数据中取
        links: graphData.links || [], // lineStyle 从边数据中取
        // 节点标签
        label: {
          show: true,
          position: 'right',
          fontSize: 12,
          color: '#303133',
        },
        // 边默认样式（可被数据中自带的 lineStyle 覆盖）
        lineStyle: {
          color: 'source',
          curveness: 0.2,
        },
        // 鼠标悬浮高亮相邻节点
        emphasis: {
          focus: 'adjacency',
          lineStyle: { width: 3 },
          label: { fontWeight: 700 },
        },
        // 力导向参数
        force: {
          repulsion: 200,
          edgeLength: 120,
          gravity: 0.1,
        },
      },
    ],
  })
}

// 监听 spreadData 变化，数据就绪后初始化力导向图
watch(spreadData, () => {
  nextTick(() => {
    initSpreadChart()
  })
})

// 组件卸载时销毁力导向图实例，释放资源
onBeforeUnmount(() => {
  if (spreadChartInstance) {
    spreadChartInstance.dispose()
    spreadChartInstance = null
  }
})

// ==================== 概述文本清理（去除 JSON、去除【标签】） ====================
const cleanSummary = computed(() => {
  let raw = eventData.value?.summary || ''
  if (!raw) return ''
  // 如果内容看起来像 JSON（包含 interaction_data 等），尝试提取纯文本
  if (raw.startsWith('{') || raw.startsWith('[')) {
    // 尝试解析为 JSON，如果是对象则显示为空（不展示原始 JSON）
    try {
      const parsed = JSON.parse(raw)
      if (typeof parsed === 'object') return ''
    } catch { /* 不是合法 JSON，继续按文本处理 */ }
  }
  // 去除【时间】【地点】【相关】【概述】等标签，只保留纯文本
  raw = raw.replace(/【(?:时间|地点|相关|概述|标签|来源|事件)】/g, '')
  // 去除其他 【xxx】 格式标签
  raw = raw.replace(/【[^】]+】/g, '')
  // 去除行首空格
  raw = raw.trim()
  if (!raw) return ''
  // 将换行转为 <br>
  return raw.replace(/\n/g, '<br>')
})

// ==================== 交互数据相关 ====================
const interactionData = computed(() => {
  // 优先从 eventData 的 interaction_data 字段读取
  return eventData.value?.interaction_data || null
})

// 情感标签映射：0=中性、1=正面、2=负面、3=其他
const sentimentTagType = (label) => {
  const map = { 0: 'info', 1: 'success', 2: 'danger', 3: 'warning' }
  return map[label] ?? 'info'
}
const sentimentTagLabel = (label) => {
  const map = { 0: '中性', 1: '正面', 2: '负面', 3: '其他' }
  return map[label] ?? '未知'
}

// 来源渠道映射：0=推荐、1=搜索
const sourceTagLabel = (source) => {
  const map = { 0: '推荐', 1: '搜索' }
  return map[source] ?? '未知'
}

// 热度值格式化（万为单位）
const formatHeat = (val) => {
  if (val == null) return '--'
  if (val >= 10000) return (val / 10000).toFixed(0) + ' 万'
  return val.toLocaleString()
}

// ==================== 概述编辑方法 ====================
const startEditSummary = () => {
  editingSummaryText.value = eventData.value?.summary || ''
  isEditingSummary.value = true
}
const cancelEditSummary = () => {
  isEditingSummary.value = false
  editingSummaryText.value = ''
}
const saveSummary = async () => {
  savingSummary.value = true
  try {
    const token = localStorage.getItem('token')
    const res = await axios.put(`/api/events/${eventId}/summary`, {
      summary: editingSummaryText.value,
    }, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (res.data.code === 200 || res.status === 200) {
      // 更新本地数据
      eventData.value = { ...eventData.value, summary: editingSummaryText.value }
      isEditingSummary.value = false
      ElMessage.success('概述已保存')
    } else {
      ElMessage.error(res.data.msg || '保存失败')
    }
  } catch (err) {
    ElMessage.error('保存概述失败：' + (err.response?.data?.detail || err.message))
  } finally {
    savingSummary.value = false
  }
}

const credibilityLevel = computed(() => {
  const s = credibilityScore.value
  if (s === null) return 'unknown'
  if (s >= 0.7) return 'high'
  if (s >= 0.4) return 'medium'
  return 'low'
})

const credibilityLabel = computed(() => {
  const map = { high: '高可信', medium: '待验证', low: '疑似虚假', unknown: '未评估' }
  return map[credibilityLevel.value]
})

const credibilityDesc = computed(() => {
  const s = credibilityScore.value
  if (s === null) return ''
  if (s >= 0.7) return '该事件关联的新闻报道整体可信度较高，来源正规、用词客观、包含具体数据支撑，虚假信息风险较低。'
  if (s >= 0.4) return '该事件关联报道整体可信，但部分文本存在轻微的特征偏差（如标题偏向吸引眼球），建议结合多源交叉验证。'
  return '该事件关联报道存在虚假信息风险特征，部分内容可能包含标题党、匿名来源或缺乏数据支撑等可疑元素，建议谨慎对待并核实信息来源。'
})

// ==================== 加载数据 ====================
const loadEvent = async () => {
  pageLoading.value = true
  try {
    const token = localStorage.getItem('token')
    const res = await axios.get(`/api/routes/event/${eventId}/full`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (res.data.code === 200) {
      const d = res.data.data
      eventData.value = d.event || {}
      analysisData.value = d.analysis || null
      spreadData.value = d.spread || null
      relatedNews.value = d.related_news || []
      emotionData.value = d.emotion || null
      heatPrediction.value = d.heat_prediction || null
      actionAdvice.value = d.action_advice || null
    }
  } catch (err) {
    ElMessage.error('加载事件详情失败')
  } finally {
    pageLoading.value = false
  }
}

onMounted(loadEvent)
</script>

<style scoped>
.breadcrumb {
  margin-bottom: 16px;
}
.breadcrumb :deep(.el-breadcrumb__item) {
  transition: all 0.3s ease;
}
.breadcrumb :deep(.el-breadcrumb__inner) {
  transition: color 0.3s ease, transform 0.3s ease;
  display: inline-block;
}
.breadcrumb :deep(.el-breadcrumb__inner:hover) {
  color: #7c3aed;
  transform: translateX(2px);
}
.breadcrumb :deep(.el-breadcrumb__separator) {
  transition: opacity 0.3s ease;
}

/* ========== 全局卡片悬浮与圆角 ========== */
.event-detail-page :deep(.el-card) {
  border-radius: 16px;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.event-detail-page :deep(.el-card:hover) {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12) !important;
}

/* ========== 概述卡片 ========== */
.summary-card { margin-bottom: 16px; }
.summary-header { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 16px; }
.event-title { margin: 0 0 12px; font-size: 24px; font-weight: 700; color: #1d1d1f; }
.event-tags { display: flex; gap: 8px; flex-wrap: wrap; }

/* 渐变药丸标签 */
.pill-tag {
  display: inline-flex;
  align-items: center;
  padding: 6px 18px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  letter-spacing: 0.5px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}
.pill-tag.risk-high,
.pill-tag.risk-critical {
  background: linear-gradient(135deg, #f56c6c, #e04040);
}
.pill-tag.risk-medium {
  background: linear-gradient(135deg, #e6a23c, #d48806);
}
.pill-tag.risk-low {
  background: linear-gradient(135deg, #67c23a, #52b025);
}
.pill-tag.risk-info {
  background: linear-gradient(135deg, #909399, #7a7d82);
}
.pill-tag.lifecycle-latent {
  background: linear-gradient(135deg, #909399, #7a7d82);
}
.pill-tag.lifecycle-growth {
  background: linear-gradient(135deg, #67c23a, #52b025);
}
.pill-tag.lifecycle-peak {
  background: linear-gradient(135deg, #f56c6c, #e04040);
}
.pill-tag.lifecycle-decline {
  background: linear-gradient(135deg, #e6a23c, #d48806);
}
.pill-tag.lifecycle-info {
  background: linear-gradient(135deg, #909399, #7a7d82);
}
.pill-tag.heat-pill {
  background: linear-gradient(135deg, #409eff, #66b1ff);
}
.pill-tag.heat-pill strong {
  font-size: 18px;
  font-weight: 800;
  margin-left: 2px;
}
.pill-tag.credibility-high { background: rgba(103,194,58,0.12); color: #67c23a; }
.pill-tag.credibility-medium { background: rgba(230,162,60,0.12); color: #e6a23c; }
.pill-tag.credibility-low { background: rgba(245,108,108,0.12); color: #f56c6c; }
.pill-tag.credibility-unknown { background: rgba(144,147,153,0.12); color: #909399; }
.event-summary-text { display: flex; gap: 8px; align-items: flex-start; color: #606266; font-size: 14px; line-height: 1.8; margin: 12px 0; }
.event-meta { display: flex; gap: 24px; color: #a0a4ad; font-size: 13px; }
.event-meta span { display: flex; align-items: center; gap: 4px; }

/* ========== 概述编辑区域 ========== */
.summary-text-area { margin: 4px 0; }
.summary-edit-row { display: flex; justify-content: flex-end; margin-top: 4px; }
.summary-edit-input { margin-top: 8px; }
.summary-edit-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.no-summary-hint { color: #909399; font-style: italic; }

/* ========== 交互数据指标卡片 ========== */
.interaction-card { margin-bottom: 16px; }
.interaction-metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
}
.interaction-metric-item {
  background: #f8f9fb;
  border-radius: 12px;
  padding: 20px 16px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  transition: transform 0.2s, box-shadow 0.2s;
}
.interaction-metric-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}
.metric-label {
  font-size: 13px;
  color: #909399;
  font-weight: 500;
}
.metric-value {
  font-size: 28px;
  font-weight: 800;
  color: #303133;
  line-height: 1.2;
}
.metric-tag {
  font-size: 16px;
  font-weight: 600;
  padding: 8px 20px;
}
.metric-sub {
  font-size: 11px;
  color: #b0b3ba;
}
.heat-metric {
  background: linear-gradient(135deg, #eef3ff 0%, #f0eaff 100%);
  border: 1px solid #e6e9f5;
}
.heat-value {
  background: linear-gradient(135deg, #409eff, #66b1ff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* ========== 图表卡片 ========== */
.chart-card { margin-bottom: 16px; }
.chart-card :deep(.el-card__header) { padding: 12px 20px; }
.card-title { font-size: 15px; font-weight: 600; color: #303133; display: flex; align-items: center; gap: 6px; }
.card-header-row { display: flex; justify-content: space-between; align-items: center; }

.wide-chart { height: 260px; }
.charts-row { margin-bottom: 16px; }
.mini-card :deep(.el-card__header) { padding: 10px 16px; }
.square-chart { height: 280px; }

/* ========== 情感详情网格 ========== */
.sentiment-detail-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.sentiment-card {
  padding: 24px;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  position: relative;
  overflow: hidden;
}

.positive-card { background: linear-gradient(135deg, #43a047, #66bb6a); }
.neutral-card { background: linear-gradient(135deg, #78909c, #90a4ae); }
.negative-card { background: linear-gradient(135deg, #e53935, #ef5350); }

.sentiment-icon { font-size: 36px; margin-bottom: 8px; }
.sentiment-percentage { font-size: 28px; font-weight: 800; color: #ffffff; }
.sentiment-label { font-size: 13px; color: rgba(255, 255, 255, 0.85); margin-top: 2px; }
.sentiment-progress { width: 100%; margin-top: 16px; }

/* 情感卡片白色进度条轨道 */
.sentiment-card :deep(.el-progress-bar__outer) { background: rgba(255, 255, 255, 0.25); border-radius: 4px; }
.sentiment-card :deep(.el-progress-bar__inner) { border-radius: 4px; }

/* ========== 关联新闻 ========== */
.event-detail-page :deep(.el-table__body tr:hover > td) {
  background: linear-gradient(135deg, #eef1ff, #f3f0ff) !important;
}

/* ========== 传播链路图 ========== */

/* ========== 可信度评分 ========== */
.credibility-section {
  display: flex;
  gap: 32px;
  align-items: flex-start;
}

.credibility-score-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

/* CSS 圆环进度 */
.credibility-ring {
  position: relative;
  width: 120px;
  height: 120px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ring-bg {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: conic-gradient(#e4e7ed 0% 100%);
  mask: radial-gradient(transparent 56%, #000 57%);
  -webkit-mask: radial-gradient(transparent 56%, #000 57%);
}

.ring-fill {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: conic-gradient(
    from 180deg,
    var(--ring-color, #4064ff) 0%,
    var(--ring-color, #4064ff) var(--pct, 0%),
    #e4e7ed var(--pct, 0%) 100%
  );
  mask: radial-gradient(transparent 56%, #000 57%);
  -webkit-mask: radial-gradient(transparent 56%, #000 57%);
  transition: background 0.6s ease;
}

.credibility-ring.high .ring-fill { --ring-color: #67c23a; }
.credibility-ring.medium .ring-fill { --ring-color: #e6a23c; }
.credibility-ring.low .ring-fill { --ring-color: #f56c6c; }
.credibility-ring.unknown .ring-fill { --ring-color: #909399; }

.ring-text {
  position: relative;
  text-align: center;
  z-index: 1;
}
.ring-value {
  font-size: 48px;
  font-weight: 800;
  line-height: 1;
  background: linear-gradient(135deg, #4064ff, #7c3aed);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.ring-unit { font-size: 12px; color: #909399; margin-top: 2px; }

.credibility-ring.high .ring-value { color: #4064ff; }
.credibility-ring.medium .ring-value { color: #7c3aed; }
.credibility-ring.low .ring-value { color: #a855f7; }

.credibility-label {
  font-size: 15px;
  font-weight: 600;
  padding: 4px 16px;
  border-radius: 20px;
}
.credibility-label.high { color: #4064ff; background: #eef1ff; }
.credibility-label.medium { color: #7c3aed; background: #f3f0ff; }
.credibility-label.low { color: #a855f7; background: #faf5ff; }

/* 右侧详情 */
.credibility-details { flex: 1; }
.detail-desc {
  font-size: 14px;
  color: #606266;
  line-height: 1.7;
  margin-bottom: 16px;
  padding: 12px 16px;
  background: #f8f9fb;
  border-radius: 8px;
  border-left: 3px solid #409eff;
}

.fake-flags { margin-top: 8px; }
.flags-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; }
.flags-list { display: flex; flex-wrap: wrap; gap: 8px; }
.fake-flag-tag { font-size: 13px; display: flex; align-items: center; gap: 4px; }

.no-flags {
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; color: #67c23a; margin-top: 8px;
}

/* ========== 传播链路图 ========== */
.spread-chart-wrapper {
  position: relative;
  background: linear-gradient(135deg, #f5f7ff 0%, #f0eaff 50%, #eef1ff 100%);
  border-radius: 12px;
  padding: 8px;
}
.spread-chart-wrapper::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  border-radius: 12px;
  background: radial-gradient(circle at 20% 80%, rgba(64, 100, 255, 0.06) 0%, transparent 50%),
              radial-gradient(circle at 80% 20%, rgba(124, 58, 237, 0.06) 0%, transparent 50%);
  pointer-events: none;
}
.spread-chart {
  height: 400px;
}
.spread-chart-container {
  width: 100%;
  height: 400px;
  background: linear-gradient(135deg, #f5f7ff 0%, #f0eaff 50%, #eef1ff 100%);
  border-radius: 12px;
}
.spread-nodes-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 16px;
  justify-content: center;
  align-items: center;
  min-height: 200px;
}
.spread-node-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.node-role {
  font-size: 12px;
  color: #909399;
}
.wordcloud-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px;
  justify-content: center;
  align-items: center;
  min-height: 200px;
}
.word-tag {
  margin: 2px;
  transition: transform 0.2s;
}
.word-tag:hover {
  transform: scale(1.08);
}

.spread-legend {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #606266;
}

.legend-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

/* ========== 响应式 ========== */
@media (max-width: 768px) {
  .sentiment-detail-grid { grid-template-columns: 1fr; }
  .square-chart { height: 240px; }
  .wide-chart { height: 220px; }
  .spread-chart { height: 300px; }
}

/* ========== 情绪量化分析样式 ========== */
.emotion-bar-group { display: flex; flex-direction: column; gap: 16px; padding: 8px 0; }
.emotion-bar-item { display: flex; align-items: center; gap: 12px; }
.emotion-label { font-size: 13px; font-weight: 600; min-width: 36px; }
.positive-label { color: #67c23a; }
.neutral-label { color: #e6a23c; }
.negative-label { color: #f56c6c; }

.emotion-detail { padding: 4px 0; }
.detail-sub-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; }
.agitated-section { margin-bottom: 12px; }
.agitated-node { margin-bottom: 10px; }
.agitated-tag { margin-right: 6px; }
.agitated-text { font-size: 12px; color: #606266; }
.agitated-cause { font-size: 11px; color: #909399; margin-top: 2px; padding-left: 10px; }
.fluctuation-section { margin-top: 8px; }
.fluctuation-item { display: flex; align-items: flex-start; gap: 6px; font-size: 12px; color: #606266; margin-bottom: 6px; line-height: 1.5; }
.no-data-hint { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #909399; padding: 12px 0; }

/* ========== 热度走势预判样式 ========== */
.heat-prediction-section { padding: 4px 0; }
.heat-summary-text { font-size: 14px; color: #303133; line-height: 1.6; margin-bottom: 16px; padding: 12px; background: #f5f7fa; border-radius: 8px; }
.heat-detail-row { margin-bottom: 16px; }
.heat-time-block { padding: 12px; background: #fafafa; border-radius: 8px; border-left: 3px solid #409eff; }
.heat-time-title { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; }
.heat-direction { font-size: 22px; font-weight: 700; margin-bottom: 6px; }
.heat-direction.dir-up { color: #f56c6c; }
.heat-direction.dir-down { color: #67c23a; }
.heat-direction.dir-stable { color: #e6a23c; }
.heat-desc { font-size: 12px; color: #606266; line-height: 1.5; }
.heat-variables { margin-top: 12px; }
.variable-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
.variable-tag { font-size: 12px; }
.var-prob { color: #909399; font-size: 11px; margin-left: 2px; }

/* ========== 处置建议样式 ========== */
.advice-section { padding: 4px 0; }
.advice-block { margin-bottom: 16px; }
.advice-block-title { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 10px; }
.rumor-block { padding: 12px; background: #fef0f0; border-radius: 8px; border: 1px solid #fde2e2; }
.rumor-content { font-size: 13px; color: #f56c6c; line-height: 1.6; }
.advice-item { margin-bottom: 10px; padding: 8px 12px; background: #f5f7fa; border-radius: 6px; }
.advice-item-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 4px; }
.advice-item-content { font-size: 12px; color: #606266; line-height: 1.5; }
.tips-block { padding: 12px; background: #f0f9eb; border-radius: 8px; border: 1px solid #e1f3d8; }
.tip-item { display: flex; align-items: flex-start; gap: 6px; font-size: 12px; color: #606266; margin-bottom: 6px; line-height: 1.5; }
</style>
