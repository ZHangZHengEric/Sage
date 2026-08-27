<template>
  <div class="relative min-h-screen grid lg:grid-cols-2 bg-background">
    <div class="absolute right-4 top-4 z-30 lg:right-6 lg:top-6">
      <button class="rounded-full border border-border/60 bg-background/90 px-3 py-1.5 text-xs text-muted-foreground backdrop-blur hover:bg-accent transition-colors" @click="toggleLanguage">
        {{ isZhCN ? t('sidebar.langToggleZh') : t('sidebar.langToggleEn') }}
      </button>
    </div>

    <AnimatedCharactersStage :is-typing="isTyping" :password-length="password.length" :show-password="showPassword" />

    <div :class="panelClass">
      <div class="w-full max-w-[420px]">
        <div :class="mobileLogoClass">
          <div class="size-8 rounded-lg bg-primary/10 flex items-center justify-center p-1">
            <img :src="logoUrl" :alt="t('auth.logoAlt')" class="size-full object-contain" />
          </div>
          <span>Sage</span>
        </div>

        <div :class="headerClass">
          <h1 :class="headlineClass">{{ headline }}</h1>
          <p :class="subheadlineClass">{{ subheadline }}</p>
        </div>

        <div
          v-if="showRegistrationDisabledNotice"
          class="mb-5 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-100"
        >
          <div class="flex items-start gap-2">
            <Info class="mt-0.5 size-4 shrink-0 text-amber-400" />
            <div class="space-y-2">
              <p class="font-medium text-amber-100">{{ t('auth.registrationDisabledTitle') }}</p>
              <p class="text-amber-100/90">
                {{ t('auth.registrationDisabledIntro') }}
                <a
                  href="https://zavixai.com/html/sage.html"
                  target="_blank"
                  rel="noreferrer"
                  class="font-medium text-amber-200 underline underline-offset-2 hover:text-amber-100"
                >
                  {{ t('auth.registrationDisabledDesktopLink') }}
                </a>
              </p>
              <p class="text-amber-100/90">
                {{ t('auth.registrationDisabledSelfHostIntro') }}
                <a
                  href="https://github.com/ZHangZHengEric/Sage"
                  target="_blank"
                  rel="noreferrer"
                  class="font-medium text-amber-200 underline underline-offset-2 hover:text-amber-100"
                >
                  {{ t('auth.registrationDisabledRepoLink') }}
                </a>
              </p>
              <p class="text-amber-100/90">
                {{ t('auth.registrationDisabledContactIntro') }}
                <span class="font-mono text-amber-200">{{ t('auth.registrationDisabledContactWeChat1') }}</span>
                <span class="mx-1">/</span>
                <span class="font-mono text-amber-200">{{ t('auth.registrationDisabledContactWeChat2') }}</span>
              </p>
            </div>
          </div>
        </div>

        <div v-if="localProvider">
          <form :class="formClass" @submit.prevent="handleLocalSubmit">
            <div :class="fieldClass">
              <Label for="account" class="text-sm font-medium">{{ accountLabel }}</Label>
              <Input
                id="account"
                v-model="account"
                type="text"
                :placeholder="accountPlaceholder"
                autocomplete="username"
                required
                :class="inputClass"
                @focus="isTyping = true"
                @blur="isTyping = false"
              />
            </div>

            <div v-if="localMode === 'login'" :class="fieldClass">
              <Label for="password" class="text-sm font-medium">{{ t('auth.password') }}</Label>
              <div class="relative">
                <Input
                  id="password"
                  v-model="password"
                  :type="loginPasswordInputType"
                  placeholder="••••••••"
                  :autocomplete="localMode === 'login' ? 'current-password' : 'new-password'"
                  required
                  :class="passwordInputClass"
                />
                <button
                  type="button"
                  class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none"
                  :aria-label="loginPasswordToggleLabel"
                  :aria-pressed="loginPasswordVisible"
                  :title="loginPasswordToggleLabel"
                  @mousedown.prevent
                  @click="toggleLoginPasswordVisibility"
                >
                  <EyeOff v-if="loginPasswordVisible" class="size-5" />
                  <Eye v-else class="size-5" />
                </button>
              </div>
            </div>

            <div v-if="localMode === 'register'" :class="passwordGroupClass">
              <div :class="fieldClass">
                <Label for="password" class="text-sm font-medium">{{ t('auth.password') }}</Label>
                <div class="relative">
                  <Input
                    id="password"
                    v-model="password"
                    :type="registerPasswordInputType"
                    placeholder="••••••••"
                    :autocomplete="localMode === 'login' ? 'current-password' : 'new-password'"
                    required
                    :class="passwordInputClass"
                  />
                  <button
                    type="button"
                    class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none"
                    :aria-label="registerPasswordToggleLabel"
                    :aria-pressed="registerPasswordVisible"
                    :title="registerPasswordToggleLabel"
                    @mousedown.prevent
                    @click="toggleRegisterPasswordVisibility"
                  >
                    <EyeOff v-if="registerPasswordVisible" class="size-5" />
                    <Eye v-else class="size-5" />
                  </button>
                </div>
              </div>

              <div :class="fieldClass">
                <Label for="confirmPassword" class="text-sm font-medium">{{ t('auth.confirmPassword') }}</Label>
                <div class="relative">
                  <Input
                    id="confirmPassword"
                    v-model="confirmPassword"
                    :type="confirmPasswordInputType"
                    placeholder="••••••••"
                    autocomplete="new-password"
                    required
                    :class="passwordInputClass"
                  />
                  <button
                    type="button"
                    class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none"
                    :aria-label="confirmPasswordToggleLabel"
                    :aria-pressed="confirmPasswordVisible"
                    :title="confirmPasswordToggleLabel"
                    @mousedown.prevent
                    @click="toggleConfirmPasswordVisibility"
                  >
                    <EyeOff v-if="confirmPasswordVisible" class="size-5" />
                    <Eye v-else class="size-5" />
                  </button>
                </div>
              </div>
            </div>

            <div v-if="localMode === 'login'" class="flex items-center justify-between">
              <div class="flex items-center space-x-2">
                <Checkbox id="remember" />
                <Label for="remember" class="text-sm font-normal cursor-pointer">
                  {{ t('auth.remember30Days') }}
                </Label>
              </div>
            </div>

            <div v-if="errorMessage" class="p-3 text-sm text-red-400 bg-red-950/20 border border-red-900/30 rounded-lg">
              {{ errorMessage }}
            </div>

            <Button type="submit" :class="submitButtonClass" size="lg" :disabled="isLoading">
              {{ isLoading ? loadingLabel : primaryActionLabel }}
            </Button>
          </form>
        </div>

        <div v-if="localProvider" :class="footerSwitchClass">
          <template v-if="localMode === 'login' && allowRegistration">
            {{ t('auth.noAccount') }}
            <button class="text-foreground font-medium hover:underline" @click="switchMode('register')">
              {{ t('auth.signUp') }}
            </button>
          </template>
          <template v-else-if="localMode === 'register'">
            {{ t('auth.haveAccount') }}
            <button class="text-foreground font-medium hover:underline" @click="switchMode('login')">
              {{ t('auth.signIn') }}
            </button>
          </template>
        </div>

        <div :class="mobileLinksClass">
          <a
            href="https://wiki.sage.zavixai.com/"
            target="_blank"
            rel="noreferrer"
            class="hover:text-foreground transition-colors"
          >
            {{ t('auth.documentation') }}
          </a>
          <a
            href="https://github.com/ZHangZHengEric/Sage/issues"
            target="_blank"
            rel="noreferrer"
            class="hover:text-foreground transition-colors"
          >
            {{ t('auth.githubIssues') }}
          </a>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Eye, EyeOff, Info } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

