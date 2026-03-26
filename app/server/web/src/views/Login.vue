<template>
  <div class="min-h-screen grid lg:grid-cols-2 bg-background">
    <AnimatedCharactersStage :is-typing="isTyping" :password-length="password.length" :show-password="showPassword" />

    <div class="flex items-center justify-center p-8 bg-background">
      <div class="w-full max-w-[420px]">
        <div class="lg:hidden flex items-center justify-center gap-2 text-lg font-semibold mb-12">
          <div class="size-8 rounded-lg bg-primary/10 flex items-center justify-center p-1">
            <img :src="logoUrl" :alt="t('auth.logoAlt')" class="size-full object-contain" />
          </div>
          <span>Sage</span>
        </div>

        <div class="text-center mb-10">
          <h1 class="text-3xl font-bold tracking-tight mb-2">{{ headline }}</h1>
          <p class="text-muted-foreground text-sm">{{ subheadline }}</p>
        </div>

        <div v-if="errorMessage && !localProvider" class="mb-5 p-3 text-sm text-red-400 bg-red-950/20 border border-red-900/30 rounded-lg">
          {{ errorMessage }}
        </div>

        <div v-if="localProvider">
          <form class="space-y-5" @submit.prevent="handleLocalSubmit">
            <div class="space-y-2">
              <Label for="account" class="text-sm font-medium">{{ accountLabel }}</Label>
              <Input
                id="account"
                v-model="account"
                type="text"
                :placeholder="accountPlaceholder"
                autocomplete="username"
                required
                class="h-12 bg-background border-border/60 focus:border-primary"
                @focus="isTyping = true"
                @blur="isTyping = false"
              />
            </div>

            <div class="space-y-2">
              <Label for="password" class="text-sm font-medium">{{ t('auth.password') }}</Label>
              <div class="relative">
                <Input
                  id="password"
                  v-model="password"
                  :type="passwordInputType"
                  placeholder="••••••••"
                  :autocomplete="localMode === 'login' ? 'current-password' : 'new-password'"
                  required
                  class="h-12 pr-10 bg-background border-border/60 focus:border-primary"
                />
                <button
                  type="button"
                  class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none"
                  :aria-label="passwordToggleLabel"
                  :aria-pressed="showPassword"
                  :title="passwordToggleLabel"
                  @mousedown.prevent
                  @click="togglePasswordVisibility"
                >
                  <EyeOff v-if="showPassword" class="size-5" />
                  <Eye v-else class="size-5" />
                </button>
              </div>
            </div>

            <div v-if="localMode === 'register'" class="space-y-2">
              <Label for="confirmPassword" class="text-sm font-medium">{{ t('auth.confirmPassword') }}</Label>
              <div class="relative">
                <Input
                  id="confirmPassword"
                  v-model="confirmPassword"
                  :type="passwordInputType"
                  placeholder="••••••••"
                  autocomplete="new-password"
                  required
                  class="h-12 pr-10 bg-background border-border/60 focus:border-primary"
                />
                <button
                  type="button"
                  class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none"
                  :aria-label="passwordToggleLabel"
                  :aria-pressed="showPassword"
                  :title="passwordToggleLabel"
                  @mousedown.prevent
                  @click="togglePasswordVisibility"
                >
                  <EyeOff v-if="showPassword" class="size-5" />
                  <Eye v-else class="size-5" />
                </button>
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

            <Button type="submit" class="w-full h-12 text-base font-medium" size="lg" :disabled="isLoading">
              {{ isLoading ? loadingLabel : primaryActionLabel }}
            </Button>
          </form>
        </div>

        <div v-if="externalProviders.length" :class="cn('mt-6', !localProvider && 'mt-0')">
          <div v-if="localProvider" class="relative my-6">
            <div class="absolute inset-0 flex items-center">
              <span class="w-full border-t border-border/60" />
            </div>
            <div class="relative flex justify-center text-xs uppercase tracking-[0.28em] text-muted-foreground">
              <span class="bg-background px-3">{{ t('auth.providers') }}</span>
            </div>
          </div>

          <div class="space-y-3">
            <Button
              v-for="provider in externalProviders"
              :key="provider.id"
              variant="outline"
              class="w-full h-12 bg-background border-border/60 hover:bg-accent justify-between"
              type="button"
              :disabled="isLoading"
              @click="handleProviderLogin(provider)"
            >
              <span class="flex items-center gap-2">
                <component :is="resolveProviderIcon(provider.icon)" class="size-5" />
                {{ getProviderButtonLabel(provider) }}
              </span>
              <ArrowRight class="size-4 opacity-70" />
            </Button>
          </div>
        </div>

        <div v-if="localProvider" class="text-center text-sm text-muted-foreground mt-8">
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

        <div class="mt-10 flex items-center justify-center gap-3 text-xs text-muted-foreground">
          <button class="rounded-full border border-border/60 px-3 py-1.5 hover:bg-accent transition-colors" @click="toggleLanguage">
            {{ isZhCN ? t('sidebar.langToggleZh') : t('sidebar.langToggleEn') }}
          </button>
        </div>

        <div class="mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-xs text-muted-foreground lg:hidden">
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
import { ArrowRight, Building2, Eye, EyeOff, Github, KeyRound, Mail, ShieldCheck } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

