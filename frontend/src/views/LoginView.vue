<template>
  <div class="login-page">
    <!-- 背景装饰粒子 -->
    <div class="bg-decoration">
      <div class="circle c1"></div>
      <div class="circle c2"></div>
      <div class="circle c3"></div>
    </div>

    <div class="login-box">
      <!-- 系统Logo与标题 -->
      <div class="login-header">
        <div class="logo-wrapper">
          <img src="/logo.jpg" alt="智舆Logo" class="login-logo-img" />
        </div>
        <h2 class="login-title">智舆 — 网络舆情智能分析平台</h2>
        <p class="login-subtitle">舆情监控 · 智能分析 · 风险预警</p>
      </div>

      <!-- 登录表单 -->
      <el-form
        v-if="!isRegister"
        ref="loginFormRef"
        :model="loginForm"
        :rules="loginRules"
        class="login-form"
        size="large"
        @keyup.enter="handleLogin"
      >
        <!-- 用户名 -->
        <el-form-item prop="username">
          <el-input
            v-model="loginForm.username"
            placeholder="请输入用户名"
            prefix-icon="User"
            clearable
            maxlength="32"
          />
        </el-form-item>

        <!-- 密码 -->
        <el-form-item prop="password">
          <el-input
            v-model="loginForm.password"
            type="password"
            placeholder="请输入密码"
            prefix-icon="Lock"
            show-password
            maxlength="64"
          />
        </el-form-item>

        <!-- 记住密码 + 忘记密码（预留） -->
        <el-form-item class="form-extra">
          <el-checkbox v-model="rememberMe" label="记住密码" />
          <el-link type="primary" :underline="false">忘记密码？</el-link>
        </el-form-item>

        <!-- 登录按钮 -->
        <el-form-item>
          <el-button
            type="primary"
            size="large"
            class="login-btn"
            :loading="loading"
            @click="handleLogin"
          >
            {{ loading ? '登录中...' : '登 录' }}
          </el-button>
        </el-form-item>
      </el-form>

      <!-- 注册表单 -->
      <el-form
        v-else
        ref="registerFormRef"
        :model="registerForm"
        :rules="registerRules"
        class="login-form"
        size="large"
        @keyup.enter="handleRegister"
      >
        <!-- 用户名 -->
        <el-form-item prop="username">
          <el-input
            v-model="registerForm.username"
            placeholder="请输入用户名"
            prefix-icon="User"
            clearable
            maxlength="32"
          />
        </el-form-item>

        <!-- 密码 -->
        <el-form-item prop="password">
          <el-input
            v-model="registerForm.password"
            type="password"
            placeholder="请输入密码"
            prefix-icon="Lock"
            show-password
            maxlength="64"
          />
        </el-form-item>

        <!-- 确认密码 -->
        <el-form-item prop="confirmPassword">
          <el-input
            v-model="registerForm.confirmPassword"
            type="password"
            placeholder="请再次输入密码"
            prefix-icon="Check"
            show-password
            maxlength="64"
          />
        </el-form-item>

        <!-- 注册按钮 -->
        <el-form-item>
          <el-button
            type="primary"
            size="large"
            class="login-btn"
            :loading="loading"
            @click="handleRegister"
          >
            {{ loading ? '注册中...' : '注 册' }}
          </el-button>
        </el-form-item>
      </el-form>

      <!-- 切换登录/注册 -->
      <div class="toggle-mode">
        <span>{{ isRegister ? '已有账号？' : '还没有账号？' }}</span>
        <el-link type="primary" :underline="false" @click="toggleMode">
          {{ isRegister ? '立即登录' : '立即注册' }}
        </el-link>
      </div>

      <!-- 底部提示 -->
      <div class="login-footer">
        <el-text v-if="!isRegister" type="info" size="small">提示：默认账号 admin / admin123</el-text>
      </div>
    </div>

    <!-- 底部版权 -->
    <div class="copyright">
      <span>© 2026 智舆 — 网络舆情智能分析平台 · Powered by FastAPI + Vue3</span>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import md5 from 'js-md5'

