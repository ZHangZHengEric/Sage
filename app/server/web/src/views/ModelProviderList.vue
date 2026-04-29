<template>
  <div class="h-full flex flex-col p-6 space-y-6">
    <div class="flex items-center justify-between">
      <div class="space-y-1">
        <h2 class="text-lg font-medium">{{ t('modelProvider.title') }}</h2>
        <p class="text-sm text-muted-foreground">{{ t('modelProvider.description') }}</p>
      </div>
      <Button @click="handleCreate">
        <Plus class="mr-2 h-4 w-4" />
        {{ t('common.create') }}
      </Button>
    </div>

    <div v-if="providers && providers.length > 0" class="border rounded-xl bg-card shadow-sm overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{{ t('modelProvider.name') }}</TableHead>
            <TableHead>{{ t('modelProvider.baseUrl') }}</TableHead>
            <TableHead>{{ t('modelProvider.model') }}</TableHead>
            <TableHead class="w-[100px]">{{ t('common.actions') }}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="provider in providers" :key="provider.id">
            <TableCell class="font-medium">
               <div class="flex items-center gap-3">
                 <div class="h-9 w-9 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                   <Bot class="h-4 w-4" />
                 </div>
                 <div class="min-w-0">
             <div class="flex items-center gap-2">
               <span class="truncate">{{ provider.name }}</span>
                 <Badge v-if="provider.is_default" variant="secondary">{{ t('common.default') }}</Badge>
                 <Badge v-if="provider.supports_multimodal" variant="outline" class="h-5 rounded-full px-2 text-[10px]">
                   {{ t('modelProvider.multimodalLabel') }}
                 </Badge>
                 <Badge v-if="provider.supports_structured_output" variant="outline" class="h-5 rounded-full px-2 text-[10px]">
                   {{ t('modelProvider.structuredOutputLabel') }}
                 </Badge>
                 </div>
                   <p class="text-xs text-muted-foreground truncate">{{ provider.model }}</p>
                 </div>
               </div>
            </TableCell>
            <TableCell class="text-muted-foreground max-w-[260px] truncate" :title="provider.base_url">{{ provider.base_url }}</TableCell>
            <TableCell>
              <Badge variant="outline">{{ provider.model }}</Badge>
            </TableCell>
            <TableCell>
              <div class="flex items-center gap-2">
                <Button variant="ghost" size="icon" @click="handleEdit(provider)">
                  <Edit class="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" @click="handleDelete(provider)" :disabled="provider.is_default">
                  <Trash2 class="h-4 w-4 text-destructive" />
                </Button>
              </div>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>
    
    <div v-else class="flex flex-col items-center justify-center py-12 text-center border rounded-xl border-dashed bg-card">
      <div class="p-4 rounded-full bg-muted/50 mb-4">
        <Bot class="w-8 h-8 text-muted-foreground" />
      </div>
      <h3 class="text-lg font-semibold">{{ t('modelProvider.noProviders') }}</h3>
      <p class="text-sm text-muted-foreground mt-2 max-w-sm">
        {{ t('modelProvider.noProvidersDesc') }}
      </p>
      <Button class="mt-6" @click="handleCreate">
        <Plus class="mr-2 h-4 w-4" />
        {{ t('modelProvider.createTitle') }}
      </Button>
    </div>

    <!-- Dialog -->
    <Dialog :open="dialogOpen" @update:open="onDialogOpenChange">
      <DialogContent
        :showClose="!saving"
        class="flex h-[760px] max-h-[86vh] flex-col overflow-hidden border-border/60 bg-background p-0 sm:max-w-[760px]"
      >
        <DialogHeader class="border-b border-border/60 px-6 py-5 text-left">
          <DialogTitle class="text-[16px] font-semibold tracking-tight">
            {{ isEdit ? t('modelProvider.editTitle') : t('modelProvider.createTitle') }}
          </DialogTitle>
        </DialogHeader>

        <div class="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <div class="grid gap-4 lg:grid-cols-[260px,minmax(0,1fr)] lg:items-start">
            <div class="grid gap-4 lg:sticky lg:top-0">
              <div class="rounded-2xl border border-border/60 bg-muted/[0.14] p-4">
                <div class="flex items-start gap-3">
                  <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-background ring-1 ring-border/60">
                    <Link2 class="h-4 w-4 text-foreground/80" />
                  </div>
                  <div class="min-w-0">
                    <div class="text-[14px] font-semibold tracking-tight text-foreground">
                      {{ form.name || selectedProvider || t('modelProvider.newSource') }}
                    </div>
                  </div>
                </div>

                <div class="mt-4 flex flex-wrap items-center gap-2">
                  <Badge :variant="verificationBadgeVariant" class="h-6 rounded-full px-2.5 text-[10px]">
                    {{ verificationBadgeLabel }}
                  </Badge>
                  <Badge v-if="form.supportsStructuredOutput" variant="outline" class="h-6 rounded-full px-2.5 text-[10px] font-medium">
                    {{ t('modelProvider.capabilityStructuredOutput') }}
                  </Badge>
                  <Badge variant="outline" class="h-6 rounded-full px-2.5 text-[10px] font-medium">
                    {{ selectedProvider && selectedProvider !== 'Custom' ? selectedProvider : t('modelProvider.customProviderBadge') }}
                  </Badge>
                  <Badge variant="outline" class="h-6 rounded-full px-2.5 text-[10px] font-medium">
                    {{ apiKeyCount > 0 ? t('modelProvider.apiKeyCount', { count: apiKeyCount }) : t('modelProvider.apiKeyEmpty') }}
                  </Badge>
                  <Badge variant="outline" class="h-6 max-w-full rounded-full px-2.5 text-[10px] font-medium">
                    <span class="truncate">{{ form.model || t('modelProvider.modelUnselected') }}</span>
                  </Badge>
                </div>
              </div>

              <div class="rounded-2xl border border-border/60 bg-background/70 p-4">
                <div class="flex items-center justify-between gap-3">
                  <div class="flex items-center gap-2">
                    <h3 class="text-[13px] font-semibold tracking-tight text-foreground">{{ t('modelProvider.verificationSection') }}</h3>
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger as-child>
                          <button class="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground">
                            <CircleHelp class="h-3.5 w-3.5" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent side="right" class="max-w-[220px] text-[12px] leading-5">
                          {{ t('modelProvider.verifyCapabilitiesHint') }}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                </div>

                <div class="mt-3 flex flex-wrap items-center gap-2">
                  <Badge variant="outline" class="h-6 rounded-full px-2.5 text-[10px] font-medium">
                    {{ capabilityBadgeLabel }}
                  </Badge>
                  <Badge variant="outline" class="h-6 rounded-full px-2.5 text-[10px] font-medium">
                    {{ capabilityDetailLabel }}
                  </Badge>
                  <Badge v-if="capabilityChecked && form.supportsStructuredOutput" variant="outline" class="h-6 rounded-full px-2.5 text-[10px] font-medium">
                    {{ t('modelProvider.capabilityStructuredOutput') }}
                  </Badge>
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger as-child>
                        <button class="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground">
                          <CircleHelp class="h-3.5 w-3.5" />
                        </button>
                        </TooltipTrigger>
                      <TooltipContent side="right" class="max-w-[220px] text-[12px] leading-5">
                        {{ verificationHint }}
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>

                <div class="mt-3">
                  <Button type="button" variant="secondary" class="h-9 w-full rounded-xl" @click="handleVerify" :disabled="verifying || saving">
                    <Loader v-if="verifying" class="mr-2 h-4 w-4 animate-spin" />
                    {{ verifyButtonLabel }}
                  </Button>
                </div>
              </div>
            </div>

            <div class="grid gap-4">
              <div class="rounded-2xl border border-border/60 bg-background/70 p-4">
                <div class="flex items-start justify-between gap-4">
                  <div class="flex items-center gap-2">
                    <h3 class="text-[13px] font-semibold tracking-tight text-foreground">{{ t('modelProvider.connectionSection') }}</h3>
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger as-child>
                          <button class="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground">
                            <CircleHelp class="h-3.5 w-3.5" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent side="top" class="max-w-[220px] text-[12px] leading-5">
                          {{ t('modelProvider.connectionSectionHint') }}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                  <div class="flex items-center gap-2">
                    <Button
                      v-if="currentProvider?.website"
                      variant="ghost"
                      size="sm"
                      class="h-8 rounded-lg px-2.5 text-[12px]"
                      @click="openProviderWebsite"
                    >
                      {{ t('modelProvider.getApiKey') }}
                      <ArrowRight class="ml-1 h-3.5 w-3.5" />
                    </Button>
                    <Button
                      v-if="currentProvider?.model_list_url"
                      variant="ghost"
                      size="sm"
                      class="h-8 rounded-lg px-2.5 text-[12px]"
                      @click="openProviderModelList"
                    >
                      {{ t('modelProvider.viewModels') }}
                      <ArrowRight class="ml-1 h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>

                <div class="mt-4 grid gap-4 md:grid-cols-2">
                  <div class="grid gap-2">
                    <Label>{{ t('modelProvider.providerType') }} <span class="text-destructive">*</span></Label>
                    <Select :model-value="selectedProvider" @update:model-value="handleProviderChange">
                      <SelectTrigger class="h-10 rounded-xl">
                        <SelectValue :placeholder="t('modelProvider.selectProviderPlaceholder')" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          <SelectItem v-for="provider in MODEL_PROVIDERS" :key="provider.name" :value="provider.name">
                            {{ provider.name }}
                          </SelectItem>
                          <SelectItem value="Custom">{{ t('modelProvider.custom') }}</SelectItem>
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </div>

                  <div class="grid gap-2">
                    <Label>{{ t('modelProvider.baseUrl') }} <span class="text-destructive">*</span></Label>
                    <Input
                      v-model="form.base_url"
                      class="h-10 rounded-xl"
                      placeholder="https://api.openai.com/v1"
                      @update:model-value="onKeyConfigChange"
                    />
                  </div>

                  <div v-if="selectedProvider === 'Custom'" class="grid gap-2">
                    <Label>{{ t('modelProvider.name') }} <span class="text-destructive">*</span></Label>
                    <Input
                      v-model="form.name"
                      class="h-10 rounded-xl"
                      :placeholder="t('modelProvider.customNamePlaceholder')"
                      @update:model-value="onKeyConfigChange"
                    />
                  </div>

                  <div class="grid gap-2 md:col-span-2">
                    <Label>{{ t('modelProvider.apiKey') }} <span class="text-destructive">*</span></Label>
                    <div class="relative">
                      <Input
                        v-model="form.api_keys_str"
                        class="h-10 rounded-xl pr-11"
                        :type="showApiKey ? 'text' : 'password'"
                        :placeholder="t('modelProvider.apiKeyPlaceholder')"
                        @update:model-value="handleApiKeyChange"
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        class="absolute right-1 top-1 h-8 w-8 rounded-lg text-muted-foreground"
                        @click="showApiKey = !showApiKey"
                      >
                        <Eye v-if="showApiKey" class="h-4 w-4" />
                        <EyeOff v-else class="h-4 w-4" />
                      </Button>
                    </div>
                  </div>

                  <div :class="selectedProvider === 'Custom' ? 'grid gap-2' : 'grid gap-2 md:col-span-2'">
                    <div class="flex items-center gap-2">
                      <Label>{{ t('modelProvider.model') }} <span class="text-destructive">*</span></Label>
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger as-child>
                            <button class="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground">
                              <CircleHelp class="h-3.5 w-3.5" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent side="top" class="max-w-[220px] text-[12px] leading-5">
                            {{ t('modelProvider.modelPickerHint') }}
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </div>
                    <div class="relative">
                      <Input
                        v-model="form.model"
                        class="h-10 rounded-xl pr-11"
                        :placeholder="t('modelProvider.modelPlaceholder')"
                        @update:model-value="onKeyConfigChange"
                      />
                      <div v-if="hasRecommendedModels" class="absolute right-1 top-1">
                        <Select :model-value="''" @update:model-value="handleModelQuickPick">
                          <SelectTrigger class="h-8 w-8 rounded-lg border-border/60 px-0">
                            <span class="sr-only">{{ t('modelProvider.quickPickModel') }}</span>
                            <ChevronsUpDown class="h-3.5 w-3.5" />
                          </SelectTrigger>
                          <SelectContent align="end" class="min-w-[220px]">
                            <SelectItem v-for="model in currentProvider.models" :key="model" :value="model">
                              {{ model }}
                            </SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <Collapsible v-model:open="advancedOpen" class="rounded-2xl border border-border/60 bg-background/70 p-4">
                <div class="flex items-center justify-between gap-4">
                  <div class="flex items-center gap-2">
                    <h3 class="text-[13px] font-semibold tracking-tight text-foreground">{{ t('modelProvider.advancedSection') }}</h3>
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger as-child>
                          <button class="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground">
                            <CircleHelp class="h-3.5 w-3.5" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent side="top" class="max-w-[220px] text-[12px] leading-5">
                          {{ t('modelProvider.advancedHint') }}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                  <CollapsibleTrigger as-child>
                    <Button type="button" variant="ghost" size="sm" class="h-8 rounded-lg px-2.5 text-[12px]">
                      {{ advancedOpen ? t('common.collapse') : t('common.expand') }}
                      <ChevronDown class="ml-1 h-3.5 w-3.5 transition-transform" :class="{ 'rotate-180': advancedOpen }" />
                    </Button>
                  </CollapsibleTrigger>
                </div>

                <CollapsibleContent class="pt-4">
                  <Separator class="bg-border/60" />
                  <div class="max-h-56 overflow-y-auto pt-4">
                    <div class="grid gap-4 md:grid-cols-2">
                      <div class="grid gap-2">
                        <Label>{{ t('agent.maxTokens') }}</Label>
                        <Input type="number" v-model.number="form.maxTokens" class="h-10 rounded-xl" />
                      </div>
                      <div class="grid gap-2">
                        <Label>{{ t('agent.temperature') }}</Label>
                        <Input type="number" v-model.number="form.temperature" class="h-10 rounded-xl" step="0.1" />
                      </div>
                      <div class="grid gap-2">
                        <Label>{{ t('agent.topP') }}</Label>
                        <Input type="number" v-model.number="form.topP" class="h-10 rounded-xl" step="0.1" />
                      </div>
                      <div class="grid gap-2">
                        <Label>{{ t('agent.presencePenalty') }}</Label>
                        <Input type="number" v-model.number="form.presencePenalty" class="h-10 rounded-xl" step="0.1" />
                      </div>
                      <div class="grid gap-2 md:col-span-2">
                        <Label>{{ t('agent.maxModelLen') }}</Label>
                        <Input type="number" v-model.number="form.maxModelLen" class="h-10 rounded-xl" />
                      </div>
                    </div>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </div>
          </div>
        </div>

        <DialogFooter class="flex w-full items-center border-t border-border/60 px-6 py-4 sm:justify-between">
          <p class="text-[11px] leading-5 text-muted-foreground">
            {{ footerStatusHint }}
          </p>
          <div class="flex gap-2">
            <Button variant="outline" class="h-9 rounded-xl px-3.5" :disabled="saving" @click="dialogOpen = false">{{ t('common.cancel') }}</Button>
            <Button class="h-9 rounded-xl px-3.5" @click="submitForm" :disabled="!canSave">
              <Loader v-if="saving" class="mr-2 h-4 w-4 animate-spin" />
              {{ saving ? t('common.saving') : t('common.save') }}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { Plus, Edit, Trash2, Bot, ArrowRight, Loader, Eye, EyeOff, ChevronDown, ChevronsUpDown, Link2, CircleHelp } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { useLanguage } from '@/utils/i18n'
