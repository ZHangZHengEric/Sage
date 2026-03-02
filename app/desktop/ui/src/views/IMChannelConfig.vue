<template>
  <div class="flex flex-col h-full bg-background">
    <!-- Header -->
    <div class="flex items-center justify-between p-4 border-b bg-card">
      <div class="flex items-center space-x-2">
        <MessageSquare class="w-5 h-5 text-primary" />
        <h1 class="text-lg font-semibold">{{ t('im.title') }}</h1>
      </div>
    </div>

    <!-- Provider Tabs -->
    <div class="flex border-b bg-card">
      <button
        v-for="provider in providers"
        :key="provider.key"
        class="flex-1 py-3 px-4 text-sm font-medium transition-colors relative"
        :class="[
          activeProvider === provider.key
            ? 'text-primary'
            : 'text-muted-foreground hover:text-foreground'
        ]"
        @click="activeProvider = provider.key"
      >
        <div class="flex items-center justify-center space-x-2">
          <component :is="provider.icon" class="w-4 h-4" />
          <span>{{ provider.label }}</span>
          <span
            v-if="provider.isEnabled"
            class="w-2 h-2 rounded-full bg-green-500"
          />
        </div>
        <div
          v-if="activeProvider === provider.key"
          class="absolute bottom-0 left-0 right-0 h-0.5 bg-primary"
        />
      </button>
    </div>

    <!-- Configuration Content -->
    <div class="flex-1 overflow-y-auto p-6">
      <!-- Feishu Configuration -->
      <div v-if="activeProvider === 'feishu'" class="space-y-6 max-w-2xl mx-auto">
        <div class="space-y-2">
          <h2 class="text-xl font-semibold">{{ t('im.feishu.title') }}</h2>
          <p class="text-sm text-muted-foreground">{{ t('im.feishu.description') }}</p>
        </div>

        <div class="flex items-center justify-between p-4 bg-card rounded-lg border">
          <div class="space-y-1">
            <Label class="text-base">{{ t('im.enable') }}</Label>
            <p class="text-sm text-muted-foreground">{{ t('im.feishu.enableDesc') }}</p>
          </div>
          <Switch v-model="config.feishu.enabled" />
        </div>

        <div class="space-y-4">
          <div class="space-y-2">
            <Label for="feishu-app-id">{{ t('im.feishu.appId') }}</Label>
            <Input
              id="feishu-app-id"
              v-model="config.feishu.app_id"
              :placeholder="t('im.feishu.appIdPlaceholder')"
            />
          </div>

          <div class="space-y-2">
            <Label for="feishu-app-secret">{{ t('im.feishu.appSecret') }}</Label>
            <Input
              id="feishu-app-secret"
              v-model="config.feishu.app_secret"
              type="password"
              :placeholder="t('im.feishu.appSecretPlaceholder')"
            />
          </div>

          <div class="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
            <h4 class="font-medium text-blue-900 dark:text-blue-100 mb-2">
              {{ t('im.feishu.setupGuide') }}
            </h4>
            <ol class="text-sm text-blue-800 dark:text-blue-200 space-y-1 list-decimal list-inside">
              <li>{{ t('im.feishu.step1') }}</li>
              <li>{{ t('im.feishu.step2') }}</li>
              <li>{{ t('im.feishu.step3') }}</li>
            </ol>
          </div>
        </div>
      </div>

      <!-- DingTalk Configuration -->
      <div v-if="activeProvider === 'dingtalk'" class="space-y-6 max-w-2xl mx-auto">
        <div class="space-y-2">
          <h2 class="text-xl font-semibold">{{ t('im.dingtalk.title') }}</h2>
          <p class="text-sm text-muted-foreground">{{ t('im.dingtalk.description') }}</p>
        </div>

        <div class="flex items-center justify-between p-4 bg-card rounded-lg border">
          <div class="space-y-1">
            <Label class="text-base">{{ t('im.enable') }}</Label>
            <p class="text-sm text-muted-foreground">{{ t('im.dingtalk.enableDesc') }}</p>
          </div>
          <Switch v-model="config.dingtalk.enabled" />
        </div>

        <div class="space-y-4">
          <div class="space-y-2">
            <Label for="dingtalk-client-id">{{ t('im.dingtalk.clientId') }}</Label>
            <Input
              id="dingtalk-client-id"
              v-model="config.dingtalk.client_id"
              :placeholder="t('im.dingtalk.clientIdPlaceholder')"
            />
          </div>

          <div class="space-y-2">
            <Label for="dingtalk-client-secret">{{ t('im.dingtalk.clientSecret') }}</Label>
            <Input
              id="dingtalk-client-secret"
              v-model="config.dingtalk.client_secret"
              type="password"
              :placeholder="t('im.dingtalk.clientSecretPlaceholder')"
            />
          </div>

          <div class="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
            <h4 class="font-medium text-blue-900 dark:text-blue-100 mb-2">
              {{ t('im.dingtalk.setupGuide') }}
            </h4>
            <ol class="text-sm text-blue-800 dark:text-blue-200 space-y-1 list-decimal list-inside">
              <li>{{ t('im.dingtalk.step1') }}</li>
              <li>{{ t('im.dingtalk.step2') }}</li>
              <li>{{ t('im.dingtalk.step3') }}</li>
            </ol>
          </div>
        </div>
      </div>

      <!-- iMessage Configuration -->
      <div v-if="activeProvider === 'imessage'" class="space-y-6 max-w-2xl mx-auto">
        <div class="space-y-2">
          <h2 class="text-xl font-semibold">{{ t('im.imessage.title') }}</h2>
          <p class="text-sm text-muted-foreground">{{ t('im.imessage.description') }}</p>
        </div>

        <div class="flex items-center justify-between p-4 bg-card rounded-lg border">
          <div class="space-y-1">
            <Label class="text-base">{{ t('im.enable') }}</Label>
            <p class="text-sm text-muted-foreground">{{ t('im.imessage.enableDesc') }}</p>
          </div>
          <Switch v-model="config.imessage.enabled" />
        </div>

        <div class="space-y-4">
          <div class="space-y-2">
            <Label>{{ t('im.imessage.mode') }}</Label>
            <div class="p-3 bg-muted rounded-lg text-sm text-muted-foreground">
              {{ t('im.imessage.databasePoll') }}
            </div>
            <p class="text-xs text-muted-foreground">{{ t('im.imessage.modeHelp') }}</p>
          </div>

          <div class="space-y-2">
            <Label for="imessage-allowed-senders">{{ t('im.imessage.allowedSenders') }}</Label>
            <Textarea
              id="imessage-allowed-senders"
              v-model="allowedSendersText"
              :placeholder="t('im.imessage.allowedSendersPlaceholder')"
              rows="4"
            />
            <p class="text-xs text-muted-foreground">{{ t('im.imessage.allowedSendersHelp') }}</p>
          </div>

          <div class="p-4 bg-amber-50 dark:bg-amber-900/20 rounded-lg">
            <h4 class="font-medium text-amber-900 dark:text-amber-100 mb-2">
              {{ t('im.imessage.macosOnly') }}
            </h4>
            <p class="text-sm text-amber-800 dark:text-amber-200">
              {{ t('im.imessage.macosOnlyDesc') }}
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- Footer Actions -->
    <div class="p-4 border-t bg-card">
      <div class="flex justify-end space-x-4 max-w-2xl mx-auto">
        <Button variant="outline" @click="loadConfig" :disabled="loading">
          {{ t('common.reset') }}
        </Button>
        <Button @click="saveConfig" :disabled="saving || loading">
          <Save v-if="!saving" class="w-4 h-4 mr-2" />
          <Loader2 v-else class="w-4 h-4 mr-2 animate-spin" />
          {{ saving ? t('common.saving') : t('common.save') }}
        </Button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { MessageSquare, Save, Loader2 } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'
