<template>
  <Dialog :open="visible" @update:open="(val) => !val && $emit('close')">
    <DialogContent class="sm:max-w-[400px] p-0 overflow-hidden max-h-[85vh] flex flex-col">
      <DialogHeader class="px-6 pt-6">
        <DialogTitle>{{ dialogTitle }}</DialogTitle>
        <DialogDescription class="hidden">
          {{ dialogDescription }}
        </DialogDescription>
      </DialogHeader>
      
      <div class="px-6 py-4 overflow-y-auto">
        <div v-if="isOAuthMode" class="grid gap-4">
          <div class="text-sm text-muted-foreground bg-muted/50 p-4 rounded-md leading-6">
            当前实例已启用 {{ oauthProviderName || 'OAuth2' }} 登录。点击下方按钮后会跳转到统一身份认证页面。
          </div>

          <div v-if="errorMessage" class="text-sm font-medium text-destructive bg-destructive/10 p-3 rounded-md">
            {{ errorMessage }}
          </div>

          <Button type="button" class="w-full" :disabled="isLoading || !oauthEnabled" @click="handleOAuthLogin">
            <Loader v-if="isLoading" class="mr-2 h-4 w-4 animate-spin" />
            {{ isLoading ? '跳转中...' : (oauthEnabled ? `使用${oauthProviderName || 'OAuth2'}登录` : 'OAuth2 未完成配置') }}
          </Button>
        </div>

        <form v-else-if="mode === 'login'" @submit.prevent="handleLogin" class="grid gap-4">
          <div class="grid gap-2">
            <Label for="username">用户名</Label>
            <Input 
              id="username"
              v-model="loginForm.username"
              placeholder="请输入用户名或邮箱"
              required
              :disabled="isLoading"
            />
          </div>

          <div class="grid gap-2">
            <Label for="password">密码</Label>
            <Input 
              type="password" 
              id="password"
              v-model="loginForm.password"
              placeholder="请输入密码"
              required
              :disabled="isLoading"
            />
          </div>

          <div v-if="errorMessage" class="text-sm font-medium text-destructive bg-destructive/10 p-3 rounded-md">
            {{ errorMessage }}
          </div>

          <Button type="submit" class="w-full" :disabled="isLoading || !loginForm.username || !loginForm.password">
            <Loader v-if="isLoading" class="mr-2 h-4 w-4 animate-spin" />
            {{ isLoading ? '登录中...' : '登录' }}
          </Button>
        </form>

        <form v-else @submit.prevent="handleRegister" class="grid gap-4">
          <div class="grid gap-2">
            <Label for="reg_username">用户名</Label>
            <Input 
              id="reg_username"
              v-model="registerForm.username"
              placeholder="请输入用户名"
              required
              :disabled="isLoading"
            />
          </div>

          <div class="grid gap-2">
            <Label for="reg_email">
              邮箱 <span class="text-destructive">*</span>
            </Label>
            <Input
              id="reg_email"
              v-model="registerForm.email"
              type="email"
              placeholder="请输入邮箱地址"
              required
              :disabled="isLoading"
            />
          </div>

          <div class="grid gap-2">
            <Label for="reg_verification_code">邮箱验证码</Label>
            <div class="flex gap-2">
              <Input
                id="reg_verification_code"
                v-model="registerForm.verificationCode"
                inputmode="numeric"
                maxlength="6"
                placeholder="请输入6位验证码"
                required
                :disabled="isLoading"
              />
              <Button
                type="button"
                variant="outline"
                class="shrink-0"
                :disabled="isLoading || isSendingCode || !registerForm.email || sendCodeCountdown > 0"
                @click="handleSendVerificationCode"
              >
                <Loader v-if="isSendingCode" class="mr-2 h-4 w-4 animate-spin" />
                {{ sendCodeButtonText }}
              </Button>
            </div>
            <p class="text-xs text-muted-foreground">验证码 5 分钟内有效，30 秒内只能发送一次。</p>
          </div>

          <div class="grid gap-3">
            <div class="grid gap-2">
              <Label for="reg_password">密码</Label>
              <Input 
                type="password" 
                id="reg_password"
                v-model="registerForm.password"
                placeholder="请输入密码"
                required
                :disabled="isLoading"
              />
            </div>

            <div class="grid gap-2">
              <Label for="reg_confirm">确认密码</Label>
              <Input 
                type="password" 
                id="reg_confirm"
                v-model="registerForm.confirmPassword"
                placeholder="请再次输入密码"
                required
                :disabled="isLoading"
              />
            </div>
          </div>

          <div v-if="successMessage" class="text-sm font-medium text-emerald-700 bg-emerald-50 p-3 rounded-md">
            {{ successMessage }}
          </div>

          <div v-if="errorMessage" class="text-sm font-medium text-destructive bg-destructive/10 p-3 rounded-md">
            {{ errorMessage }}
          </div>

          <Button
            type="submit"
            class="w-full"
            :disabled="isLoading || !registerForm.username || !registerForm.email || !registerForm.verificationCode || !registerForm.password || !registerForm.confirmPassword"
          >
            <Loader v-if="isLoading" class="mr-2 h-4 w-4 animate-spin" />
            {{ isLoading ? '注册中...' : '注册并登录' }}
          </Button>
        </form>
      </div>

      <div v-if="!isOAuthMode" class="bg-muted/50 p-4 flex justify-center border-t">
        <div class="text-sm text-muted-foreground">
          <span v-if="mode === 'login'">
            <span v-if="allowRegistration">
              没有账号？<a href="#" class="text-primary font-medium hover:underline" @click.prevent="switchToRegister">去注册</a>
            </span>
          </span>
          <span v-else>
            已有账号？<a href="#" class="text-primary font-medium hover:underline" @click.prevent="switchToLogin">去登录</a>
          </span>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { computed, ref, reactive, onBeforeUnmount, onMounted } from 'vue'