import { modelProviderAPI } from '@/api/modelProvider'
import { MODEL_PROVIDERS } from '@/utils/modelProviders'
import { toast } from 'vue-sonner'

const { listModelProviders, createModelProvider, updateModelProvider, deleteModelProvider } = modelProviderAPI

const { t } = useLanguage()
const providers = ref([])
const dialogOpen = ref(false)
const isEdit = ref(false)
const currentId = ref(null)
const verifying = ref(false)
const saving = ref(false)
const verified = ref(false)
const capabilityChecked = ref(false)
const showApiKey = ref(false)
const advancedOpen = ref(false)

// Basic form state
const form = reactive({
  name: '',
  base_url: '',
  api_keys_str: '',
  model: '',
  maxTokens: null,
  temperature: null,
  topP: null,
  presencePenalty: null,
  maxModelLen: null,
  supportsMultimodal: false,
  supportsStructuredOutput: false
})

// 存储原始值用于比较（编辑模式）
const originalValues = reactive({
  base_url: '',
  api_keys_str: '',
  model: ''
})

const selectedProvider = ref('')
const currentProvider = computed(() => MODEL_PROVIDERS.find(p => p.name === selectedProvider.value))
const hasRecommendedModels = computed(() => Array.isArray(currentProvider.value?.models) && currentProvider.value.models.length > 0)
const apiKeyCount = computed(() => buildApiKeys().length)
const hasRequiredFields = computed(() =>
  Boolean(form.name.trim() && form.base_url.trim() && buildApiKeys().length > 0 && form.model.trim())
)
const configChanged = computed(() =>
  form.base_url !== originalValues.base_url ||
  form.api_keys_str !== originalValues.api_keys_str ||
  form.model !== originalValues.model
)
const needsCapabilityVerification = computed(() => {
  if (!hasRequiredFields.value) return false
  if (!isEdit.value) return !capabilityChecked.value
  return configChanged.value && !capabilityChecked.value
})
const verificationBadgeLabel = computed(() => {
  if (saving.value) return t('common.saving')
  if (verifying.value) return t('modelProvider.verifying')
  if (!hasRequiredFields.value) return t('modelProvider.pendingConfig')
  if (needsCapabilityVerification.value) return t('modelProvider.pendingVerification')
  if (capabilityChecked.value || isEdit.value) return t('modelProvider.readyToSave')
  return t('modelProvider.pendingConfig')
})
const verificationBadgeVariant = computed(() => {
  if (saving.value || verifying.value) return 'secondary'
  if (needsCapabilityVerification.value || !hasRequiredFields.value) return 'outline'
  return 'secondary'
})
const verificationHint = computed(() => {
  if (verifying.value) {
    return t('modelProvider.verificationCheckingHint')
  }
  if (!hasRequiredFields.value) {
    return t('modelProvider.verificationConfigHint')
  }
  if (needsCapabilityVerification.value) {
    return t('modelProvider.verificationChangedHint')
  }
  if (form.supportsMultimodal) {
    return t('modelProvider.verificationMultimodalHint')
  }
  if (capabilityChecked.value || isEdit.value) {
    return t('modelProvider.verificationTextHint')
  }
  return t('modelProvider.verificationReadyHint')
})
const capabilityBadgeLabel = computed(() => {
  if (verifying.value) return t('modelProvider.capabilityChecking')
  if (!capabilityChecked.value) return t('modelProvider.capabilityUnknown')
  return form.supportsMultimodal ? t('modelProvider.capabilityMultimodal') : t('modelProvider.capabilityTextOnly')
})
const capabilityDetailLabel = computed(() => {
  if (verifying.value) return t('modelProvider.capabilityRecognizing')
  if (!capabilityChecked.value) return t('modelProvider.capabilityUnverified')
  return form.supportsMultimodal ? t('modelProvider.imageInputAvailable') : t('modelProvider.imageInputUnavailable')
})
const footerStatusHint = computed(() => {
  if (saving.value) return t('common.saving')
  if (verifying.value) return t('modelProvider.footerVerifyingHint')
  if (!hasRequiredFields.value) return t('modelProvider.footerFillRequiredHint')
  if (needsCapabilityVerification.value) return t('modelProvider.footerNeedVerificationHint')
  if (isEdit.value && !configChanged.value) return t('modelProvider.footerUnchangedHint')
  if (form.supportsMultimodal) return t('modelProvider.footerMultimodalReadyHint')
  return t('modelProvider.footerReadyHint')
})
const verifyButtonLabel = computed(() => {
  if (verifying.value) return t('modelProvider.verifying')
  return capabilityChecked.value ? t('modelProvider.reverifyCapabilities') : t('modelProvider.verifyCapabilities')
})

