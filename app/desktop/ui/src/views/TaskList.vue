<template>
  <div class="h-full overflow-y-auto bg-background">
    <div class="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-6">
      <div class="flex items-center justify-between gap-4 border-b border-border/55 pb-3">
        <div class="min-w-0">
          <h1 class="text-[15px] font-semibold tracking-tight text-foreground">{{ t('scheduledTask.menuTitle') }}</h1>
          <p class="text-[11px] text-muted-foreground">
            {{ activeTab === 'recurring'
              ? t('scheduledTask.recurringCount', { count: tasks.length })
              : t('scheduledTask.oneTimeCount', { count: oneTimeTasks.length })
            }}
          </p>
        </div>

        <Tabs v-model="activeTab" class="flex-none">
          <TabsList class="bg-muted/50">
            <TabsTrigger value="recurring" class="gap-2">
              <Repeat class="w-4 h-4" />
              {{ t('scheduledTask.title') }}
            </TabsTrigger>
            <TabsTrigger value="one-time" class="gap-2">
              <Clock class="w-4 h-4" />
              {{ t('scheduledTask.oneTimeTitle') }}
            </TabsTrigger>
          </TabsList>
        </Tabs>

        <Button class="h-9 rounded-xl px-3.5" @click="handleCreate" v-if="activeTab === 'recurring'">
          <Plus class="mr-2 h-4 w-4" />
          {{ t('scheduledTask.createTitle') }}
        </Button>
        <Button class="h-9 rounded-xl px-3.5" @click="handleCreateOneTime" v-else>
          <Plus class="mr-2 h-4 w-4" />
          {{ t('scheduledTask.createOneTime') }}
        </Button>
      </div>

      <Tabs v-model="activeTab" class="w-full flex flex-col flex-1 min-h-0">
        <TabsList class="hidden">
          <TabsTrigger value="recurring" />
          <TabsTrigger value="one-time" />
        </TabsList>

        <!-- Recurring Tasks - Task Ticket Style -->
        <TabsContent value="recurring" class="flex-1 overflow-hidden">
          <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 overflow-y-auto h-full pb-4 content-start">
          <!-- Task Ticket Card -->
          <div
            v-for="task in tasks"
            :key="task.id"
            class="group relative bg-card border rounded-lg overflow-hidden transition-all duration-300 hover:shadow-lg hover:border-primary/40 cursor-pointer flex flex-col"
            :class="{ 'opacity-60': !task.enabled }"
          >
            <!-- Ticket Header with perforation effect -->
            <div class="relative bg-gradient-to-r from-primary/10 via-primary/5 to-transparent px-4 py-3 border-b border-dashed flex-shrink-0">
              <!-- Task ID badge -->
              <div class="absolute top-2 right-2">
                <span class="text-[10px] font-mono text-muted-foreground bg-muted/50 px-1.5 py-0.5 rounded">
                  #{{ String(task.id).slice(-6).toUpperCase() }}
                </span>
              </div>

              <div class="flex items-start gap-3 pr-16">
                <!-- Checkbox icon for task feel -->
                <div class="mt-0.5">
                  <div
                    class="w-5 h-5 rounded border-2 flex items-center justify-center transition-colors"
                    :class="task.enabled ? 'bg-green-500 border-green-500' : 'border-muted-foreground'"
                  >
                    <Check v-if="task.enabled" class="w-3 h-3 text-white" />
                  </div>
                </div>

                <div class="flex-1 min-w-0">
                  <h3 class="text-sm font-bold leading-tight truncate" :title="task.name">
                    {{ task.name }}
                  </h3>
                </div>
              </div>
            </div>

            <!-- Ticket Body - 可滚动区域 -->
            <div class="px-4 py-3 flex-1 overflow-hidden">
              <p class="text-xs text-muted-foreground line-clamp-3 leading-relaxed mb-3">
                {{ task.description || t('scheduledTask.noDescription') }}
              </p>

              <!-- Agent assignment line -->
              <div class="flex items-center gap-2 text-xs border-t border-dashed pt-3">
                <span class="text-muted-foreground">{{ t('scheduledTask.executor') }}:</span>
                <div class="flex items-center gap-1.5">
                  <Avatar class="h-5 w-5">
                    <AvatarImage :src="getAgentAvatar(task.agent_id)" />
                    <AvatarFallback class="text-[10px]">{{ getAgentName(task.agent_id).charAt(0) }}</AvatarFallback>
                  </Avatar>
                  <span class="font-medium">{{ getAgentName(task.agent_id) }}</span>
                </div>
              </div>
            </div>

            <!-- Ticket Footer with schedule info - 始终显示 -->
            <div class="px-4 py-2 bg-muted/30 border-t flex items-center justify-between gap-2 flex-shrink-0">
              <div class="flex items-center gap-2 min-w-0 flex-1">
                <Clock class="w-3.5 h-3.5 text-primary flex-shrink-0" />
                <span class="text-xs font-medium truncate">{{ formatCron(task.cron_expression) }}</span>
              </div>

              <div class="flex items-center gap-0.5 relative z-10 flex-shrink-0">
                <Button variant="ghost" size="icon" class="h-7 w-7 flex-shrink-0" @click.stop="handleHistory(task)">
                  <History class="h-3.5 w-3.5" />
                </Button>
                <Button variant="ghost" size="icon" class="h-7 w-7 flex-shrink-0" @click.stop="handleEdit(task)">
                  <Edit class="h-3.5 w-3.5" />
                </Button>
                <Button variant="ghost" size="icon" class="h-7 w-7 text-destructive hover:text-destructive flex-shrink-0" @click.stop="handleDelete(task)">
                  <Trash2 class="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>

            <!-- Last execution timestamp - 始终显示 -->
            <div class="px-4 py-1.5 bg-muted/50 text-[10px] text-muted-foreground border-t flex-shrink-0">
              <span v-if="task.last_executed_at">
                {{ t('scheduledTask.lastExecuted') }}: {{ formatDateShort(task.last_executed_at) }}
              </span>
              <span v-else>{{ t('scheduledTask.neverExecuted') }}</span>
            </div>
          </div>

          <!-- Empty State -->
          <div v-if="tasks.length === 0" class="col-span-full flex flex-col items-center justify-center py-20 text-muted-foreground">
            <div class="w-16 h-16 rounded-full bg-muted/50 flex items-center justify-center mb-4">
              <Repeat class="w-8 h-8 opacity-50" />
            </div>
            <p class="text-lg font-medium">{{ t('scheduledTask.noRecurringTasks') }}</p>
            <p class="text-sm mt-1">{{ t('scheduledTask.createHint') }}</p>
          </div>
        </div>
      </TabsContent>

      <!-- One-Time Tasks - Task Ticket Style -->
      <TabsContent value="one-time" class="flex-1 overflow-hidden">
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 overflow-y-auto h-full pb-4 content-start">
          <!-- Task Ticket Card -->
          <div
            v-for="task in oneTimeTasks"
            :key="task.id"
            class="group relative bg-card border rounded-lg overflow-hidden transition-all duration-300 hover:shadow-lg hover:border-primary/40 flex flex-col"
          >
            <!-- Ticket Header with status color -->
            <div
              class="relative px-4 py-3 border-b border-dashed flex-shrink-0"
              :class="{
                'bg-green-500/10': task.status === 'completed',
                'bg-blue-500/10': task.status === 'pending',
                'bg-yellow-500/10': task.status === 'processing',
                'bg-red-500/10': task.status === 'failed'
              }"
            >
              <!-- Task ID badge -->
              <div class="absolute top-2 right-2">
                <span class="text-[10px] font-mono text-muted-foreground bg-muted/50 px-1.5 py-0.5 rounded">
                  #{{ String(task.id).slice(-6).toUpperCase() }}
                </span>
              </div>

              <div class="flex items-start gap-3 pr-16">
                <!-- Status checkbox -->
                <div class="mt-0.5">
                  <div
                    class="w-5 h-5 rounded border-2 flex items-center justify-center transition-colors"
                    :class="{
                      'bg-green-500 border-green-500': task.status === 'completed',
                      'bg-blue-500 border-blue-500': task.status === 'pending',
                      'bg-yellow-500 border-yellow-500': task.status === 'processing',
                      'bg-red-500 border-red-500': task.status === 'failed',
                      'border-muted-foreground': task.status === 'cancelled'
                    }"
                  >
                    <Check v-if="task.status === 'completed'" class="w-3 h-3 text-white" />
                    <Clock v-else-if="task.status === 'pending'" class="w-3 h-3 text-white" />
                    <Loader2 v-else-if="task.status === 'processing'" class="w-3 h-3 text-white animate-spin" />
                    <X v-else-if="task.status === 'failed'" class="w-3 h-3 text-white" />
                  </div>
                </div>

                <div class="flex-1 min-w-0">
                  <h3 class="text-sm font-bold leading-tight truncate" :title="task.name">
                    {{ task.name }}
                  </h3>
                </div>
              </div>
            </div>

            <!-- Ticket Body - 可滚动区域 -->
            <div class="px-4 py-3 flex-1 overflow-hidden">
              <p class="text-xs text-muted-foreground line-clamp-3 leading-relaxed mb-3">
                {{ task.description || t('scheduledTask.noDescription') }}
              </p>

              <!-- Agent assignment line -->
              <div class="flex items-center gap-2 text-xs border-t border-dashed pt-3">
                <span class="text-muted-foreground">{{ t('scheduledTask.executor') }}:</span>
                <div class="flex items-center gap-1.5">
                  <Avatar class="h-5 w-5">
                    <AvatarImage :src="getAgentAvatar(task.agent_id)" />
                    <AvatarFallback class="text-[10px]">{{ getAgentName(task.agent_id).charAt(0) }}</AvatarFallback>
                  </Avatar>
                  <span class="font-medium">{{ getAgentName(task.agent_id) }}</span>
                </div>
              </div>
            </div>

            <!-- Ticket Footer with execute time - 始终显示 -->
            <div class="px-4 py-2 bg-muted/30 border-t flex items-center justify-between gap-2 flex-shrink-0">
              <div class="flex items-center gap-2 min-w-0 flex-1">
                <CalendarClock class="w-3.5 h-3.5 text-primary flex-shrink-0" />
                <span class="text-xs font-medium truncate">{{ formatDate(task.execute_at) }}</span>
              </div>

              <div class="flex items-center gap-0.5 relative z-10 flex-shrink-0">
                <Button
                  v-if="task.session_id"
                  variant="ghost"
                  size="icon"
                  class="h-7 w-7 flex-shrink-0"
                  @click.stop="handleViewSession(task.session_id)"
                >
                  <MessageSquare class="h-3.5 w-3.5" />
                </Button>
                <Button variant="ghost" size="icon" class="h-7 w-7 flex-shrink-0" @click.stop="handleEditOneTime(task)">
                  <Edit class="h-3.5 w-3.5" />
                </Button>
                <Button variant="ghost" size="icon" class="h-7 w-7 text-destructive hover:text-destructive flex-shrink-0" @click.stop="handleDeleteOneTime(task)">
                  <Trash2 class="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>

            <!-- Completion timestamp - 始终显示 -->
            <div class="px-4 py-1.5 bg-muted/50 text-[10px] text-muted-foreground border-t flex-shrink-0">
              <span v-if="task.completed_at">
                {{ t('scheduledTask.completedAt') }}: {{ formatDateShort(task.completed_at) }}
              </span>
              <span v-else-if="task.status === 'pending'">{{ t('scheduledTask.statusPending') }}</span>
              <span v-else-if="task.status === 'processing'">{{ t('scheduledTask.statusProcessing') }}</span>
              <span v-else-if="task.status === 'failed'">{{ t('scheduledTask.statusFailed') }}</span>
            </div>
          </div>

          <!-- Empty State -->
          <div v-if="oneTimeTasks.length === 0" class="col-span-full flex flex-col items-center justify-center py-20 text-muted-foreground">
            <div class="w-16 h-16 rounded-full bg-muted/50 flex items-center justify-center mb-4">
              <Clock class="w-8 h-8 opacity-50" />
            </div>
            <p class="text-lg font-medium">{{ t('scheduledTask.noOneTimeTasks') }}</p>
            <p class="text-sm mt-1">{{ t('scheduledTask.createHint') }}</p>
          </div>
        </div>
      </TabsContent>
    </Tabs>

    <!-- Create/Edit Dialog - Two Column Layout -->
    <Dialog :open="dialogOpen" @update:open="dialogOpen = $event">
      <DialogContent class="sm:max-w-[700px] max-h-[90vh] overflow-hidden">
        <DialogHeader>
          <DialogTitle>{{ isEdit ? t('scheduledTask.editTitle') : t('scheduledTask.createTitle') }}</DialogTitle>
        </DialogHeader>
        <div class="grid grid-cols-2 gap-6 py-4 overflow-y-auto max-h-[calc(90vh-180px)]">
          <!-- Left Column - Basic Info -->
          <div class="space-y-4">
            <div class="text-sm font-medium text-muted-foreground mb-2">{{ t('scheduledTask.basicInfo') }}</div>
            
            <div class="space-y-2">
              <Label>{{ t('scheduledTask.name') }} <span class="text-destructive">*</span></Label>
              <Input v-model="form.name" :placeholder="t('scheduledTask.namePlaceholder')" />
            </div>
            
            <div class="space-y-2">
              <Label>{{ t('scheduledTask.description') }}</Label>
              <Textarea v-model="form.description" :placeholder="t('scheduledTask.descPlaceholder')" rows="8" class="min-h-[160px] resize-y" />
            </div>
            
            <div class="space-y-2">
              <Label>{{ t('scheduledTask.agent') }} <span class="text-destructive">*</span></Label>
              <Select v-model="form.agent_id">
                <SelectTrigger>
                  <SelectValue :placeholder="t('scheduledTask.agentPlaceholder')" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="agent in agents" :key="agent.id" :value="agent.id">
                    <div class="flex items-center gap-2">
                      <img :src="getAgentAvatar(agent.id)" class="w-5 h-5 rounded" />
                      {{ agent.name }}
                    </div>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            
            <div class="flex items-center gap-3 pt-2">
              <Label class="text-sm">{{ t('scheduledTask.enabled') }}</Label>
              <Switch :checked="form.enabled" @update:checked="(val) => form.enabled = val" />
            </div>
          </div>

          <!-- Right Column - Schedule -->
          <div class="space-y-4">
            <div class="text-sm font-medium text-muted-foreground mb-2">{{ t('scheduledTask.executionPlan') }}</div>
            
            <div class="space-y-2">
              <Label>{{ t('scheduledTask.cron') }} <span class="text-destructive">*</span></Label>
              <CronEditor v-model="form.cron_expression" />
            </div>
            
            <!-- Preview -->
            <div class="bg-muted/50 rounded-lg p-4 space-y-2">
              <div class="text-xs text-muted-foreground">{{ t('scheduledTask.executionPreview') }}</div>
              <div class="text-sm font-medium">{{ formatCron(form.cron_expression) }}</div>
              <div class="text-xs font-mono text-muted-foreground">{{ form.cron_expression }}</div>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="dialogOpen = false">{{ t('common.cancel') }}</Button>
          <Button @click="submitForm">{{ t('common.save') }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- One-Time Task Dialog - Two Column Layout -->
    <Dialog :open="oneTimeDialogOpen" @update:open="oneTimeDialogOpen = $event">
      <DialogContent class="sm:max-w-[700px] max-h-[90vh] overflow-hidden">
        <DialogHeader>
          <DialogTitle>{{ oneTimeIsEdit ? t('scheduledTask.editTitle') : t('scheduledTask.createOneTime') }}</DialogTitle>
        </DialogHeader>
        <div class="grid grid-cols-2 gap-6 py-4 overflow-y-auto max-h-[calc(90vh-180px)]">
          <!-- Left Column - Basic Info -->
          <div class="space-y-4">
            <div class="text-sm font-medium text-muted-foreground mb-2">{{ t('scheduledTask.basicInfo') }}</div>
            
            <div class="space-y-2">
              <Label>{{ t('scheduledTask.name') }} <span class="text-destructive">*</span></Label>
              <Input v-model="oneTimeForm.name" :placeholder="t('scheduledTask.namePlaceholder')" />
            </div>
            
            <div class="space-y-2">
              <Label>{{ t('scheduledTask.description') }}</Label>
              <Textarea v-model="oneTimeForm.description" :placeholder="t('scheduledTask.descPlaceholder')" rows="8" class="min-h-[160px] resize-y" />
            </div>
            
            <div class="space-y-2">
              <Label>{{ t('scheduledTask.agent') }} <span class="text-destructive">*</span></Label>
              <Select v-model="oneTimeForm.agent_id">
                <SelectTrigger>
                  <SelectValue :placeholder="t('scheduledTask.agentPlaceholder')" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="agent in agents" :key="agent.id" :value="agent.id">
                    <div class="flex items-center gap-2">
                      <img :src="getAgentAvatar(agent.id)" class="w-5 h-5 rounded" />
                      {{ agent.name }}
                    </div>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <!-- Right Column - Schedule -->
          <div class="space-y-4">
            <div class="text-sm font-medium text-muted-foreground mb-2">{{ t('scheduledTask.executionTime') }}</div>
            
            <div class="space-y-2">
              <Label>{{ t('scheduledTask.executeAt') }} <span class="text-destructive">*</span></Label>
              <Input type="datetime-local" v-model="oneTimeForm.execute_at" :min="minDateTime" class="w-full" />
            </div>
            
            <!-- Preview -->
            <div class="bg-muted/50 rounded-lg p-4 space-y-2">
              <div class="text-xs text-muted-foreground">{{ t('scheduledTask.plannedExecutionTime') }}</div>
              <div class="text-sm font-medium">{{ oneTimeForm.execute_at ? formatDate(oneTimeForm.execute_at) : t('scheduledTask.selectTime') }}</div>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="oneTimeDialogOpen = false">{{ t('common.cancel') }}</Button>
          <Button @click="submitOneTimeForm">{{ t('common.save') }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- History Dialog -->
    <Dialog :open="historyOpen" @update:open="historyOpen = $event">
      <DialogContent class="sm:max-w-[800px] flex flex-col max-h-[80vh]">
        <DialogHeader>
          <DialogTitle>{{ t('scheduledTask.historyTitle') }}</DialogTitle>
        </DialogHeader>
        <div class="flex-1 overflow-auto py-4">
           <div class="space-y-3">
             <Card v-for="item in historyList" :key="item.id" class="p-4">
               <div class="flex items-center justify-between">
                 <div class="flex items-center gap-4">
                   <Badge :variant="getStatusVariant(item.status)">{{ item.status }}</Badge>
                   <span class="text-sm">{{ formatDate(item.execute_at) }}</span>
                   <span v-if="item.retry_count > 0" class="text-xs text-muted-foreground">
                     {{ t('scheduledTask.retryTimes').replace('{count}', item.retry_count) }}
                   </span>
                 </div>
                 <Button 
                   v-if="item.session_id" 
                   variant="ghost" 
                   size="sm" 
                   @click="handleViewSession(item.session_id)"
                   class="gap-2"
                 >
                   <MessageSquare class="h-4 w-4" />
                   {{ t('scheduledTask.viewSession') }}
                 </Button>
               </div>
               <div v-if="item.completed_at" class="text-xs text-muted-foreground mt-2">
                 {{ t('scheduledTask.completedAt') }}: {{ formatDate(item.completed_at) }}
               </div>
             </Card>
             <div v-if="historyList.length === 0" class="text-center py-8 text-muted-foreground">
               {{ t('scheduledTask.noHistory') }}
             </div>
           </div>
        </div>
      </DialogContent>
    </Dialog>
    <AppConfirmDialog ref="confirmDialogRef" />
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed, watch } from 'vue'
import { Plus, Edit, Trash2, History, MessageSquare, Repeat, Clock, CalendarClock, Check, Loader2, X } from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from '@/components/ui/avatar'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { useLanguage } from '@/utils/i18n'
import { taskAPI } from '@/api/task'
import { agentAPI } from '@/api/agent'
import { toast } from 'vue-sonner'
import cronstrue from 'cronstrue/i18n'
import CronEditor from '@/components/CronEditor.vue'
import AppConfirmDialog from '@/components/AppConfirmDialog.vue'

const router = useRouter()
const { t, isZhCN } = useLanguage()
const tasks = ref([])
const oneTimeTasks = ref([])
const historyList = ref([])
const agents = ref([])
const dialogOpen = ref(false)
const oneTimeDialogOpen = ref(false)
const historyOpen = ref(false)
const isEdit = ref(false)
const currentId = ref(null)
const oneTimeIsEdit = ref(false)
const currentOneTimeId = ref(null)
const activeTab = ref('recurring')
const minDateTime = ref('')
const confirmDialogRef = ref(null)

const form = reactive({
  name: '',
  description: '',
  agent_id: '',
  cron_expression: '',
  enabled: true
})

const oneTimeForm = reactive({
  name: '',
  description: '',
  agent_id: '',
  execute_at: ''
})

const toLocalISO = (date) => {
  const pad = (num) => (num < 10 ? '0' + num : num)
  const year = date.getFullYear()
  const month = pad(date.getMonth() + 1)
  const day = pad(date.getDate())
  const hours = pad(date.getHours())
  const minutes = pad(date.getMinutes())
  return `${year}-${month}-${day}T${hours}:${minutes}`
}

const fetchAgents = async () => {
  try {
    const res = await agentAPI.getAgents()
    // request.js 已经处理了响应，返回的是 response.data
    if (Array.isArray(res)) {
      agents.value = res
    } else if (res && Array.isArray(res.data)) {
      agents.value = res.data
    } else {
      agents.value = []
    }
  } catch (error) {
    console.error('Failed to fetch agents:', error)
    agents.value = []
  }
}

const getAgentName = (agentId) => {
  const agent = agents.value.find(a => a.id === agentId)
  return agent ? agent.name : agentId
}

const getAgentAvatar = (agentId) => {
  return `https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=${encodeURIComponent(agentId)}`
}

const fetchTasks = async () => {
  try {
    const res = await taskAPI.getRecurringTasks()
    tasks.value = res.items || []
  } catch (error) {
    console.error('Failed to fetch tasks:', error)
    toast.error(t('scheduledTask.fetchTasksFailed'))
  }
}

const fetchOneTimeTasks = async () => {
  try {
    const res = await taskAPI.getOneTimeTasks()
    oneTimeTasks.value = res.items || []
  } catch (error) {
    console.error('Failed to fetch one-time tasks:', error)
    toast.error(t('scheduledTask.fetchOneTimeTasksFailed'))
  }
}

const handleCreate = () => {
  isEdit.value = false
  currentId.value = null
  form.name = ''
  form.description = ''
  form.agent_id = ''
  form.cron_expression = '0 9 * * *'
  form.enabled = true
  dialogOpen.value = true
}

const handleCreateOneTime = () => {
  oneTimeIsEdit.value = false
  currentOneTimeId.value = null
  oneTimeForm.name = ''
  oneTimeForm.description = ''
  oneTimeForm.agent_id = ''
  
  const now = new Date()
  minDateTime.value = toLocalISO(now)
  now.setHours(now.getHours() + 1)
  oneTimeForm.execute_at = toLocalISO(now)
  oneTimeDialogOpen.value = true
}

const submitOneTimeForm = async () => {
  if (!oneTimeForm.name || !oneTimeForm.agent_id || !oneTimeForm.execute_at) {
    toast.error(t('common.fillRequired'))
    return
  }

  const selectedDate = new Date(oneTimeForm.execute_at)
  if (!oneTimeIsEdit.value && selectedDate <= new Date()) {
    toast.error(t('scheduledTask.futureTimeRequired'))
    return
  }

  try {
    const payload = {
      ...oneTimeForm,
      execute_at: oneTimeForm.execute_at
    }
    if (oneTimeIsEdit.value) {
      await taskAPI.updateOneTimeTask(currentOneTimeId.value, payload)
    } else {
      await taskAPI.createOneTimeTask(payload)
    }
    toast.success(t('common.success'))
    oneTimeDialogOpen.value = false
    fetchOneTimeTasks()
  } catch (error) {
    toast.error(error.message)
  }
}

const handleEditOneTime = (task) => {
  oneTimeIsEdit.value = true
  currentOneTimeId.value = task.id
  oneTimeForm.name = task.name
  oneTimeForm.description = task.description
  oneTimeForm.agent_id = task.agent_id
  const safeDate = typeof task.execute_at === 'string' ? task.execute_at.replace(' ', 'T') : task.execute_at
  oneTimeForm.execute_at = toLocalISO(new Date(safeDate))
  minDateTime.value = toLocalISO(new Date())
  oneTimeDialogOpen.value = true
}

const handleDeleteOneTime = async (task) => {
  const confirmed = await confirmDialogRef.value.confirm(t('common.confirmDelete'))
  if (!confirmed) return
  try {
    await taskAPI.deleteOneTimeTask(task.id)
    fetchOneTimeTasks()
  } catch (error) {
    toast.error(error.message)
  }
}

const handleEdit = (task) => {
  isEdit.value = true
  currentId.value = task.id
  form.name = task.name
  form.description = task.description
  form.agent_id = task.agent_id
  form.cron_expression = task.cron_expression
  form.enabled = task.enabled
  dialogOpen.value = true
}

const handleDelete = async (task) => {
  const confirmed = await confirmDialogRef.value.confirm(t('common.confirmDelete'))
  if (!confirmed) return
  try {
    await taskAPI.deleteRecurringTask(task.id)
    fetchTasks()
  } catch (error) {
    toast.error(error.message)
  }
}

const handleToggle = async (task, checked) => {
  try {
    await taskAPI.toggleTaskStatus(task.id, checked)
    task.enabled = checked
    toast.success(t('common.success'))
  } catch (error) {
    toast.error(error.message)
    task.enabled = !checked
  }
}

const handleHistory = async (task) => {
  try {
    const res = await taskAPI.getTaskHistory(task.id)
    historyList.value = res.items || []
    historyOpen.value = true
  } catch (error) {
    toast.error(t('scheduledTask.fetchHistoryFailed'))
  }
}

const handleViewSession = (sessionId) => {
  router.push({
    path: '/agent/chat',
    query: { session_id: sessionId }
  })
}

const submitForm = async () => {
  if (!form.name || !form.agent_id || !form.cron_expression) {
    toast.error(t('common.fillRequired'))
    return
  }

  try {
    if (isEdit.value) {
      await taskAPI.updateRecurringTask(currentId.value, form)
    } else {
      await taskAPI.createRecurringTask(form)
    }
    toast.success(t('common.success'))
    dialogOpen.value = false
    fetchTasks()
  } catch (error) {
    toast.error(error.message)
  }
}

const getStatusVariant = (status) => {
  switch (status) {
    case 'completed': return 'default'
    case 'failed': return 'destructive'
    case 'processing': return 'secondary'
    case 'pending': return 'outline'
    default: return 'outline'
  }
}

const getStatusLabel = (status) => {
  const labels = {
    'completed': t('scheduledTask.statusCompleted'),
    'failed': t('scheduledTask.statusFailed'),
    'processing': t('scheduledTask.statusProcessing'),
    'pending': t('scheduledTask.statusPending')
  }
  return labels[status] || status
}

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  try {
    const isoStr = typeof dateStr === 'string' ? dateStr.replace(' ', 'T') : dateStr
    return new Date(isoStr).toLocaleString()
  } catch (e) {
    return dateStr
  }
}

const formatDateShort = (dateStr) => {
  if (!dateStr) return '-'
  try {
    const isoStr = typeof dateStr === 'string' ? dateStr.replace(' ', 'T') : dateStr
    const date = new Date(isoStr)
    const now = new Date()
    const diffMs = now - date
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)
    
    if (diffMins < 1) return t('scheduledTask.justNow')
    if (diffMins < 60) return t('scheduledTask.minutesAgo').replace('{count}', diffMins)
    if (diffHours < 24) return t('scheduledTask.hoursAgo').replace('{count}', diffHours)
    if (diffDays < 7) return t('scheduledTask.daysAgo').replace('{count}', diffDays)
    
    return date.toLocaleDateString()
  } catch (e) {
    return dateStr
  }
}

const formatCron = (cron) => {
  try {
    return cronstrue.toString(cron, { locale: isZhCN.value ? 'zh_CN' : 'en' })
  } catch (e) {
    return cron
  }
}

watch(activeTab, (val) => {
  if (val === 'one-time') {
    fetchOneTimeTasks()
  } else {
    fetchTasks()
  }
})

onMounted(() => {
  fetchTasks()
  fetchOneTimeTasks()
  fetchAgents()
})
</script>