import AnimatedCharactersStage from '@/components/auth/AnimatedCharactersStage.vue'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { systemAPI } from '@/api/system.js'
import { loginAPI, registerAPI } from '@/utils/auth.js'
import { cn } from '@/utils/cn'
import { useLanguage } from '@/utils/i18n.js'
import { getAssetUrl } from '@/config/runtime.js'

const router = useRouter()
const route = useRoute()
const { toggleLanguage, isZhCN, t } = useLanguage()
const logoUrl = getAssetUrl('sage_logo.svg')

const allowRegistration = ref(true)
const loginPasswordVisible = ref(false)
const registerPasswordVisible = ref(false)
const confirmPasswordVisible = ref(false)
const account = ref('')
const password = ref('')
const confirmPassword = ref('')
const errorMessage = ref('')
const isLoading = ref(false)
const isTyping = ref(false)
const localMode = ref('login')
const isRegisterMode = computed(() => localMode.value === 'register')

const safeNextPath = computed(() => {
  const nextPath = typeof route.query.next === 'string' ? route.query.next : '/agent/chat'
  return nextPath.startsWith('/') ? nextPath : '/agent/chat'
})
const shouldUseBrowserNavigation = (targetPath) => (
  targetPath.startsWith('/jaeger/')
  || targetPath.startsWith('/api/')
)

const navigateAfterAuth = async (targetPath) => {
  if (shouldUseBrowserNavigation(targetPath)) {
    window.location.assign(targetPath)
    return
  }
  await router.replace(targetPath)
}

