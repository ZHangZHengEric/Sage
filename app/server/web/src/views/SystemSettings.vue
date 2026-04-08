<template>
  <div class="h-full overflow-y-auto bg-background">
    <div class="mx-auto flex w-full max-w-4xl flex-col gap-5 px-6 py-5">
      <div class="flex items-end justify-between gap-4 border-b border-border/60 pb-4">
        <div class="space-y-1.5">
          <p class="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/65">SAGE</p>
          <div class="space-y-0.5">
            <h1 class="text-[1.75rem] font-semibold tracking-tight text-foreground">
              {{ t('system.title') }}
            </h1>
            <p class="max-w-2xl text-[13px] leading-5 text-muted-foreground">
              {{ t('system.subtitle') }}
            </p>
          </div>
        </div>
        <div v-if="currentVersion" class="hidden items-center gap-2 rounded-full border border-border/70 bg-muted/25 px-3 py-1.5 text-[11px] text-muted-foreground md:flex">
          <span class="h-2 w-2 rounded-full bg-emerald-500/80" />
          {{ t('system.currentVersion') }}: {{ currentVersion }}
        </div>
      </div>

      <div class="space-y-5">
        <section class="space-y-2">
          <div class="flex items-center gap-2.5">
            <Palette class="h-3.5 w-3.5 text-muted-foreground" />
            <h2 class="text-[12px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{{ t('system.preferences') }}</h2>
          </div>

          <div class="overflow-hidden rounded-[18px] border border-border/60 bg-transparent">
            <div class="flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-center md:justify-between">
              <div class="space-y-1">
                <Label class="text-sm font-medium">{{ t('sidebar.language') }}</Label>
                <p class="text-[13px] text-muted-foreground">{{ t('system.languageDesc') }}</p>
              </div>
              <Select :model-value="language" @update:model-value="setLanguage">
                <SelectTrigger class="h-9 w-full rounded-full border-border/70 bg-background/90 px-3.5 text-[13px] shadow-none md:w-[170px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="zhCN">简体中文</SelectItem>
                  <SelectItem value="enUS">English</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div class="h-px bg-border/60" />

            <div class="flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-center md:justify-between">
              <div class="space-y-1">
                <Label class="text-sm font-medium">{{ t('sidebar.theme') }}</Label>
                <p class="text-[13px] text-muted-foreground">{{ t('system.themeDesc') }}</p>
              </div>
              <Select :model-value="themeStore.theme" @update:model-value="themeStore.setTheme">
                <SelectTrigger class="h-9 w-full rounded-full border-border/70 bg-background/90 px-3.5 text-[13px] shadow-none md:w-[170px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="light">{{ t('sidebar.themeLight') }}</SelectItem>
                  <SelectItem value="dark">{{ t('sidebar.themeDark') }}</SelectItem>
                  <SelectItem value="system">{{ t('sidebar.themeSystem') }}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </section>

        <section class="space-y-2">
          <div class="flex items-center gap-2.5">
            <Settings class="h-3.5 w-3.5 text-muted-foreground" />
            <h2 class="text-[12px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{{ t('system.environment') }}</h2>
          </div>

          <div class="overflow-hidden rounded-[18px] border border-border/60 bg-transparent">
            <div class="flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-center md:justify-between">
              <div class="space-y-1">
                <Label class="text-sm font-medium">{{ t('system.currentVersion') }}</Label>
                <p class="text-[13px] text-muted-foreground">{{ currentVersion || '-' }}</p>
              </div>
              <Badge variant="outline" class="rounded-full px-3 py-1 text-[11px]">
                {{ currentVersion || '-' }}
              </Badge>
            </div>
          </div>
        </section>

        <section class="space-y-2">
          <div class="flex items-center gap-2.5">
            <UserPlus class="h-3.5 w-3.5 text-muted-foreground" />
            <h2 class="text-[12px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{{ t('system.generalSettings') }}</h2>
          </div>

          <div class="overflow-hidden rounded-[18px] border border-border/60 bg-transparent">
            <div class="flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-center md:justify-between">
              <div class="space-y-1">
                <Label class="text-sm font-medium">{{ t('system.allowRegistration') }}</Label>
                <p class="text-[13px] text-muted-foreground">{{ t('system.instancePolicyDesc') }}</p>
              </div>
              <div class="flex items-center gap-3">
                <Badge :variant="settings.allow_registration ? 'default' : 'secondary'" class="rounded-full px-3 py-1 text-[11px]">
                  {{ settings.allow_registration ? t('common.enabled') : t('common.disabled') }}
                </Badge>
                <Switch :checked="settings.allow_registration" @update:checked="(val) => updateSetting('allow_registration', val)" />
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { systemAPI } from '../api/system'
import { useLanguage } from '../utils/i18n'
import { useThemeStore } from '../stores/theme'
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
import { Palette, UserPlus, Settings } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

const { t, language, setLanguage } = useLanguage()
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
