<template>
  <div class="space-y-6">

    <!-- Strategy Settings -->
    <Card class="transition-all hover:shadow-md rounded-xl border bg-background/80 backdrop-blur-sm">
      <CardHeader class="pb-3 pt-4 px-5 bg-muted/30 cursor-pointer flex flex-row items-center justify-between rounded-t-xl" @click="toggleSection('strategy')">
        <div class="flex items-center gap-2">
          <Cpu class="h-5 w-5" />
          <CardTitle class="text-base">{{ t('agent.strategy') }}</CardTitle>
        </div>
        <ChevronDown v-if="sections.strategy" class="h-4 w-4" />
        <ChevronUp v-else class="h-4 w-4" />
      </CardHeader>
      <div v-show="!sections.strategy" class="px-5 pb-5 pt-4 space-y-6">
        <FormItem :label="t('agent.memoryType')">
           <Select v-model="store.formData.memoryType">
             <SelectTrigger>
               <SelectValue />
             </SelectTrigger>
             <SelectContent>
               <SelectItem value="session">{{ t('agent.sessionMemory') }}</SelectItem>
               <SelectItem value="user">{{ t('agent.userMemory') }}</SelectItem>
             </SelectContent>
           </Select>
        </FormItem>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
           <FormItem :label="t('agent.deepThinking')">
              <Tabs :model-value="getSelectValue(store.formData.deepThinking)" @update:model-value="(v) => setSelectValue('deepThinking', v)" class="w-full">
                <TabsList class="grid w-full grid-cols-3">
                  <TabsTrigger value="auto">{{ t('agent.auto') }}</TabsTrigger>
                  <TabsTrigger value="enabled">{{ t('agent.enabled') }}</TabsTrigger>
                  <TabsTrigger value="disabled">{{ t('agent.disabled') }}</TabsTrigger>
                </TabsList>
              </Tabs>
           </FormItem>

           <FormItem :label="t('agent.multiAgent')">
              <Tabs :model-value="getSelectValue(store.formData.multiAgent)" @update:model-value="(v) => setSelectValue('multiAgent', v)" class="w-full">
                <TabsList class="grid w-full grid-cols-3">
                  <TabsTrigger value="auto">{{ t('agent.auto') }}</TabsTrigger>
                  <TabsTrigger value="enabled">{{ t('agent.enabled') }}</TabsTrigger>
                  <TabsTrigger value="disabled">{{ t('agent.disabled') }}</TabsTrigger>
                </TabsList>
              </Tabs>
           </FormItem>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <FormItem :label="t('agent.moreSuggest')">
             <div class="flex items-center h-10 gap-2 border rounded-md px-3">
               <Switch :checked="store.formData.moreSuggest" @update:checked="(v) => store.formData.moreSuggest = v" />
               <span class="text-sm text-muted-foreground">{{ store.formData.moreSuggest ? t('agent.enabled') : t('agent.disabled') }}</span>
             </div>
          </FormItem>
          <FormItem :label="t('agent.maxLoopCount')">
            <Input type="number" v-model.number="store.formData.maxLoopCount" min="1" max="50" />
          </FormItem>
        </div>
      </div>
    </Card>

    <!-- LLM Config -->
    <Card class="transition-all hover:shadow-md rounded-xl border bg-background/80 backdrop-blur-sm">
      <CardHeader class="pb-3 pt-4 px-5 bg-muted/30 cursor-pointer flex flex-row items-center justify-between rounded-t-xl" @click="toggleSection('llm')">
        <div class="flex items-center gap-2">
          <Bot class="h-5 w-5" />
          <CardTitle class="text-base">{{ t('agent.llmConfig') }}</CardTitle>
        </div>
        <ChevronDown v-if="sections.llm" class="h-4 w-4" />
        <ChevronUp v-else class="h-4 w-4" />
      </CardHeader>
      <div v-show="!sections.llm" class="px-5 pb-5 pt-4 space-y-4">
        <FormItem :label="t('agent.apiKey')">
           <Input v-model="store.formData.llmConfig.apiKey" type="password" :placeholder="t('agent.apiKeyPlaceholder')" show-password-toggle />
        </FormItem>
        <FormItem :label="t('agent.baseUrl')">
           <Input v-model="store.formData.llmConfig.baseUrl" :placeholder="t('agent.baseUrlPlaceholder')" />
        </FormItem>
        <FormItem :label="t('agent.model')">
           <Input v-model="store.formData.llmConfig.model" :placeholder="t('agent.modelPlaceholder')" />
        </FormItem>
        <div class="grid grid-cols-2 gap-4">
           <FormItem :label="t('agent.maxTokens')">
              <Input type="number" v-model.number="store.formData.llmConfig.maxTokens" placeholder="4096" />
           </FormItem>
           <FormItem :label="t('agent.temperature')">
              <Input type="number" v-model.number="store.formData.llmConfig.temperature" step="0.1" placeholder="0.2" />
           </FormItem>
           <FormItem :label="t('agent.topP')">
              <Input type="number" v-model.number="store.formData.llmConfig.topP" step="0.1" placeholder="0.9" />
           </FormItem>
           <FormItem :label="t('agent.presencePenalty')">
              <Input type="number" v-model.number="store.formData.llmConfig.presencePenalty" step="0.1" placeholder="0.0" />
           </FormItem>
        </div>
        <FormItem :label="t('agent.maxModelLen')">
           <Input type="number" v-model.number="store.formData.llmConfig.maxModelLen" placeholder="54000" />
        </FormItem>
      </div>
    </Card>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { useAgentEditStore } from '../../stores/agentEdit'
import { useLanguage } from '../../utils/i18n.js'
import { ChevronDown, ChevronUp, Bot, Cpu } from 'lucide-vue-next'

// UI Components
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
import { FormItem } from '@/components/ui/form'

const store = useAgentEditStore()
const { t } = useLanguage()

const sections = reactive({
  strategy: false,
  llm: true // Default collapsed? "Default collapsed, only show...". I'll start with LLM collapsed (true).
})

const toggleSection = (key) => {
  sections[key] = !sections[key]
}

// Helpers
const getSelectValue = (val) => {
  if (val === null) return 'auto'
  return val ? 'enabled' : 'disabled'
}

const setSelectValue = (field, val) => {
  if (val === 'auto') store.formData[field] = null
  else if (val === 'enabled') store.formData[field] = true
  else store.formData[field] = false
}
</script>