import { imAPI } from '@/api/im'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'


const { t } = useLanguage()

const activeProvider = ref('feishu')
const loading = ref(false)
const saving = ref(false)

const providers = computed(() => [
  {
    key: 'feishu',
    label: t('im.feishu.name'),
    icon: 'MessageSquare',
    isEnabled: config.value.feishu.enabled,
  },
  {
    key: 'dingtalk',
    label: t('im.dingtalk.name'),
    icon: 'MessageSquare',
    isEnabled: config.value.dingtalk.enabled,
  },
  {
    key: 'imessage',
    label: t('im.imessage.name'),
    icon: 'MessageSquare',
    isEnabled: config.value.imessage.enabled,
  },
])

const config = ref({
  feishu: {
    enabled: false,
    app_id: '',
    app_secret: '',
  },
  dingtalk: {
    enabled: false,
    client_id: '',
    client_secret: '',
  },
  imessage: {
    enabled: false,
    mode: 'database_poll',
    allowed_senders: [],
  },
})

const allowedSendersText = computed({
  get() {
    return config.value.imessage.allowed_senders.join('\n')
  },
  set(value) {
    config.value.imessage.allowed_senders = value
      .split('\n')
      .map(s => s.trim())
      .filter(s => s)
  },
})

const loadConfig = async () => {
  loading.value = true
  try {
    const data = await imAPI.getConfig()
    if (data) {
      config.value = {
        feishu: {
          enabled: false,
          app_id: '',
          app_secret: '',
          ...data.feishu,
        },
        dingtalk: {
          enabled: false,
          client_id: '',
          client_secret: '',
          ...data.dingtalk,
        },
        imessage: {
          enabled: false,
          mode: 'database_poll',
          allowed_senders: [],
          ...data.imessage,
        },
      }
    }
  } catch (error) {
    console.error('Failed to load IM config:', error)
    toast.error(t('im.loadError'))
  } finally {
    loading.value = false
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    await imAPI.saveConfig(config.value)
    toast.success(t('im.saveSuccess'))
  } catch (error) {
    console.error('Failed to save IM config:', error)
    toast.error(t('im.saveError'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadConfig()
})
</script>
