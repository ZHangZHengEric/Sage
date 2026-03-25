<template>
  <div class="space-y-4">
    <Tabs v-model="activeTab" class="w-full">
      <TabsList class="grid w-full grid-cols-3 lg:grid-cols-6 h-auto">
        <TabsTrigger value="minute">{{ t('cron.minute') }}</TabsTrigger>
        <TabsTrigger value="hourly">{{ t('cron.hourly') }}</TabsTrigger>
        <TabsTrigger value="daily">{{ t('cron.daily') }}</TabsTrigger>
        <TabsTrigger value="weekly">{{ t('cron.weekly') }}</TabsTrigger>
        <TabsTrigger value="monthly">{{ t('cron.monthly') }}</TabsTrigger>
        <TabsTrigger value="custom">{{ t('cron.custom') }}</TabsTrigger>
      </TabsList>

      <div class="mt-4 p-4 border rounded-md min-h-[150px]">
        <!-- Minute -->
        <TabsContent value="minute" class="space-y-4 mt-0">
          <div class="flex items-center gap-2">
            <Label>{{ t('cron.every') }}</Label>
            <Input 
              type="number" 
              min="1" 
              max="59" 
              v-model="minuteState.interval" 
              class="w-20" 
              @change="updateCron"
            />
            <Label>{{ t('cron.minutes') }}</Label>
          </div>
        </TabsContent>

        <!-- Hourly -->
        <TabsContent value="hourly" class="space-y-4 mt-0">
          <div class="flex items-center gap-2 flex-wrap">
            <Label>{{ t('cron.every') }}</Label>
            <Input 
              type="number" 
              min="1" 
              max="23" 
              v-model="hourlyState.interval" 
              class="w-20" 
              @change="updateCron"
            />
            <Label>{{ t('cron.hoursAtMinute') }}</Label>
            <Input 
              type="number" 
              min="0" 
              max="59" 
              v-model="hourlyState.minute" 
              class="w-20" 
              @change="updateCron"
            />
          </div>
        </TabsContent>

        <!-- Daily -->
        <TabsContent value="daily" class="space-y-4 mt-0">
          <div class="flex items-center gap-2">
            <Label>{{ t('cron.atTime') }}</Label>
            <div class="flex items-center gap-1">
              <Select v-model="dailyState.hour" @update:modelValue="updateCron">
                <SelectTrigger class="w-[70px]">
                  <SelectValue placeholder="HH" />
                </SelectTrigger>
                <SelectContent class="max-h-[200px] overflow-y-auto">
                  <SelectItem v-for="h in 24" :key="h-1" :value="(h-1).toString()">
                    {{ (h-1).toString().padStart(2, '0') }}
                  </SelectItem>
                </SelectContent>
              </Select>
              <span>:</span>
              <Select v-model="dailyState.minute" @update:modelValue="updateCron">
                <SelectTrigger class="w-[70px]">
                  <SelectValue placeholder="MM" />
                </SelectTrigger>
                <SelectContent class="max-h-[200px] overflow-y-auto">
                  <SelectItem v-for="m in 60" :key="m-1" :value="(m-1).toString()">
                    {{ (m-1).toString().padStart(2, '0') }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </TabsContent>

        <!-- Weekly -->
        <TabsContent value="weekly" class="space-y-4 mt-0">
          <div class="space-y-3">
            <div class="flex items-center gap-2">
              <Label>{{ t('cron.atTime') }}</Label>
              <div class="flex items-center gap-1">
                <Select v-model="weeklyState.hour" @update:modelValue="updateCron">
                  <SelectTrigger class="w-[70px]">
                    <SelectValue placeholder="HH" />
                  </SelectTrigger>
                  <SelectContent class="max-h-[200px] overflow-y-auto">
                    <SelectItem v-for="h in 24" :key="h-1" :value="(h-1).toString()">
                      {{ (h-1).toString().padStart(2, '0') }}
                    </SelectItem>
                  </SelectContent>
                </Select>
                <span>:</span>
                <Select v-model="weeklyState.minute" @update:modelValue="updateCron">
                  <SelectTrigger class="w-[70px]">
                    <SelectValue placeholder="MM" />
                  </SelectTrigger>
                  <SelectContent class="max-h-[200px] overflow-y-auto">
                    <SelectItem v-for="m in 60" :key="m-1" :value="(m-1).toString()">
                      {{ (m-1).toString().padStart(2, '0') }}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            
            <div class="space-y-2">
              <Label>{{ t('cron.onDays') }}</Label>
              <div class="flex flex-wrap gap-4">
                <div v-for="(day, index) in daysOfWeek" :key="index" class="flex items-center space-x-2">
                  <Checkbox 
                    :id="`day-${index}`" 
                    :checked="weeklyState.days.includes(index)"
                    @update:checked="(checked) => updateWeeklyDay(index, checked)"
                  />
                  <Label :for="`day-${index}`" class="cursor-pointer">{{ day }}</Label>
                </div>
              </div>
            </div>
          </div>
        </TabsContent>

        <!-- Monthly -->
        <TabsContent value="monthly" class="space-y-4 mt-0">
          <div class="flex items-center gap-2 flex-wrap">
            <Label>{{ t('cron.onDay') }}</Label>
            <Input 
              type="number" 
              min="1" 
              max="31" 
              v-model="monthlyState.day" 
              class="w-20" 
              @change="updateCron"
            />
            <Label>{{ t('cron.ofMonthAt') }}</Label>
            <div class="flex items-center gap-1">
              <Select v-model="monthlyState.hour" @update:modelValue="updateCron">
                <SelectTrigger class="w-[70px]">
                  <SelectValue placeholder="HH" />
                </SelectTrigger>
                <SelectContent class="max-h-[200px] overflow-y-auto">
                  <SelectItem v-for="h in 24" :key="h-1" :value="(h-1).toString()">
                    {{ (h-1).toString().padStart(2, '0') }}
                  </SelectItem>
                </SelectContent>
              </Select>
              <span>:</span>
              <Select v-model="monthlyState.minute" @update:modelValue="updateCron">
                <SelectTrigger class="w-[70px]">
                  <SelectValue placeholder="MM" />
                </SelectTrigger>
                <SelectContent class="max-h-[200px] overflow-y-auto">
                  <SelectItem v-for="m in 60" :key="m-1" :value="(m-1).toString()">
                    {{ (m-1).toString().padStart(2, '0') }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </TabsContent>

        <!-- Custom -->
        <TabsContent value="custom" class="space-y-4 mt-0">
          <div class="grid gap-2">
            <Label>{{ t('cron.expression') }}</Label>
            <Input v-model="customCron" @input="updateCronFromCustom" placeholder="* * * * *" />
            <p class="text-xs text-muted-foreground">{{ t('scheduledTask.cronHint') }}</p>
          </div>
        </TabsContent>
      </div>
    </Tabs>
    
    <div class="flex items-center justify-between text-sm bg-muted/30 p-2 rounded">
      <div class="font-mono">{{ modelValue }}</div>
      <div class="text-muted-foreground">{{ formattedCron }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, watch, computed, onMounted } from 'vue'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useLanguage } from '@/utils/i18n'
import cronstrue from 'cronstrue/i18n'

const props = defineProps({
  modelValue: {
    type: String,
    default: '* * * * *'
  }
})

const emit = defineEmits(['update:modelValue'])
const { t, isZhCN } = useLanguage()

const activeTab = ref('custom')
const customCron = ref(props.modelValue)

// State for each tab
const minuteState = reactive({ interval: 5 })
const hourlyState = reactive({ interval: 1, minute: 0 })
const dailyState = reactive({ hour: '0', minute: '0' })
const weeklyState = reactive({ days: [], hour: '0', minute: '0' })
const monthlyState = reactive({ day: 1, hour: '0', minute: '0' })

const daysOfWeek = computed(() => [
  t('cron.sun'), t('cron.mon'), t('cron.tue'), t('cron.wed'), t('cron.thu'), t('cron.fri'), t('cron.sat')
])

const formattedCron = computed(() => {
  try {
    return cronstrue.toString(props.modelValue, { locale: isZhCN.value ? 'zh_CN' : 'en', use24HourTimeFormat: true })
  } catch (e) {
    return ''
  }
})

// Parse cron string to state
const parseCron = (cron) => {
  if (!cron) return

  const parts = cron.split(' ')
  if (parts.length !== 5) {
    activeTab.value = 'custom'
    customCron.value = cron
    return
  }

  const [min, hour, dayOfMonth, month, dayOfWeek] = parts

  // Check for Minute: */5 * * * *
  if (min.startsWith('*/') && hour === '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    activeTab.value = 'minute'
    minuteState.interval = parseInt(min.substring(2))
    return
  }

  // Check for Hourly: 0 */1 * * * or 0 1-23/1 * * * (simplified: m */h * * *)
  // Standard cron for every N hours: 0 */N * * *
  if (hour.startsWith('*/') && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    activeTab.value = 'hourly'
    hourlyState.interval = parseInt(hour.substring(2))
    hourlyState.minute = parseInt(min)
    return
  }

  // Check for Daily: m h * * *
  if (!min.includes('*') && !min.includes('/') && !hour.includes('*') && !hour.includes('/') && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    activeTab.value = 'daily'
    dailyState.hour = hour
    dailyState.minute = min
    return
  }

  // Check for Weekly: m h * * d,d,d
  if (!min.includes('*') && !min.includes('/') && !hour.includes('*') && !hour.includes('/') && dayOfMonth === '*' && month === '*') {
    activeTab.value = 'weekly'
    weeklyState.hour = hour
    weeklyState.minute = min
    if (dayOfWeek === '*') {
      weeklyState.days = [0, 1, 2, 3, 4, 5, 6]
    } else {
      weeklyState.days = dayOfWeek.split(',').map(d => parseInt(d))
    }
    return
  }

  // Check for Monthly: m h d * *
  if (!min.includes('*') && !min.includes('/') && !hour.includes('*') && !hour.includes('/') && !dayOfMonth.includes('*') && month === '*' && dayOfWeek === '*') {
    activeTab.value = 'monthly'
    monthlyState.hour = hour
    monthlyState.minute = min
    monthlyState.day = parseInt(dayOfMonth)
    return
  }

  // Default to custom
  activeTab.value = 'custom'
  customCron.value = cron
}

const generateCron = () => {
  let cron = '* * * * *'
  
  switch (activeTab.value) {
    case 'minute':
      cron = `*/${minuteState.interval} * * * *`
      break
    case 'hourly':
      cron = `${hourlyState.minute} */${hourlyState.interval} * * *`
      break
    case 'daily':
      cron = `${dailyState.minute} ${dailyState.hour} * * *`
      break
    case 'weekly':
      const days = weeklyState.days.length > 0 ? weeklyState.days.sort().join(',') : '*'
      cron = `${weeklyState.minute} ${weeklyState.hour} * * ${days}`
      break
    case 'monthly':
      cron = `${monthlyState.minute} ${monthlyState.hour} ${monthlyState.day} * *`
      break
    case 'custom':
      cron = customCron.value
      break
  }
  
  return cron
}

const updateCron = () => {
  const newCron = generateCron()
  if (newCron !== props.modelValue) {
    emit('update:modelValue', newCron)
  }
}

const updateCronFromCustom = () => {
  emit('update:modelValue', customCron.value)
}

const updateWeeklyDay = (dayIndex, checked) => {
  if (checked) {
    if (!weeklyState.days.includes(dayIndex)) {
      weeklyState.days.push(dayIndex)
    }
  } else {
    weeklyState.days = weeklyState.days.filter(d => d !== dayIndex)
  }
  updateCron()
}

watch(() => activeTab.value, (newTab) => {
  if (newTab !== 'custom') {
    updateCron()
  } else {
    customCron.value = props.modelValue
  }
})

watch(() => props.modelValue, (newVal) => {
  if (activeTab.value === 'custom' && newVal !== customCron.value) {
    customCron.value = newVal
  }
  // Only re-parse if the generated cron doesn't match (avoid loop)
  const currentGenerated = generateCron()
  if (newVal !== currentGenerated) {
    parseCron(newVal)
  }
}, { immediate: true })

onMounted(() => {
  parseCron(props.modelValue)
})
</script>