import AnimatedCharactersStage from '@/components/auth/AnimatedCharactersStage.vue'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { systemAPI } from '@/api/system.js'
import { buildOAuthLoginUrl, loginAPI, registerAPI } from '@/utils/auth.js'
import { cn } from '@/utils/cn'
import { useLanguage } from '@/utils/i18n.js'

const router = useRouter()
const route = useRoute()
const { toggleLanguage, isZhCN, t } = useLanguage()
const logoUrl = `${import.meta.env.BASE_URL}sage_logo.svg`

const authProviders = ref([])
const allowRegistration = ref(true)
const showPassword = ref(false)
const account = ref('')
const password = ref('')
const confirmPassword = ref('')
const errorMessage = ref('')
const isLoading = ref(false)
const isTyping = ref(false)
const localMode = ref('login')

const safeNextPath = computed(() => {
  const nextPath = typeof route.query.next === 'string' ? route.query.next : '/agent/chat'
  return nextPath.startsWith('/') ? nextPath : '/agent/chat'
})
const localOnlyMode = computed(() => String(route.query.local_only || '') === '1')
const shouldUseBrowserNavigation = (targetPath) => (
  targetPath.startsWith('/jaeger/')
  || targetPath.startsWith('/api/')
  || targetPath.startsWith('/oauth2/')
)

const navigateAfterAuth = async (targetPath) => {
  if (shouldUseBrowserNavigation(targetPath)) {
    window.location.assign(targetPath)
    return
  }
  await router.replace(targetPath)
}

const localProvider = computed(() => authProviders.value.find((provider) => provider.type === 'local') || null)
const externalProviders = computed(() => (
  localOnlyMode.value
    ? []
    : authProviders.value.filter((provider) => provider.type !== 'local')
))
const accountLabel = computed(() => (localMode.value === 'login' ? t('auth.account') : t('auth.username')))
const accountPlaceholder = computed(() => (localMode.value === 'login' ? t('auth.accountPlaceholder') : t('auth.usernamePlaceholder')))
const passwordInputType = computed(() => (showPassword.value ? 'text' : 'password'))
const passwordToggleLabel = computed(() => (showPassword.value ? t('auth.hidePassword') : t('auth.showPassword')))

const headline = computed(() => {
  if (localProvider.value) {
    return t('auth.welcomeBack')
  }
  if (externalProviders.value.length === 1) {
    return t('auth.continueWith', { provider: externalProviders.value[0].name })
  }
  return t('auth.chooseProvider')
})

const subheadline = computed(() => {
  if (localProvider.value) {
    return t('auth.enterDetails')
  }
  return t('auth.providerSessionHint')
})

const primaryActionLabel = computed(() => (localMode.value === 'login' ? t('auth.logIn') : t('auth.createAccount')))
const loadingLabel = computed(() => (localMode.value === 'login' ? t('auth.signingIn') : t('auth.creatingAccount')))

const iconMap = {
  mail: Mail,
  github: Github,
  building2: Building2,
  'key-round': KeyRound,
  'shield-check': ShieldCheck,
}

const resolveProviderIcon = (iconName) => iconMap[iconName] || Mail
const getProviderButtonLabel = (provider) => provider.button_text || t('auth.continueWith', { provider: provider.name })

const togglePasswordVisibility = () => {
  showPassword.value = !showPassword.value
}

const switchMode = (mode) => {
  errorMessage.value = ''
  confirmPassword.value = ''
  showPassword.value = false
  localMode.value = mode
}

const loadAuthConfig = async () => {
  try {
    const info = await systemAPI.getSystemInfo()
    allowRegistration.value = info.allow_registration !== false
    authProviders.value = Array.isArray(info.auth_providers) ? info.auth_providers : []

    if (localOnlyMode.value && !authProviders.value.some((provider) => provider.type === 'local')) {
      errorMessage.value = t('auth.noProviderConfigured')
      return
    }

    if (!authProviders.value.length) {
      errorMessage.value = t('auth.noProviderConfigured')
    }
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

const handleProviderLogin = (provider) => {
  errorMessage.value = ''
  window.location.href = buildOAuthLoginUrl(provider.id, safeNextPath.value)
}

onMounted(() => {
  loadAuthConfig()
})
</script>
