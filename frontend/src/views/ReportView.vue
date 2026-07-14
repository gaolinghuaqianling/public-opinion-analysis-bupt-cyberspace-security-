<template>
  <div class="report-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="page-title">报表导出</h1>
      <p class="page-desc">支持导出舆情日报、周报及事件专报，可生成 Word 或 PDF 格式文件</p>
    </div>

    <!-- 三个报表卡片 -->
    <el-row :gutter="24">
      <!-- 卡片1：舆情日报 -->
      <el-col :xs="24" :sm="24" :md="8">
        <el-card class="report-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <el-icon :size="22" color="#409eff"><Document /></el-icon>
              <span class="card-title">舆情日报</span>
            </div>
          </template>
          <p class="card-desc">
            当日全网监测整体概况、新增热点、热度排行、风险预警
          </p>
          <div class="card-actions">
            <el-button type="primary" @click="handleExport('daily', 'docx')" :loading="loading['daily-docx']">
              导出 Word
            </el-button>
            <el-button type="success" @click="handleExport('daily', 'pdf')" :loading="loading['daily-pdf']">
              导出 PDF
            </el-button>
          </div>
        </el-card>
      </el-col>

      <!-- 卡片2：舆情周报 -->
      <el-col :xs="24" :sm="24" :md="8">
        <el-card class="report-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <el-icon :size="22" color="#67c23a"><TrendCharts /></el-icon>
              <span class="card-title">舆情周报</span>
            </div>
          </template>
          <p class="card-desc">
            本周热度趋势、情感变化、负面话题、传播统计、虚假信息
          </p>
          <div class="card-actions">
            <el-button type="primary" @click="handleExport('weekly', 'docx')" :loading="loading['weekly-docx']">
              导出 Word
            </el-button>
            <el-button type="success" @click="handleExport('weekly', 'pdf')" :loading="loading['weekly-pdf']">
              导出 PDF
            </el-button>
          </div>
        </el-card>
      </el-col>

      <!-- 卡片3：事件专报 -->
      <el-col :xs="24" :sm="24" :md="8">
        <el-card class="report-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <el-icon :size="22" color="#e6a23c"><DataAnalysis /></el-icon>
              <span class="card-title">事件专报</span>
            </div>
          </template>
          <p class="card-desc">
            针对单一事件的完整复盘，包含传播路径、情感走势、关键节点分析
          </p>
          <div class="event-input-area">
            <el-input
              v-model="eventId"
              type="number"
              placeholder="请输入事件 ID"
              :min="1"
              class="event-id-input"
            />
          </div>
          <div class="card-actions">
            <el-button
              type="primary"
              @click="handleExportEvent('docx')"
              :loading="loading['event-docx']"
              :disabled="!eventId"
            >
              导出 Word
            </el-button>
            <el-button
              type="success"
              @click="handleExportEvent('pdf')"
              :loading="loading['event-pdf']"
              :disabled="!eventId"
            >
              导出 PDF
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, TrendCharts, DataAnalysis } from '@element-plus/icons-vue'
import axios from 'axios'

// 事件 ID 输入
const eventId = ref(null)

// 各按钮加载状态
const loading = reactive({
  'daily-docx': false,
  'daily-pdf': false,
  'weekly-docx': false,
  'weekly-pdf': false,
  'event-docx': false,
  'event-pdf': false,
})

/**
 * 通用报表导出方法
 * @param {string} url - 请求的 API 地址（含 query 参数）
 * @param {string} filename - 下载时使用的文件名
 * @param {string} loadingKey - 对应 loading 状态的 key
 */
const exportReport = async (url, filename, loadingKey) => {
  loading[loadingKey] = true
  try {
    const token = localStorage.getItem('token')
    const res = await axios.get(url, {
      headers: { Authorization: `Bearer ${token}` },
      responseType: 'blob',
    })

    // 检查返回内容是否为 JSON 错误信息（后端 503 等情况）
    const contentType = res.headers['content-type']
    if (contentType && contentType.includes('application/json')) {
      // blob 转文本，解析错误信息
      const text = await res.data.text()
      const errData = JSON.parse(text)
      ElMessage.error(errData.detail || '导出失败')
      return
    }

    // 创建临时链接下载文件
    const blob = new Blob([res.data])
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = filename
    link.click()
    URL.revokeObjectURL(link.href)
    ElMessage.success('报表导出成功')
  } catch (err) {
    const msg = err.response?.data?.detail || err.message || '导出失败，请稍后重试'
    ElMessage.error(msg)
  } finally {
    loading[loadingKey] = false
  }
}

/**
 * 日报 / 周报导出
 */
const handleExport = (type, format) => {
  const url = `/api/reports/${type}?format=${format}`
  const filename = type === 'daily' ? '舆情日报' : '舆情周报'
  const ext = format === 'pdf' ? '.pdf' : '.docx'
  exportReport(url, `${filename}${ext}`, `${type}-${format}`)
}

/**
 * 事件专报导出
 */
const handleExportEvent = (format) => {
  if (!eventId.value) {
    ElMessage.warning('请先输入事件 ID')
    return
  }
  const url = `/api/reports/event/${eventId.value}?format=${format}`
  const ext = format === 'pdf' ? '.pdf' : '.docx'
  exportReport(url, `事件专报_${eventId.value}${ext}`, `event-${format}`)
}
</script>

<style scoped>
.report-page {
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 28px;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 8px 0;
}

.page-desc {
  font-size: 14px;
  color: #94a3b8;
  margin: 0;
}

/* ========== 卡片样式 ========== */
.report-card {
  margin-bottom: 24px;
  border-radius: 12px;
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}

.report-card:hover {
  transform: translateY(-2px);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-title {
  font-size: 17px;
  font-weight: 600;
  color: #1e293b;
}

.card-desc {
  font-size: 13px;
  color: #64748b;
  line-height: 1.7;
  margin: 0 0 20px 0;
  min-height: 48px;
}

.event-input-area {
  margin-bottom: 16px;
}

.event-id-input {
  width: 100%;
}

.card-actions {
  display: flex;
  gap: 12px;
}

/* ========== 响应式 ========== */
@media (max-width: 768px) {
  .card-actions {
    flex-direction: column;
  }
}
</style>