const router = useRouter()

// ==================== 登录/注册切换 ====================
const isRegister = ref(false)

const toggleMode = () => {
  isRegister.value = !isRegister.value
  // 切换时重置表单和校验状态
  nextTick(() => {
    loginFormRef.value?.resetFields?.()
    registerFormRef.value?.resetFields?.()
  })
}

// ==================== 登录表单 ====================
const loginFormRef = ref(null)
const loading = ref(false)
const rememberMe = ref(false)

const loginForm = reactive({
  username: '',
  password: '',
})

// ==================== 注册表单 ====================
const registerFormRef = ref(null)

const registerForm = reactive({
  username: '',
  password: '',
  confirmPassword: '',
})

// ==================== 表单校验规则 ====================
// 用户名：必填，3-32位，只允许字母/数字/下划线
const validateUsername = (rule, value, callback) => {
  if (!value) {
    callback(new Error('请输入用户名'))
  } else if (value.length < 3) {
    callback(new Error('用户名至少3个字符'))
  } else if (value.length > 32) {
    callback(new Error('用户名最多32个字符'))
  } else if (!/^[a-zA-Z0-9_\u4e00-\u9fa5]+$/.test(value)) {
    callback(new Error('用户名只能包含字母、数字、下划线或中文'))
  } else {
    callback()
  }
}

// 密码：必填，6-64位
const validatePassword = (rule, value, callback) => {
  if (!value) {
    callback(new Error('请输入密码'))
  } else if (value.length < 6) {
    callback(new Error('密码至少6个字符'))
  } else if (value.length > 64) {
    callback(new Error('密码最多64个字符'))
  } else {
    callback()
  }
}

const loginRules = {
  username: [{ required: true, validator: validateUsername, trigger: 'blur' }],
  password: [{ required: true, validator: validatePassword, trigger: 'blur' }],
}

