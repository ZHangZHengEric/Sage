<template>
  <div v-if="visible" class="fixed inset-0 z-[10000] flex items-center justify-center bg-black/70 backdrop-blur-sm animate-in fade-in duration-200" @click="handleOverlayClick">
    <Card class="w-[90%] max-w-[400px] shadow-2xl animate-in zoom-in-95 duration-200" @click.stop>
      <CardHeader>
        <div class="flex justify-between items-center">
          <CardTitle>{{ mode === 'login' ? '用户登录' : '用户注册' }}</CardTitle>
          <Button 
            v-if="!required" 
            variant="ghost" 
            size="icon" 
            class="h-8 w-8 rounded-full" 
            @click="$emit('close')"
          >
            <span class="text-lg leading-none">&times;</span>
          </Button>
        </div>
      </CardHeader>
      
      <CardContent>
        <form v-if="mode === 'login'" @submit.prevent="handleLogin" class="grid gap-4">
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
            <span v-if="isLoading" class="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
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

          <div v-if="errorMessage" class="text-sm font-medium text-destructive bg-destructive/10 p-3 rounded-md">
            {{ errorMessage }}
          </div>

          <Button type="submit" class="w-full" :disabled="isLoading || !registerForm.username || !registerForm.password || !registerForm.confirmPassword">
            <span v-if="isLoading" class="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
            {{ isLoading ? '注册中...' : '注册并登录' }}
          </Button>
        </form>
      </CardContent>
      <CardFooter class="flex justify-center bg-muted/50 p-4 rounded-b-lg">
        <div class="text-sm text-muted-foreground">
          <span v-if="mode === 'login'">
            没有账号？<a href="#" class="text-primary font-medium hover:underline" @click.prevent="switchToRegister">去注册</a>
          </span>
          <span v-else>
            已有账号？<a href="#" class="text-primary font-medium hover:underline" @click.prevent="switchToLogin">去登录</a>
          </span>
        </div>
      </CardFooter>
    </Card>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { loginAPI, registerAPI } from '../utils/auth.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui/card'

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
const errorMessage = ref('')
const mode = ref('login')

const loginForm = reactive({
  username: '',
  password: ''
})
const registerForm = reactive({
  username: '',
  email: '',
  phonenum: '',
  password: '',
  confirmPassword: ''
})

const handleLogin = async () => {
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

const handleRegister = async () => {
  if (!registerForm.username || !registerForm.password || !registerForm.confirmPassword) {
    errorMessage.value = '请填写完整注册信息'
    return
  }
  if (registerForm.password !== registerForm.confirmPassword) {
    errorMessage.value = '两次输入的密码不一致'
    return
  }
  isLoading.value = true
  errorMessage.value = ''
  try {
    const result = await registerAPI(registerForm.username, registerForm.password, registerForm.email, registerForm.phonenum)
    if (result.success) {
      emit('login-success', result.data)
      registerForm.username = ''
      registerForm.email = ''
      registerForm.phonenum = ''
      registerForm.password = ''
      registerForm.confirmPassword = ''
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

const switchToRegister = () => {
  errorMessage.value = ''
  mode.value = 'register'
}
const switchToLogin = () => {
  errorMessage.value = ''
  mode.value = 'login'
}

const handleOverlayClick = () => {
  if (!props.required) {
    emit('close')
  }
}
</script>
