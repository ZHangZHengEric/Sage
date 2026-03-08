<template>
  <div class="h-full flex flex-col bg-muted/30">

    
    <div class="p-6">
        <Card class="p-6 max-w-2xl">
            <h3 class="text-lg font-medium mb-4">{{ t('system.generalSettings') }}</h3>
            
            <!-- User Avatar Setting -->
            <div class="flex items-center justify-between py-4 border-b">
                <div class="space-y-0.5">
                    <Label class="text-base">{{ t('system.userAvatar') || '用户头像' }}</Label>
                    <p class="text-sm text-muted-foreground">
                        {{ t('system.userAvatarDesc') || '选择或随机生成您的头像' }}
                    </p>
                </div>
                <div class="flex items-center gap-3">
                    <img 
                        :src="userAvatarUrl" 
                        alt="User Avatar" 
                        class="w-12 h-12 rounded-full border-2 border-primary/20"
                    />
                    <Button 
                        variant="outline" 
                        size="sm"
                        @click="randomizeAvatar"
                        :title="t('system.randomAvatar') || '随机头像'"
                    >
                        <RefreshCw class="w-4 h-4 mr-1" />
                        {{ t('system.random') || '随机' }}
                    </Button>
                </div>
            </div>
            
            <!-- Language Setting -->
            <div class="flex items-center justify-between py-4 border-b">
                <div class="space-y-0.5">
                    <Label class="text-base">{{ t('sidebar.language') }}</Label>
                    <p class="text-sm text-muted-foreground">
                        {{ t('system.languageDesc') }}
                    </p>
                </div>
                <Select :model-value="language" @update:model-value="setLanguage">
                  <SelectTrigger class="w-[180px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="zhCN">简体中文</SelectItem>
                    <SelectItem value="enUS">English</SelectItem>
                  </SelectContent>
                </Select>
            </div>

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
import { ref, computed, onMounted } from 'vue'
import { useLanguage } from '../utils/i18n'
import { useThemeStore } from '../stores/theme'
import { useUserStore } from '../stores/user'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { RefreshCw } from 'lucide-vue-next'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const { t, language, setLanguage } = useLanguage()
const themeStore = useThemeStore()
const userStore = useUserStore()

// 用户头像 URL
const userAvatarUrl = computed(() => {
  return userStore.avatarUrl
})

// 随机生成头像
const randomizeAvatar = () => {
  const newSeed = Math.random().toString(36).substring(2, 15)
  userStore.setAvatarSeed(newSeed)
}

onMounted(() => {
  // 如果用户没有头像种子，生成一个随机的
  if (!userStore.avatarSeed) {
    randomizeAvatar()
  }
})
</script>