// 注册表单校验
const validateConfirmPassword = (rule, value, callback) => {
  if (!value) {
    callback(new Error('请再次输入密码'))
  } else if (value !== registerForm.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const registerRules = {
  username: [{ required: true, validator: validateUsername, trigger: 'blur' }],
  password: [{ required: true, validator: validatePassword, trigger: 'blur' }],
  confirmPassword: [
    { required: true, validator: validateConfirmPassword, trigger: 'blur' },
  ],
}

// ==================== 登录逻辑 ====================
const handleLogin = async () => {
  // 1. 表单校验
  try {
    await loginFormRef.value.validate()
  } catch {
    ElMessage.warning('请正确填写登录信息')
    return
  }

  // 2. 防止重复提交
  if (loading.value) return
  loading.value = true

  try {
    // 3. 前端 MD5 加密密码后传输（与后端 pwd_md5=true 模式对接）
    const passwordMd5 = md5(loginForm.password)

    // 4. 调用后端登录接口
    const res = await axios.post('/api/routes/login', null, {
      params: {
        username: loginForm.username,
        password: passwordMd5,
        pwd_md5: true,
      },
    })

    // 5. 处理响应
    if (res.data.code === 200 && res.data.data) {
      const { access_token, user } = res.data.data

      // 存储 Token 和用户信息到 localStorage
      localStorage.setItem('token', access_token)
      localStorage.setItem('user', JSON.stringify(user))

      // 记住密码：将用户名存到 localStorage
      if (rememberMe.value) {
        localStorage.setItem('remembered_user', loginForm.username)
      } else {
        localStorage.removeItem('remembered_user')
      }

      ElMessage.success(`欢迎回来，${user.username}`)
      router.push('/dashboard')
    } else {
      ElMessage.error(res.data.message || '登录失败，请检查账号密码')
    }
  } catch (err) {
    // 处理 HTTP 错误
    const detail = err.response?.data?.detail
    if (detail) {
      ElMessage.error(detail)
    } else if (!err.response) {
      ElMessage.error('网络连接失败，请检查后端服务是否启动')
    } else {
      ElMessage.error('登录失败，请稍后重试')
    }
  } finally {
    loading.value = false
  }
}

// ==================== 注册逻辑 ====================
const handleRegister = async () => {
  try {
    await registerFormRef.value.validate()
  } catch {
    ElMessage.warning('请正确填写注册信息')
    return
  }

  if (loading.value) return
  loading.value = true

  try {
    // 前端 MD5 加密后传输，与登录逻辑保持一致
    const passwordMd5 = md5(registerForm.password)

    const res = await axios.post('/api/auth/register', {
      username: registerForm.username,
      password: passwordMd5,
      focus_platforms: [],
      focus_keywords: [],
    })

    if (res.data.code === 200) {
      ElMessage.success('注册成功，请登录')
      // 预填用户名并切回登录
      loginForm.username = registerForm.username
      isRegister.value = false
      registerForm.password = ''
      registerForm.confirmPassword = ''
    } else {
      ElMessage.error(res.data.message || '注册失败')
    }
  } catch (err) {
    const detail = err.response?.data?.detail
    if (detail) {
      ElMessage.error(detail)
    } else if (!err.response) {
      ElMessage.error('网络连接失败，请检查后端服务是否启动')
    } else {
      ElMessage.error('注册失败，请稍后重试')
    }
  } finally {
    loading.value = false
  }
}

// ==================== 初始化 ====================
onMounted(() => {
  // 如果已登录，直接跳转首页
  const token = localStorage.getItem('token')
  if (token) {
    router.replace('/dashboard')
    return
  }

  // 回填记住的用户名
  const remembered = localStorage.getItem('remembered_user')
  if (remembered) {
    loginForm.username = remembered
    rememberMe.value = true
  }
})
</script>

<style scoped>
/* ========== 页面容器 ========== */
.login-page {
  height: 100vh;
  width: 100vw;
  background: linear-gradient(160deg, #0a0e27 0%, #0d1b3e 30%, #0f1f5c 60%, #0b1a3d 85%, #060d1f 100%);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  font-family: 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Arial, sans-serif;
}

/* ========== 背景装饰 ========== */
.bg-decoration {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  overflow: hidden;
}

/* 光晕效果 */
.bg-decoration::before {
  content: '';
  position: absolute;
  top: -20%;
  right: -10%;
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, rgba(64, 120, 255, 0.12) 0%, transparent 70%);
  border-radius: 50%;
  animation: glowPulse 6s ease-in-out infinite;
}

.bg-decoration::after {
  content: '';
  position: absolute;
  bottom: -15%;
  left: -5%;
  width: 500px;
  height: 500px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.10) 0%, transparent 70%);
  border-radius: 50%;
  animation: glowPulse 8s ease-in-out infinite reverse;
}

.circle {
  position: absolute;
  border-radius: 50%;
  background: #409eff;
}

.c1 {
  width: 500px;
  height: 500px;
  top: -150px;
  right: -100px;
  opacity: 0.06;
  animation: float 8s ease-in-out infinite;
  box-shadow: 0 0 80px 40px rgba(64, 158, 255, 0.04);
}

.c2 {
  width: 300px;
  height: 300px;
  bottom: -80px;
  left: -60px;
  opacity: 0.05;
  animation: float 6s ease-in-out infinite reverse;
  box-shadow: 0 0 60px 30px rgba(99, 102, 241, 0.04);
}

.c3 {
  width: 200px;
  height: 200px;
  top: 40%;
  left: 15%;
  opacity: 0.04;
  animation: float 10s ease-in-out infinite;
  box-shadow: 0 0 40px 20px rgba(64, 158, 255, 0.03);
}

@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-30px); }
}

@keyframes glowPulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.15); opacity: 0.7; }
}

