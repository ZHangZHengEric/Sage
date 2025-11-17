<template>
  <div v-if="visible" class="login-modal-overlay" @click="handleOverlayClick">
    <div class="login-modal" @click.stop>
      <div class="login-header">
        <h2>{{ mode === 'login' ? '用户登录' : '用户注册' }}</h2>
        <button class="close-btn" @click="$emit('close')" v-if="!required">×</button>
      </div>
      
      <form v-if="mode === 'login'" @submit.prevent="handleLogin" class="login-form">
        <div class="form-group">
          <label for="username">用户名</label>
          <input 
            type="text" 
            id="username"
            v-model="loginForm.username"
            placeholder="请输入用户名或邮箱"
            required
            :disabled="isLoading"
          />
        </div>

        <div class="form-group">
          <label for="password">密码</label>
          <input 
            type="password" 
            id="password"
            v-model="loginForm.password"
            placeholder="请输入密码"
            required
            :disabled="isLoading"
          />
        </div>

        <div v-if="errorMessage" class="error-message">
          {{ errorMessage }}
        </div>

        <button 
          type="submit" 
          class="login-btn"
          :disabled="isLoading || !loginForm.username || !loginForm.password"
        >
          <span v-if="isLoading" class="loading-spinner"></span>
          {{ isLoading ? '登录中...' : '登录' }}
        </button>
        <div class="login-tips" style="margin-top: 12px;">
          <p>没有账号？<a href="#" @click.prevent="switchToRegister">去注册</a></p>
        </div>
      </form>

      <form v-else @submit.prevent="handleRegister" class="login-form">
        <div class="form-group">
          <label for="reg_username">用户名</label>
          <input 
            type="text" 
            id="reg_username"
            v-model="registerForm.username"
            placeholder="请输入用户名"
            required
            :disabled="isLoading"
          />
        </div>

        <div class="form-group">
          <label for="reg_email">邮箱（可选）</label>
          <input 
            type="email" 
            id="reg_email"
            v-model="registerForm.email"
            placeholder="请输入邮箱"
            :disabled="isLoading"
          />
        </div>

        <div class="form-group">
          <label for="reg_phonenum">手机号（可选）</label>
          <input 
            type="text" 
            id="reg_phonenum"
            v-model="registerForm.phonenum"
            placeholder="请输入手机号"
            :disabled="isLoading"
          />
        </div>

        <div class="form-group">
          <label for="reg_password">密码</label>
          <input 
            type="password" 
            id="reg_password"
            v-model="registerForm.password"
            placeholder="请输入密码"
            required
            :disabled="isLoading"
          />
        </div>

        <div class="form-group">
          <label for="reg_confirm">确认密码</label>
          <input 
            type="password" 
            id="reg_confirm"
            v-model="registerForm.confirmPassword"
            placeholder="请再次输入密码"
            required
            :disabled="isLoading"
          />
        </div>

        <div v-if="errorMessage" class="error-message">
          {{ errorMessage }}
        </div>

        <button 
          type="submit" 
          class="login-btn"
          :disabled="isLoading || !registerForm.username || !registerForm.password || !registerForm.confirmPassword"
        >
          <span v-if="isLoading" class="loading-spinner"></span>
          {{ isLoading ? '注册中...' : '注册并登录' }}
        </button>
        <div class="login-tips" style="margin-top: 12px;">
          <p>已有账号？<a href="#" @click.prevent="switchToLogin">去登录</a></p>
        </div>
      </form>
    </div>
  </div>
</template>

<script>
import { ref, reactive } from 'vue'
import { loginAPI, registerAPI } from '../utils/auth.js'

export default {
  name: 'LoginModal',
  props: {
    visible: {
      type: Boolean,
      default: false
    },
    required: {
      type: Boolean,
      default: false
    }
  },
  emits: ['close', 'login-success'],
  setup(props, { emit }) {
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
    
    return {
      isLoading,
      errorMessage,
      mode,
      loginForm,
      registerForm,
      handleLogin,
      handleRegister,
      switchToRegister,
      switchToLogin,
      handleOverlayClick
    }
  }
}
</script>

<style scoped>
.login-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.login-modal {
  background: white;
  border-radius: 12px;
  padding: 2rem;
  width: 90%;
  max-width: 400px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  animation: modalSlideIn 0.3s ease-out;
}

@keyframes modalSlideIn {
  from {
    opacity: 0;
    transform: translateY(-50px) scale(0.95);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.login-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
  border-bottom: 1px solid #eee;
  padding-bottom: 1rem;
}

.login-header h2 {
  color: #2c3e50;
  margin: 0;
  font-size: 1.5rem;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: #666;
  cursor: pointer;
  padding: 0;
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  transition: all 0.2s ease;
}

.close-btn:hover {
  background-color: #f0f0f0;
  color: #333;
}

.login-form {
  margin-bottom: 1.5rem;
}

.form-group {
  margin-bottom: 1.5rem;
}

.form-group label {
  display: block;
  margin-bottom: 0.5rem;
  color: #555;
  font-weight: 500;
}

.form-group input {
  width: 100%;
  padding: 0.75rem;
  border: 2px solid #e1e5e9;
  border-radius: 8px;
  font-size: 1rem;
  transition: border-color 0.3s ease;
  box-sizing: border-box;
}

.form-group input:focus {
  outline: none;
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

.form-group input:disabled {
  background-color: #f8f9fa;
  color: #6c757d;
  cursor: not-allowed;
}

.error-message {
  background-color: #fee;
  color: #c53030;
  padding: 0.75rem;
  border-radius: 6px;
  margin-bottom: 1rem;
  border: 1px solid #feb2b2;
  font-size: 0.9rem;
}

.login-btn {
  width: 100%;
  padding: 0.75rem;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}

.login-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
}

.login-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.loading-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top: 2px solid white;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.login-tips {
  background-color: #f8f9fa;
  padding: 1rem;
  border-radius: 8px;
  border-left: 4px solid #667eea;
}

.login-tips p {
  margin: 0.25rem 0;
  font-size: 0.9rem;
  color: #666;
}

.login-tips p:first-child {
  font-weight: 600;
  color: #333;
  margin-bottom: 0.5rem;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
</style>