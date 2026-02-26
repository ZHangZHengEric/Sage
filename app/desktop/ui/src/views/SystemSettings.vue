<template>
  <div class="h-full flex flex-col bg-muted/30">

    
    <div class="p-6">
        <Card class="p-6 max-w-2xl">
            <h3 class="text-lg font-medium mb-4">{{ t('system.generalSettings') }}</h3>
            
            <!-- Theme Setting -->
            <div class="flex items-center justify-between py-4 border-b">
                <div class="space-y-0.5">
                    <Label class="text-base">{{ t('sidebar.theme') }}</Label>
                    <p class="text-sm text-muted-foreground">
                        {{ t('system.themeDesc') }}
                    </p>
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

            <div class="flex items-center justify-between py-4 border-b">
                <div class="space-y-0.5">
                    <Label class="text-base">{{ t('system.allowRegistration') }}</Label>
                    <p class="text-sm text-muted-foreground">
                        {{ t('system.allowRegistrationDesc') }}
                    </p>
                </div>
                <Switch :checked="settings.allow_registration" @update:checked="(val) => updateSetting('allow_registration', val)" />
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from 'vue-sonner'

const { t } = useLanguage()
const themeStore = useThemeStore()
const settings = ref({ allow_registration: false })

const fetchSettings = async () => {
    const data = await systemAPI.getSystemInfo()
    settings.value.allow_registration = data.allow_registration
    console.log(settings.value)
}

const updateSetting = async (key, value) => {
    console.log(key, value)
    // Optimistic update
    const oldValue = settings.value[key]
    settings.value[key] = value
    try {
        await systemAPI.updateSettings({ ...settings.value })
        toast.success(t('system.updateSuccess'))
    } catch (error) {
        toast.error(t('system.updateError'))
        // Revert
        settings.value[key] = oldValue
    }
}

onMounted(fetchSettings)
</script>