/* ========== 登录卡片 ========== */
.login-box {
  width: 420px;
  background: rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-radius: 20px;
  padding: 44px 40px 36px;
  box-shadow:
    0 24px 64px rgba(0, 0, 0, 0.35),
    0 0 0 1px rgba(255, 255, 255, 0.12),
    inset 0 0.5px 0 0 rgba(255, 255, 255, 0.15);
  z-index: 1;
  animation: slideUp 0.6s cubic-bezier(0.16, 1, 0.3, 1);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(40px) scale(0.97);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

/* ========== 头部区域 ========== */
.login-header {
  text-align: center;
  margin-bottom: 38px;
}

.logo-wrapper {
  width: 68px;
  height: 68px;
  margin: 0 auto 18px;
  background: linear-gradient(135deg, rgba(64, 158, 255, 0.2), rgba(99, 102, 241, 0.15));
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8px 32px rgba(64, 158, 255, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
.login-logo-img {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  object-fit: cover;
}

.login-title {
  font-size: 22px;
  font-weight: 700;
  color: #e8ecf4;
  margin: 0 0 10px;
  letter-spacing: 2px;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.login-subtitle {
  font-size: 13px;
  color: rgba(160, 170, 200, 0.8);
  letter-spacing: 4px;
  margin: 0;
  animation: fadeInUp 1s ease-out 0.3s both;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ========== 表单区域 ========== */
.login-form {
  margin-top: 8px;
}

.login-form :deep(.el-input__wrapper) {
  border-radius: 10px;
  padding: 4px 14px;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.12) inset;
  background: rgba(255, 255, 255, 0.06);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.login-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.2) inset;
  background: rgba(255, 255, 255, 0.08);
}

.login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow:
    0 0 0 1px rgba(99, 140, 255, 0.6) inset,
    0 0 16px rgba(64, 158, 255, 0.25),
    0 0 4px rgba(64, 158, 255, 0.15);
  background: rgba(255, 255, 255, 0.1);
}

.login-form :deep(.el-input__inner) {
  color: #d0d8e8;
}

.login-form :deep(.el-input__inner::placeholder) {
  color: rgba(160, 170, 200, 0.5);
}

.login-form :deep(.el-input__prefix) {
  color: rgba(160, 170, 200, 0.6);
}

.login-form :deep(.el-form-item__error) {
  color: #f56c6c;
}

.form-extra {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 22px;
}

.form-extra :deep(.el-form-item__content) {
  justify-content: space-between;
}

.form-extra :deep(.el-checkbox__label) {
  color: rgba(160, 170, 200, 0.7);
  font-size: 13px;
}

.form-extra :deep(.el-link) {
  color: rgba(144, 180, 255, 0.9);
  font-size: 13px;
}

/* ========== 登录按钮 ========== */
.login-btn {
  width: 100%;
  height: 46px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 8px;
  border-radius: 10px;
  background: linear-gradient(135deg, #409eff, #6366f1);
  border: none;
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.2);
}

.login-btn:hover {
  background: linear-gradient(135deg, #66b1ff, #818cf8);
  transform: translateY(-2px);
  box-shadow: 0 8px 28px rgba(64, 158, 255, 0.35), 0 2px 8px rgba(99, 102, 241, 0.2);
}

.login-btn:active {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.2);
}

/* ========== 底部 ========== */
.login-footer {
  text-align: center;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.login-footer :deep(.el-text) {
  color: rgba(160, 170, 200, 0.5);
  font-size: 12px;
}

/* ========== 切换登录/注册 ========== */
.toggle-mode {
  text-align: center;
  margin-top: 18px;
  font-size: 13px;
  color: rgba(160, 170, 200, 0.6);
}

.toggle-mode span {
  margin-right: 4px;
}

.toggle-mode :deep(.el-link) {
  color: rgba(144, 180, 255, 0.9);
  font-size: 13px;
  font-weight: 500;
}

.toggle-mode :deep(.el-link:hover) {
  color: #a0c4ff;
}

.copyright {
  position: absolute;
  bottom: 20px;
  color: rgba(255, 255, 255, 0.2);
  font-size: 12px;
  z-index: 1;
  letter-spacing: 0.5px;
}

/* ========== 响应式 ========== */
@media (max-width: 480px) {
  .login-box {
    width: 90%;
    padding: 32px 24px 28px;
  }

  .login-title {
    font-size: 18px;
  }

  .circle {
    display: none;
  }
}
</style>