import { buildOAuthLoginUrl, loginAPI, registerAPI, sendRegisterVerificationCodeAPI } from '../utils/auth.js'
import { systemAPI } from '../api/system.js'
import { Loader } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { 
  Dialog, 
  DialogContent, 
  DialogHeader, 
  DialogTitle,
  DialogDescription
} from '@/components/ui/dialog'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  required: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close', 'login-success'])

const isLoading = ref(false)
const isSendingCode = ref(false)
const sendCodeCountdown = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const mode = ref('login')
const allowRegistration = ref(true)
const authMode = ref('password')
const authProviders = ref([])
const oauthProviderName = ref('OAuth2')
const oauthEnabled = ref(false)
let sendCodeTimer = null
const defaultOauthProviderId = computed(() => authProviders.value.find((provider) => provider.type === 'oidc')?.id || null)
const hasLocalProvider = computed(() => authProviders.value.some((provider) => provider.type === 'local'))
const isOAuthMode = computed(() => !hasLocalProvider.value && oauthEnabled.value)
const dialogTitle = computed(() => {
  if (isOAuthMode.value) return '统一登录'
  return mode.value === 'login' ? '用户登录' : '创建账号'
})
const dialogDescription = computed(() => {
  if (isOAuthMode.value) return '跳转到身份提供商完成认证'
  return mode.value === 'login' ? '登录您的账户以继续' : '填写邮箱验证码并设置密码'
})
const sendCodeButtonText = computed(() => {
  if (isSendingCode.value) return '发送中...'
  if (sendCodeCountdown.value > 0) return `${sendCodeCountdown.value}s 后重发`
  return '发送验证码'
})

onMounted(async () => {
  try {
    const res = await systemAPI.getSystemInfo()
    allowRegistration.value = res.allow_registration
    authMode.value = res.auth_mode || 'password'
    authProviders.value = Array.isArray(res.auth_providers) ? res.auth_providers : []
    oauthProviderName.value = res.oauth_provider_name || 'OAuth2'
    oauthEnabled.value = res.oauth_enabled === true || authProviders.value.some((provider) => provider.type === 'oidc')

  } catch (e) {
    console.error('Failed to get system info', e)
  }
})

const loginForm = reactive({
  username: '',
  password: ''
})
const registerForm = reactive({
  username: '',
  email: '',
  verificationCode: '',
  phonenum: '',
  password: '',
  confirmPassword: ''
})

const clearSendCodeTimer = () => {
  if (sendCodeTimer) {
    clearInterval(sendCodeTimer)
    sendCodeTimer = null
  }
}

const startSendCodeCountdown = (seconds = 30) => {
  clearSendCodeTimer()
  sendCodeCountdown.value = seconds
  sendCodeTimer = window.setInterval(() => {
    if (sendCodeCountdown.value <= 1) {
      clearSendCodeTimer()
      sendCodeCountdown.value = 0
      return
    }
    sendCodeCountdown.value -= 1
  }, 1000)
}

