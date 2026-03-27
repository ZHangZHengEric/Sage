<template>
  <div class="h-full flex flex-col bg-muted/30">
    <div class="p-6">
      <Card class="p-6 max-w-3xl shadow-sm">
        <div class="flex items-start justify-between gap-4 pb-4 border-b">
          <div class="space-y-1">
            <h3 class="text-lg font-medium">{{ t('system.generalSettings') }}</h3>
            <p class="text-sm text-muted-foreground">
              管理当前实例的通用配置和访问策略。
            </p>
          </div>
          <Badge v-if="currentVersion" variant="outline" class="text-xs">
            {{ currentVersion }}
          </Badge>
        </div>

        <div class="divide-y">
          <div class="flex items-center justify-between gap-4 py-5">
            <div class="flex items-start gap-3">
              <div class="p-2 rounded-lg bg-blue-100 text-blue-600 dark:bg-blue-950/30 dark:text-blue-400">
                <Palette class="w-5 h-5" />
              </div>
              <div class="space-y-0.5">
                <Label class="text-base">{{ t('sidebar.theme') }}</Label>
                <p class="text-sm text-muted-foreground">
                  {{ t('system.themeDesc') }}
                </p>
              </div>
            </div>
            <Select :model-value="themeStore.theme" @update:model-value="themeStore.setTheme">
              <SelectTrigger class="w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="light">{{ t('sidebar.themeLight') }}</SelectItem>
                <SelectItem value="dark">{{ t('sidebar.themeDark') }}</SelectItem>
                <SelectItem value="system">{{ t('sidebar.themeSystem') }}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div class="flex items-center justify-between gap-4 py-5">
            <div class="flex items-start gap-3">
              <div class="p-2 rounded-lg bg-emerald-100 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-400">
                <UserPlus class="w-5 h-5" />
              </div>
              <div class="space-y-0.5">
                <Label class="text-base">{{ t('system.allowRegistration') }}</Label>
                <p class="text-sm text-muted-foreground">
                  {{ t('system.allowRegistrationDesc') }}
                </p>
              </div>
            </div>
            <div class="flex items-center gap-3">
              <Badge :variant="settings.allow_registration ? 'default' : 'secondary'" class="text-xs">
                {{ settings.allow_registration ? '已开启' : '已关闭' }}
              </Badge>
              <Switch :checked="settings.allow_registration" @update:checked="(val) => updateSetting('allow_registration', val)" />
            </div>
          </div>
        </div>
      </Card>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { systemAPI } from '../api/system'
import { useLanguage } from '../utils/i18n'
import { useThemeStore } from '../stores/theme'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Palette, UserPlus } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

const { t } = useLanguage()
const themeStore = useThemeStore()
const settings = ref({ allow_registration: false })
const currentVersion = ref('')

const fetchSettings = async () => {
  const data = await systemAPI.getSystemInfo()
  settings.value.allow_registration = data.allow_registration
  currentVersion.value = data.version || data.app_version || data.current_version || ''
}

const updateSetting = async (key, value) => {
  const oldValue = settings.value[key]
  settings.value[key] = value
  try {
    await systemAPI.updateSettings({ ...settings.value })
    toast.success(t('system.updateSuccess'))
  } catch (error) {
    toast.error(t('system.updateError'))
    settings.value[key] = oldValue
  }
}

onMounted(fetchSettings)
</script>
