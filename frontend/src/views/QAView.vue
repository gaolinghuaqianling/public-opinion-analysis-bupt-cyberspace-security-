<template>
  <div class="chat-page">
    <!-- 面包屑 -->
    <el-breadcrumb separator="/" class="breadcrumb">
      <el-breadcrumb-item :to="{ path: '/event-board' }">事件看板</el-breadcrumb-item>
      <el-breadcrumb-item>智能问答</el-breadcrumb-item>
    </el-breadcrumb>

    <el-row :gutter="16" class="chat-layout">
      <!-- ====== 左侧面板 ====== -->
      <el-col :xs="24" :md="6" class="sidebar-col">
        <!-- 事件选择 -->
        <el-card shadow="hover" class="sidebar-card">
          <template #header>
            <span class="card-title"><el-icon><Document /></el-icon> 当前事件</span>
          </template>

          <el-select
            v-model="selectedEventId"
            placeholder="选择要分析的事件"
            style="width: 100%"
            filterable
            @change="onEventChange"
          >
            <el-option
              v-for="ev in eventOptions"
              :key="ev.id"
              :label="`#${ev.id} ${ev.title.substring(0, 16)}${ev.title.length > 16 ? '...' : ''}`"
              :value="ev.id"
            />
          </el-select>

          <!-- 事件预览 -->
          <div v-if="selectedEvent" class="event-preview">
            <div class="preview-title">{{ selectedEvent.title }}</div>
            <div class="preview-tags">
              <el-tag :type="riskTagType(selectedEvent.risk_level)" size="small">
                {{ riskLabel(selectedEvent.risk_level) }}
              </el-tag>
              <el-tag :type="lifecycleTagType(selectedEvent.lifecycle)" size="small">
                {{ lifecycleLabel(selectedEvent.lifecycle) }}
              </el-tag>
              <el-tag type="info" size="small">热度 {{ selectedEvent.heat_score }}</el-tag>
            </div>
            <p class="preview-summary">{{ selectedEvent.summary?.substring(0, 60) }}...</p>
          </div>
          <el-empty v-else description="请选择一个事件" :image-size="60" />
        </el-card>

        <!-- 快捷问题 -->
        <el-card v-if="selectedEvent && !messages.length" shadow="hover" class="sidebar-card">
          <template #header>
            <span class="card-title"><el-icon><Lightning /></el-icon> 快捷提问</span>
          </template>
          <div class="quick-questions">
            <div
              v-for="(q, idx) in quickQuestions"
              :key="idx"
              class="quick-item"
              @click="quickAsk(q)"
            >
              <el-icon :size="14"><ChatLineSquare /></el-icon>
              <span>{{ q }}</span>
            </div>
          </div>
        </el-card>

        <!-- 历史对话 -->
        <el-card shadow="hover" class="sidebar-card history-card">
          <template #header>
            <div class="history-header">
              <span class="card-title"><el-icon><Timer /></el-icon> 历史对话</span>
              <el-button v-if="history.length" link type="danger" size="small" @click="clearHistory">清空</el-button>
            </div>
          </template>
          <div v-if="history.length" class="history-list">
            <div
              v-for="(item, idx) in history"
              :key="idx"
              class="history-item"
              @click="restoreHistory(item)"
            >
              <div class="history-event">事件 #{{ item.eventId }}</div>
              <div class="history-q">{{ item.question }}</div>
              <div class="history-time">{{ item.time }}</div>
            </div>
          </div>
          <el-empty v-else description="暂无历史" :image-size="50" />
        </el-card>
      </el-col>

      <!-- ====== 右侧聊天区域 ====== -->
      <el-col :xs="24" :md="18" class="chat-col">
        <el-card shadow="hover" class="chat-card">
          <!-- 聊天头部 -->
          <template #header>
            <div class="chat-header">
              <div class="chat-header-left">
                <el-avatar :size="32" :icon="Service" style="background:#409eff;color:#fff" />
                <div>
                  <div class="chat-bot-name">舆情分析助手</div>
                  <div class="chat-bot-status">
                    <span class="status-dot" :class="{ online: !loading, busy: loading }"></span>
                    {{ loading ? '思考中...' : '在线' }}
                  </div>
                </div>
              </div>
              <div class="chat-header-right">
                <el-tag v-if="selectedEvent" type="info" effect="plain" size="small">
                  事件 #{{ selectedEventId }}
                </el-tag>
                <el-tooltip content="清空当前对话">
                  <el-button link :icon="Delete" @click="clearMessages" />
                </el-tooltip>
              </div>
            </div>
          </template>

          <!-- 消息列表 -->
          <div ref="chatBoxRef" class="chat-messages" @scroll="onScroll">
            <!-- 顶部加载更多 -->
            <div v-if="hasMoreHistory" class="load-more">
              <el-button link type="primary" size="small" @click="loadMoreHistory">加载更早消息</el-button>
            </div>

            <!-- 欢迎消息 -->
            <div v-if="!messages.length && !loading" class="welcome-section">
              <div class="welcome-icon">
                <el-icon :size="48" color="#409eff"><ChatDotRound /></el-icon>
              </div>
              <h3 class="welcome-title">舆情智能问答助手</h3>
              <p v-if="selectedEvent" class="welcome-desc">
                当前正在分析事件「{{ selectedEvent.title }}」，请在下方输入框提问
              </p>
              <p v-else class="welcome-desc">请先在左侧选择一个事件，然后开始提问</p>
            </div>

            <!-- 消息气泡 -->
            <template v-for="(msg, idx) in messages" :key="msg.id">
              <!-- 时间分隔线（超过5分钟间隔显示） -->
              <div v-if="shouldShowTime(idx)" class="time-divider">
                <span>{{ formatDividerTime(msg.time) }}</span>
              </div>

              <!-- 用户消息 -->
              <div v-if="msg.role === 'user'" class="message-row user">
                <el-avatar :size="36" :icon="UserFilled" class="avatar user-avatar" />
                <div class="message-body">
                  <div class="message-bubble user-bubble">
                    {{ msg.content }}
                  </div>
                  <div class="message-meta">
                    <span class="msg-time">{{ msg.time }}</span>
                    <el-tooltip content="复制">
                      <el-icon class="msg-action" :size="13" @click.stop="copyText(msg.content)"><CopyDocument /></el-icon>
                    </el-tooltip>
                  </div>
                </div>
              </div>

              <!-- 助手消息 -->
              <div v-else class="message-row assistant">
                <el-avatar :size="36" :icon="Service" class="avatar bot-avatar" />
                <div class="message-body">
                  <div class="message-bubble bot-bubble">
                    <div class="msg-content" v-html="renderMarkdown(msg.content)"></div>
                  </div>
                  <div class="message-meta">
                    <span class="msg-time">{{ msg.time }}</span>
                    <el-tooltip content="复制">
                      <el-icon class="msg-action" :size="13" @click.stop="copyText(msg.content)"><CopyDocument /></el-icon>
                    </el-tooltip>
                    <el-tooltip v-if="idx === messages.length - 1" content="重新生成">
                      <el-icon class="msg-action" :size="13" @click.stop="regenerate(msg)"><RefreshRight /></el-icon>
                    </el-tooltip>
                  </div>
                </div>
              </div>
            </template>

            <!-- 加载占位 -->
            <div v-if="loading" class="message-row assistant">
              <el-avatar :size="36" :icon="Service" class="avatar bot-avatar" />
              <div class="message-body">
                <div class="message-bubble bot-bubble typing-bubble">
                  <div class="typing-indicator">
                    <span></span><span></span><span></span>
                  </div>
                  <span class="typing-text">正在分析中</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 输入区域 -->
          <div class="chat-input-area">
            <div class="input-wrapper">
              <el-input
                ref="inputRef"
                v-model="inputText"
                type="textarea"
                :autosize="{ minRows: 1, maxRows: 4 }"
                placeholder="输入你的问题... (Enter 发送, Shift+Enter 换行)"
                resize="none"
                :disabled="loading || !selectedEventId"
                @keydown="onKeydown"
              />
              <el-button
                type="primary"
                :icon="Promotion"
                :loading="loading"
                :disabled="!inputText.trim() || !selectedEventId"
                class="send-btn"
                @click="sendMessage"
              />
            </div>
            <div class="input-tips">
              <span v-if="!selectedEventId" class="tip-warn">
                <el-icon><WarningFilled /></el-icon> 请先选择事件
              </span>
              <span v-else class="tip-info">按 Enter 发送，Shift+Enter 换行</span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import {
  Service, Delete, ChatDotRound, UserFilled, Promotion,
  WarningFilled, RefreshRight,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

// ==================== 状态 ====================
const selectedEventId = ref(Number(route.query.eventId) || null)
const selectedEvent = ref(null)
const eventOptions = ref([])
const inputText = ref('')
const messages = ref([])
const loading = ref(false)
const chatBoxRef = ref(null)
const inputRef = ref(null)
const history = ref([])
const hasMoreHistory = ref(false)

let msgIdCounter = 0
const genId = () => ++msgIdCounter

// 快捷问题
const quickQuestions = [
  '这个事件的核心议题是什么？',
  '舆论情感倾向如何，正面还是负面居多？',
  '有哪些潜在风险需要关注？',
  '主要传播平台是哪些？',
  '事件目前处于什么生命周期阶段？',
]

// ==================== 工具函数 ====================
const riskTagType = (r) => ({ low: 'success', medium: 'warning', high: 'danger', critical: 'danger' }[r] || 'info')
const riskLabel = (r) => ({ low: '低风险', medium: '中风险', high: '高风险', critical: '严重' }[r] || r)
const lifecycleTagType = (l) => ({ latent: 'info', growth: 'success', peak: 'danger', decline: 'warning' }[l] || 'info')
const lifecycleLabel = (l) => ({ latent: '潜伏期', growth: '成长期', peak: '高潮期', decline: '衰退期' }[l] || l)

// 简易 Markdown 渲染（**加粗**、*斜体*、`代码`、- 列表）
const renderMarkdown = (text) => {
  if (!text) return ''
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code style="background:#f0f2f5;padding:1px 5px;border-radius:3px;font-size:13px">$1</code>')
    .replace(/^[-•]\s+(.+)/gm, '<div style="padding-left:12px;position:relative"><span style="position:absolute;left:0">•</span>$1</div>')
    .replace(/\n/g, '<br>')
}

const formatTime = () => {
  const now = new Date()
  return now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

const formatDividerTime = (time) => {
  return time || ''
}

const shouldShowTime = (idx) => {
  if (idx === 0) return true
  const prev = messages.value[idx - 1]
  const curr = messages.value[idx]
  if (!prev || !curr) return false
  // 超过5分钟显示时间分隔
  return curr.time !== prev.time
}

const scrollToBottom = (smooth = true) => {
  nextTick(() => {
    if (chatBoxRef.value) {
      chatBoxRef.value.scrollTo({
        top: chatBoxRef.value.scrollHeight,
        behavior: smooth ? 'smooth' : 'instant',
      })
    }
  })
}

const copyText = (text) => {
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('已复制')
  }).catch(() => {
    ElMessage.warning('复制失败')
  })
}