onBeforeUnmount(() => {
  clearSendCodeTimer()
})

const handleLogin = async () => {
  if (isOAuthMode.value) {
    handleOAuthLogin()
    return
  }
  if (!loginForm.username || !loginForm.password) {
    errorMessage.value = '请输入用户名和密码'
    return
  }
  
  isLoading.value = true
  errorMessage.value = ''
  
  try {
    const result = await loginAPI(loginForm.username, loginForm.password)
    
    if (result.success) {
      // 登录成功，通知父组件
      emit('login-success', result.data)
      
      // 重置表单
      loginForm.username = ''
      loginForm.password = ''
      
      // 关闭模态框
      emit('close')
    } else {
      errorMessage.value = result.message || '登录失败'
    }
  } catch (error) {
    console.error('登录失败:', error)
    errorMessage.value = '登录失败，请重试'
  } finally {
    isLoading.value = false
  }
}

const handleSendVerificationCode = async () => {
  if (isOAuthMode.value) {
    errorMessage.value = '当前实例已启用 OAuth2 登录，不支持本地注册'
    successMessage.value = ''
    return
  }
  if (!allowRegistration.value) {
    errorMessage.value = '当前未开放注册'
    successMessage.value = ''
    return
  }
  if (!registerForm.email) {
    errorMessage.value = '请输入邮箱地址'
    successMessage.value = ''
    return
  }

  isSendingCode.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const result = await sendRegisterVerificationCodeAPI(registerForm.email)
    if (result.success) {
      successMessage.value = '验证码已发送，请查收邮箱'
      startSendCodeCountdown(result.data?.retry_after || 30)
    } else {
      errorMessage.value = result.message || '验证码发送失败'
    }
  } catch (error) {
    console.error('发送验证码失败:', error)
    errorMessage.value = '验证码发送失败，请重试'
  } finally {
    isSendingCode.value = false
  }
}

const handleRegister = async () => {
  if (isOAuthMode.value) {
    errorMessage.value = '当前实例已启用 OAuth2 登录，不支持本地注册'
    successMessage.value = ''
    return
  }
  if (!registerForm.username || !registerForm.email || !registerForm.verificationCode || !registerForm.password || !registerForm.confirmPassword) {
    errorMessage.value = '请填写完整注册信息'
    successMessage.value = ''
    return
  }
  if (registerForm.password !== registerForm.confirmPassword) {
    errorMessage.value = '两次输入的密码不一致'
    successMessage.value = ''
    return
  }
  isLoading.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const result = await registerAPI(
      registerForm.username,
      registerForm.password,
      registerForm.email,
      registerForm.phonenum,
      registerForm.verificationCode
    )
    if (result.success) {
      emit('login-success', result.data)
      registerForm.username = ''
      registerForm.email = ''
      registerForm.verificationCode = ''
      registerForm.phonenum = ''
      registerForm.password = ''
      registerForm.confirmPassword = ''
      successMessage.value = ''
      emit('close')
    } else {
      errorMessage.value = result.message || '注册失败'
    }
  } catch (error) {
    console.error('注册失败:', error)
    errorMessage.value = '注册失败，请重试'
  } finally {
    isLoading.value = false
  }
}

const handleOAuthLogin = () => {
  if (!oauthEnabled.value) {
    errorMessage.value = 'OAuth2 登录尚未配置完成，请联系管理员'
    return
  }
  if (!defaultOauthProviderId.value) {
    errorMessage.value = '未找到可用的 OAuth Provider'
    return
  }
  errorMessage.value = ''
  isLoading.value = true
  try {
    window.location.href = buildOAuthLoginUrl(defaultOauthProviderId.value)
  } catch (error) {
    console.error('OAuth login redirect failed:', error)
    errorMessage.value = '跳转登录失败，请重试'
    isLoading.value = false
  }
}

const switchToRegister = () => {
  if (!allowRegistration.value) return
  errorMessage.value = ''
  successMessage.value = ''
  mode.value = 'register'
}
const switchToLogin = () => {
  errorMessage.value = ''
  successMessage.value = ''
  mode.value = 'login'
}

const handleOverlayClick = () => {
  if (!props.required) {
    emit('close')
  }
}
</script>