const localProvider = true
const showRegistrationDisabledNotice = computed(() => (
  !allowRegistration.value && localMode.value === 'login'
))
const accountLabel = computed(() => (localMode.value === 'login' ? t('auth.account') : t('auth.username')))
const accountPlaceholder = computed(() => (localMode.value === 'login' ? t('auth.accountPlaceholder') : t('auth.usernamePlaceholder')))
const showPassword = computed(() => (
  localMode.value === 'login'
    ? loginPasswordVisible.value
    : (registerPasswordVisible.value || confirmPasswordVisible.value)
))
const loginPasswordInputType = computed(() => (loginPasswordVisible.value ? 'text' : 'password'))
const registerPasswordInputType = computed(() => (registerPasswordVisible.value ? 'text' : 'password'))
const confirmPasswordInputType = computed(() => (confirmPasswordVisible.value ? 'text' : 'password'))
const loginPasswordToggleLabel = computed(() => (loginPasswordVisible.value ? t('auth.hidePassword') : t('auth.showPassword')))
const registerPasswordToggleLabel = computed(() => (registerPasswordVisible.value ? t('auth.hidePassword') : t('auth.showPassword')))
const confirmPasswordToggleLabel = computed(() => (confirmPasswordVisible.value ? t('auth.hidePassword') : t('auth.showPassword')))
const panelClass = computed(() => cn(
  'flex justify-center bg-background',
  isRegisterMode.value
    ? 'items-start px-8 pt-6 pb-8 lg:px-10 lg:pt-8 lg:pb-10'
    : 'items-center p-8'
))
const mobileLogoClass = computed(() => cn(
  'lg:hidden flex items-center justify-center gap-2 text-lg font-semibold',
  isRegisterMode.value ? 'mb-10' : 'mb-12'
))
const headerClass = computed(() => cn(
  'text-center',
  isRegisterMode.value ? 'mb-8' : 'mb-10'
))
const headlineClass = computed(() => cn(
  'font-bold tracking-tight',
  isRegisterMode.value ? 'mb-2 text-3xl' : 'mb-2 text-3xl'
))
const subheadlineClass = computed(() => cn(
  'text-muted-foreground',
  'text-sm'
))
const formClass = computed(() => (isRegisterMode.value ? 'space-y-4' : 'space-y-5'))
const fieldClass = computed(() => (isRegisterMode.value ? 'space-y-1.5' : 'space-y-2'))
const inputClass = computed(() => 'h-12 bg-background border-border/60 focus:border-primary')
const passwordInputClass = computed(() => 'h-12 pr-10 bg-background border-border/60 focus:border-primary')
const passwordGroupClass = computed(() => 'space-y-3')
const submitButtonClass = computed(() => 'w-full h-12 text-base font-medium')
const footerSwitchClass = computed(() => cn(
  'text-center text-sm text-muted-foreground',
  isRegisterMode.value ? 'mt-7' : 'mt-8'
))
const mobileLinksClass = computed(() => cn(
  'flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-xs text-muted-foreground lg:hidden',
  isRegisterMode.value ? 'mt-6' : 'mt-6'
))
const headline = computed(() => {
  return localMode.value === 'login' ? t('auth.welcomeBack') : t('auth.registerHeadline')
})

const subheadline = computed(() => {
  return localMode.value === 'login' ? t('auth.enterDetails') : t('auth.registerSubheadline')
})

const primaryActionLabel = computed(() => (localMode.value === 'login' ? t('auth.logIn') : t('auth.createAccount')))
const loadingLabel = computed(() => (localMode.value === 'login' ? t('auth.signingIn') : t('auth.creatingAccount')))

const toggleLoginPasswordVisibility = () => {
  loginPasswordVisible.value = !loginPasswordVisible.value
}

const toggleRegisterPasswordVisibility = () => {
  registerPasswordVisible.value = !registerPasswordVisible.value
}

const toggleConfirmPasswordVisibility = () => {
  confirmPasswordVisible.value = !confirmPasswordVisible.value
}

const switchMode = (mode) => {
  errorMessage.value = ''
  confirmPassword.value = ''
  loginPasswordVisible.value = false
  registerPasswordVisible.value = false
  confirmPasswordVisible.value = false
  localMode.value = mode
}

const loadAuthConfig = async () => {
  try {
    const info = await systemAPI.getSystemInfo()
    allowRegistration.value = info.allow_registration !== false
  } catch (error) {
    console.error('Failed to load auth config:', error)
    errorMessage.value = t('auth.loadProvidersFailed')
  }
}

const handleLocalSubmit = async () => {
  if (!localProvider.value) return
  if (!account.value || !password.value) {
    errorMessage.value = t('auth.requiredFields')
    return
  }
  if (localMode.value === 'register') {
    if (!allowRegistration.value) {
      errorMessage.value = t('auth.registrationDisabled')
      return
    }
    if (password.value !== confirmPassword.value) {
      errorMessage.value = t('auth.passwordsMismatch')
      return
    }
  }

  isLoading.value = true
  errorMessage.value = ''
  try {
    const result = localMode.value === 'login'
      ? await loginAPI(account.value, password.value)
      : await registerAPI(account.value, password.value)

    if (!result.success) {
      errorMessage.value = result.message || t('auth.authFailed')
      return
    }

    toast.success(localMode.value === 'login' ? t('auth.loginSuccess') : t('auth.accountCreatedSuccess'))
    await navigateAfterAuth(safeNextPath.value)
  } catch (error) {
    console.error('Local auth failed:', error)
    errorMessage.value = t('auth.authRetry')
  } finally {
    isLoading.value = false
  }
}

onMounted(() => {
  loadAuthConfig()
})
</script>