// ==================== 事件相关 ====================
const loadEvents = async () => {
  try {
    const token = localStorage.getItem('token')
    const res = await axios.get('/api/routes/dashboard', {
      headers: { Authorization: `Bearer ${token}` },
      params: { page: 1, page_size: 200, sort_by: 'heat', order: 'desc' },
    })
    if (res.data.code === 200) {
      eventOptions.value = res.data.data.items || []
      if (selectedEventId.value) {
        selectedEvent.value = eventOptions.value.find(e => e.id === selectedEventId.value) || null
      }
    }
  } catch {}
}

const onEventChange = (id) => {
  selectedEvent.value = eventOptions.value.find(e => e.id === id) || null
  messages.value = []
  inputRef.value?.focus()
}

// ==================== 发送消息 ====================
const onKeydown = (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

const sendMessage = async () => {
  const text = inputText.value.trim()
  if (!text || loading.value) return
  if (!selectedEventId.value) {
    ElMessage.warning('请先选择一个事件')
    return
  }

  // 添加用户消息
  messages.value.push({
    id: genId(),
    role: 'user',
    content: text,
    time: formatTime(),
  })
  inputText.value = ''
  scrollToBottom()

  // 调用后端
  loading.value = true
  try {
    const token = localStorage.getItem('token')
    const res = await axios.post('/api/routes/qa', {
      event_id: selectedEventId.value,
      question: text,
    }, {
      headers: { Authorization: `Bearer ${token}` },
    })

    if (res.data.code === 200) {
      const answer = res.data.data.answer
      messages.value.push({
        id: genId(),
        role: 'assistant',
        content: answer,
        time: formatTime(),
      })
      // 写入历史
      history.value.unshift({
        question: text,
        answer,
        eventId: selectedEventId.value,
        time: new Date().toLocaleString('zh-CN'),
      })
      if (history.value.length > 30) history.value.pop()
    } else {
      messages.value.push({
        id: genId(),
        role: 'assistant',
        content: `请求失败：${res.data.message || '未知错误'}`,
        time: formatTime(),
      })
    }
  } catch (err) {
    const detail = err.response?.data?.detail
    messages.value.push({
      id: genId(),
      role: 'assistant',
      content: detail || '请求异常，请检查网络连接或后端 API 配置。',
      time: formatTime(),
    })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

const quickAsk = (question) => {
  inputText.value = question
  sendMessage()
}

// ==================== 历史与操作 ====================
const restoreHistory = (item) => {
  selectedEventId.value = item.eventId
  selectedEvent.value = eventOptions.value.find(e => e.id === item.eventId) || null
  messages.value = [
    { id: genId(), role: 'user', content: item.question, time: item.time },
    { id: genId(), role: 'assistant', content: item.answer, time: item.time },
  ]
}

const clearMessages = () => {
  messages.value = []
}

const clearHistory = () => {
  history.value = []
}

const regenerate = async (msg) => {
  // 找到该助手消息对应的用户问题
  const idx = messages.value.findIndex(m => m.id === msg.id)
  if (idx <= 0) return

  const userMsg = messages.value[idx - 1]
  if (userMsg.role !== 'user') return

  // 移除当前助手消息
  messages.value.splice(idx, 1)

  // 重新发送
  inputText.value = userMsg.content
  await sendMessage()
}

const loadMoreHistory = () => {
  // 预留：加载更早的历史（可对接后端持久化）
  ElMessage.info('暂无更多历史消息')
}

const onScroll = () => {
  // 预留：滚动到顶部时加载更多
}

// ==================== 初始化 ====================
onMounted(() => {
  loadEvents()
  inputRef.value?.focus()
})
</script>

<style scoped>
.breadcrumb { margin-bottom: 12px; }

.chat-layout { height: calc(100vh - 120px); }
.sidebar-col { display: flex; flex-direction: column; gap: 12px; }
.chat-col { display: flex; flex-direction: column; }

/* ========== 侧边栏 ========== */
.sidebar-card :deep(.el-card__header) { padding: 10px 16px; }
.sidebar-card :deep(.el-card__body) { padding: 14px 16px; }
.card-title { font-size: 14px; font-weight: 600; color: #303133; display: flex; align-items: center; gap: 5px; }

/* 事件选择下拉框 - 蓝色聚焦光晕 */
.sidebar-card :deep(.el-select .el-input__wrapper),
.sidebar-card :deep(.el-select .el-select__wrapper) {
  border-radius: 8px;
  transition: all 0.3s ease;
  box-shadow: 0 0 0 0 rgba(64, 158, 255, 0);
}
.sidebar-card :deep(.el-select .el-input.is-focus .el-input__wrapper),
.sidebar-card :deep(.el-select.is-focus .el-select__wrapper) {
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.25), 0 0 12px rgba(64, 158, 255, 0.15);
  border-color: #409eff !important;
}

.event-preview { margin-top: 14px; }
.preview-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; line-height: 1.4; }
.preview-tags { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 6px; }
.preview-summary { font-size: 12px; color: #909399; line-height: 1.5; margin: 0; }

/* 快捷问题 - pill 形状 */
.quick-questions { display: flex; flex-direction: column; gap: 6px; }
.quick-item {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 14px; border-radius: 999px;
  font-size: 13px; color: #606266;
  cursor: pointer; transition: all 0.3s ease;
  border: 1px solid #e8ecf2;
  background: #f8f9fb;
}
.quick-item:hover {
  background: linear-gradient(135deg, #4facfe, #7c6ff7);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 4px 12px rgba(79, 172, 254, 0.3);
  transform: translateX(4px);
}

/* 历史 */
.history-card { flex: 1; min-height: 0; }
.history-header { display: flex; justify-content: space-between; align-items: center; }
.history-list { max-height: 280px; overflow-y: auto; }
.history-item {
  padding: 8px 10px 8px 16px; border-radius: 6px;
  cursor: pointer; transition: all 0.25s ease;
  margin-bottom: 4px; border: 1px solid transparent;
  position: relative;
}
.history-item::before {
  content: '';
  position: absolute; left: 0; top: 50%;
  transform: translateY(-50%);
  width: 3px; height: 0; border-radius: 2px;
  background: linear-gradient(180deg, #409eff, #7c6ff7);
  transition: height 0.25s ease;
}
.history-item:hover {
  background: #f5f9ff; border-color: #d9ecff;
}
.history-item:hover::before {
  height: 70%;
}
.history-event { font-size: 11px; color: #c0c4cc; margin-bottom: 2px; }
.history-q { font-size: 12px; color: #303133; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.history-time { font-size: 10px; color: #c0c4cc; margin-top: 3px; }

/* ========== 聊天卡片 ========== */
.chat-card { display: flex; flex-direction: column; height: 100%; }
.chat-card :deep(.el-card__header) { padding: 10px 20px; }
.chat-card :deep(.el-card__body) { flex: 1; display: flex; flex-direction: column; padding: 0; overflow: hidden; }

.chat-header { display: flex; justify-content: space-between; align-items: center; }
.chat-header-left { display: flex; align-items: center; gap: 10px; }
.chat-bot-name { font-size: 14px; font-weight: 600; color: #303133; }
.chat-bot-status { font-size: 11px; color: #909399; display: flex; align-items: center; gap: 4px; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; }
.status-dot.online { background: #67c23a; }
.status-dot.busy { background: #e6a23c; animation: blink 1s infinite; }
@keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }

.chat-header-right { display: flex; align-items: center; gap: 8px; }

/* ========== 消息区 ========== */
.chat-messages {
  flex: 1; overflow-y: auto; padding: 16px 20px;
  background: #f8f9fb;
  scroll-behavior: smooth;
}

.chat-messages::-webkit-scrollbar { width: 5px; }
.chat-messages::-webkit-scrollbar-thumb { background: #dcdfe6; border-radius: 3px; }
.chat-messages::-webkit-scrollbar-thumb:hover { background: #c0c4cc; }

/* 时间分隔线 */
.time-divider { text-align: center; margin: 16px 0; position: relative; }
.time-divider::before { content: ''; position: absolute; top: 50%; left: 0; right: 0; height: 1px; background: #e4e7ed; }
.time-divider span {
  position: relative; background: #f8f9fb; padding: 0 12px;
  font-size: 11px; color: #c0c4cc;
}

/* 欢迎区 */
.welcome-section { text-align: center; padding: 60px 20px; }
.welcome-icon { margin-bottom: 16px; }
.welcome-title { font-size: 20px; font-weight: 600; color: #303133; margin: 0 0 8px; }
.welcome-desc { font-size: 13px; color: #909399; margin: 0; }

/* 消息行 */
.message-row {
  display: flex; gap: 10px; margin-bottom: 16px;
  animation: fadeInUp 0.35s cubic-bezier(0.22, 1, 0.36, 1);
}
.message-row.user { flex-direction: row-reverse; }
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

.avatar { flex-shrink: 0; }
.bot-avatar { background: linear-gradient(135deg, #409eff, #66b1ff); color: #fff; }
.user-avatar { background: linear-gradient(135deg, #67c23a, #95d475); color: #fff; }

.message-body { max-width: 72%; min-width: 60px; }

.message-bubble {
  padding: 12px 16px; border-radius: 16px;
  font-size: 14px; line-height: 1.7;
  word-break: break-word;
}

.bot-bubble {
  background: linear-gradient(135deg, #f7f8fa, #eef0f4);
  color: #303133;
  border: 1px solid #e8ebf0;
  border-top-left-radius: 4px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.user-bubble {
  background: linear-gradient(135deg, #4facfe, #00f2fe);
  color: #fff;
  border-top-right-radius: 4px;
  box-shadow: 0 4px 16px rgba(79, 172, 254, 0.3);
}

.message-meta {
  display: flex; align-items: center; gap: 6px;
  margin-top: 4px; padding: 0 4px;
}
.message-row.user .message-meta { justify-content: flex-end; }
.msg-time { font-size: 10px; color: #c0c4cc; }
.msg-action { color: #c0c4cc; cursor: pointer; transition: color 0.2s; }
.msg-action:hover { color: #409eff; }

/* 加载动画 */
.typing-bubble { display: flex; align-items: center; gap: 10px; padding: 14px 18px; }
.typing-indicator { display: flex; gap: 4px; }
.typing-indicator span {
  width: 7px; height: 7px; border-radius: 50%;
  background: #c0c4cc; animation: typingBounce 1.2s infinite;
}
.typing-indicator span:nth-child(2) { animation-delay: 0.15s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.3s; }
@keyframes typingBounce {
  0%, 60%, 100% { transform: translateY(0); background: #c0c4cc; }
  30% { transform: translateY(-6px); background: #409eff; }
}
.typing-text { font-size: 13px; color: #909399; }

/* ========== 输入区 ========== */
.chat-input-area {
  border-top: 1px solid #ebeef5;
  background: #fff; padding: 12px 20px;
}
.input-wrapper { display: flex; gap: 10px; align-items: flex-end; }
.input-wrapper :deep(.el-textarea__inner) {
  border-radius: 10px; padding: 10px 14px;
  font-size: 14px; line-height: 1.6;
  transition: all 0.3s ease;
  box-shadow: 0 0 0 0 rgba(64, 158, 255, 0);
}
.input-wrapper :deep(.el-textarea__inner:focus) {
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.2), 0 0 16px rgba(64, 158, 255, 0.12);
  border-color: #409eff !important;
}
.send-btn {
  width: 44px; height: 44px; border-radius: 10px;
  flex-shrink: 0; font-size: 18px;
}
.input-tips {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: 6px; font-size: 11px;
}
.tip-info { color: #c0c4cc; }
.tip-warn { color: #e6a23c; display: flex; align-items: center; gap: 3px; }

/* ========== 响应式 ========== */
@media (max-width: 768px) {
  .chat-layout { height: auto; min-height: calc(100vh - 120px); }
  .message-body { max-width: 85%; }
  .sidebar-col { margin-bottom: 12px; }
}
</style>
