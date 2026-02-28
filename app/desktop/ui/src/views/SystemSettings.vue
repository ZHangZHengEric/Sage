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
        </Card>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useLanguage } from '../utils/i18n'
import { useThemeStore } from '../stores/theme'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const { t } = useLanguage()
const themeStore = useThemeStore()
</script>