const buildApiKeys = () => form.api_keys_str.trim().split(/[\n,]+/).map(k => k.trim()).filter(Boolean)

// 输入为有效数字则下发，置空（null/''/NaN）显式以 null 形式下发，
// 让后端 update 流程可以区分"未提供"和"用户主动清空"，从而把 DB 中的旧值清掉。
// 同时后端 sanitize_model_request_kwargs 会把 None 字段从 OpenAI SDK 调用里丢弃。
const optionalNumber = (value) => {
  if (value === null || value === undefined || value === '') return null
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

const buildProviderPayload = () => ({
  name: form.name,
  base_url: form.base_url,
  api_keys: buildApiKeys(),
  model: form.model,
  max_tokens: optionalNumber(form.maxTokens),
  temperature: optionalNumber(form.temperature),
  top_p: optionalNumber(form.topP),
  presence_penalty: optionalNumber(form.presencePenalty),
  max_model_len: optionalNumber(form.maxModelLen),
  supports_multimodal: form.supportsMultimodal,
  supports_structured_output: form.supportsStructuredOutput
})
const resetCapabilityState = () => {
  verified.value = false
  capabilityChecked.value = false
  form.supportsMultimodal = false
  form.supportsStructuredOutput = false
}

// 保存按钮是否可点击
const canSave = computed(() => {
  if (!hasRequiredFields.value) return false
  if (verifying.value || saving.value) return false
  return !needsCapabilityVerification.value
})

const onDialogOpenChange = (open) => {
  if (!open && saving.value) return
  dialogOpen.value = open
}

const handleProviderChange = (val) => {
  selectedProvider.value = val
  if (val === 'Custom') {
    form.name = ''
    form.base_url = ''
    form.model = ''
    resetCapabilityState()
    return
  }
  const provider = MODEL_PROVIDERS.find(p => p.name === val)
  if (provider) {
    form.name = provider.name
    form.base_url = provider.base_url
    form.model = provider.models?.[0] || ''
  }
  resetCapabilityState()
}

const onKeyConfigChange = () => {
  resetCapabilityState()
}

const handleApiKeyChange = (value) => {
  form.api_keys_str = `${value ?? ''}`.split(/\r?\n/, 1)[0]
  onKeyConfigChange()
}

const handleModelQuickPick = (val) => {
  form.model = val
  onKeyConfigChange()
}

const openProviderWebsite = () => {
  if (currentProvider.value?.website) {
    window.open(currentProvider.value.website, '_blank')
  }
}

const openProviderModelList = () => {
  if (currentProvider.value?.model_list_url) {
    window.open(currentProvider.value.model_list_url, '_blank')
  }
}

const fetchProviders = async () => {
  try {
    const res = await listModelProviders()
    providers.value = res || []
  } catch (error) {
    console.error('Failed to fetch providers:', error)
    providers.value = []
  }
}

const getProviderName = (provider) => {
  const match = MODEL_PROVIDERS.find(p => p.base_url === provider.base_url)
  return match ? match.name : 'Custom'
}

const handleCreate = () => {
  isEdit.value = false
  currentId.value = null
  form.name = ''
  selectedProvider.value = ''
  form.base_url = ''
  form.api_keys_str = ''
  form.model = ''
  form.maxTokens = null
  form.temperature = null
  form.topP = null
  form.presencePenalty = null
  form.maxModelLen = null
  form.supportsMultimodal = false
  form.supportsStructuredOutput = false
  verified.value = false
  capabilityChecked.value = false
  showApiKey.value = false
  advancedOpen.value = false
  // 清空原始值
  originalValues.base_url = ''
  originalValues.api_keys_str = ''
  originalValues.model = ''
  saving.value = false
  dialogOpen.value = true
}

const handleEdit = (provider) => {
  isEdit.value = true
  currentId.value = provider.id
  form.name = provider.name

  // Try to match provider
  const known = MODEL_PROVIDERS.find(p => p.base_url === provider.base_url)
  selectedProvider.value = known ? known.name : 'Custom'

  form.base_url = provider.base_url
  // api_keys are not returned in list usually for security?
  // But DTO has them. The backend router returns them.
  // Ideally we should mask them.
  // But for editing we need them.
  // The backend router returns full DTO.
  let keys = provider.api_keys
  if (!Array.isArray(keys)) {
    keys = (typeof keys === 'string' && keys) ? [keys] : []
  }
  form.api_keys_str = keys.join(',')
  form.model = provider.model
  form.maxTokens = provider.max_tokens ?? null
  form.temperature = provider.temperature ?? null
  form.topP = provider.top_p ?? null
  form.presencePenalty = provider.presence_penalty ?? null
  form.maxModelLen = provider.max_model_len ?? null
  form.supportsMultimodal = provider.supports_multimodal ?? false
  form.supportsStructuredOutput = provider.supports_structured_output ?? false

  // 保存原始值用于比较
  originalValues.base_url = provider.base_url
  originalValues.api_keys_str = keys.join(',')
  originalValues.model = provider.model

  // 编辑模式初始状态设为已验证（如果没有变化）
  verified.value = true
  capabilityChecked.value = true
  showApiKey.value = false
  advancedOpen.value = false

  saving.value = false
  dialogOpen.value = true
}

const handleDelete = async (provider) => {
  if (confirm(t('common.confirmDelete'))) {
     try {
       await deleteModelProvider(provider.id)
       toast.success(t('common.deleteSuccess'))
       fetchProviders()
     } catch (error) {
       toast.error(error.message)
     }
  }
}

const handleVerify = async () => {
  if (saving.value) return
  const data = buildProviderPayload()

  if (!data.name || !data.base_url || !data.api_keys.length || !data.model) {
     toast.error(t('common.fillRequired'))
     return
  }

  verifying.value = true
  try {
    const res = await modelProviderAPI.verifyModelProvider(data)
    verified.value = true
    form.supportsMultimodal = Boolean(res?.supports_multimodal)
    form.supportsStructuredOutput = Boolean(res?.supports_structured_output)
    if (form.supportsMultimodal && form.supportsStructuredOutput) {
      toast.success(t('modelProvider.connectionVerifiedMultimodalStructured'))
    } else if (form.supportsMultimodal) {
      toast.success(t('modelProvider.connectionVerifiedMultimodal'))
    } else if (form.supportsStructuredOutput) {
      toast.success(t('modelProvider.connectionVerifiedStructuredOutput'))
    } else {
      toast.success(t('common.verifySuccess'))
    }

    capabilityChecked.value = true
  } catch (error) {
    resetCapabilityState()
    toast.error(error.message || t('modelProvider.verifyFailed'))
  } finally {
    verifying.value = false
  }
}

const submitForm = async () => {
  if (saving.value) return
  const data = buildProviderPayload()

  if (!hasRequiredFields.value) {
    toast.error(t('common.fillRequired'))
    return
  }
  if (needsCapabilityVerification.value) {
    toast.error(t('modelProvider.verifyCapabilitiesFirst'))
    return
  }

  saving.value = true
  try {
    if (isEdit.value) {
      await updateModelProvider(currentId.value, data)
    } else {
      await createModelProvider(data)
    }

    toast.success(t('common.success'))
    dialogOpen.value = false
    fetchProviders()
  } catch (error) {
    toast.error(error.message)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  fetchProviders()
})
</script>
