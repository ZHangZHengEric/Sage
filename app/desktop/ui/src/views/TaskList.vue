<template>
  <div class="h-full flex flex-col p-6 space-y-6">
    <Tabs default-value="recurring" class="w-full flex flex-col h-full" v-model="activeTab">
      <div class="flex items-center justify-between mb-4">
        <TabsList>
          <TabsTrigger value="recurring">{{ t('scheduledTask.title') || 'Recurring Tasks' }}</TabsTrigger>
          <TabsTrigger value="one-time">{{ t('scheduledTask.oneTimeTitle') || 'One-time Tasks' }}</TabsTrigger>
        </TabsList>
        <div class="flex items-center justify-end">
          <Button @click="handleCreate" v-if="activeTab === 'recurring'">
            <Plus class="mr-2 h-4 w-4" />
            {{ t('common.create') }}
          </Button>
          <Button @click="handleCreateOneTime" v-else>
            <Plus class="mr-2 h-4 w-4" />
            {{ t('common.create') }}
          </Button>
        </div>
      </div>

      <TabsContent v-if="activeTab === 'recurring'" value="recurring" class="flex-1 overflow-hidden flex flex-col h-full">
        <div class="border rounded-md overflow-auto flex-1">
          <Table class="min-w-[800px]">
            <TableHeader>
              <TableRow>
                <TableHead>{{ t('scheduledTask.name') }}</TableHead>
                <TableHead>{{ t('scheduledTask.cron') }}</TableHead>
                <TableHead>{{ t('scheduledTask.agent') }}</TableHead>
                <TableHead>{{ t('scheduledTask.status') }}</TableHead>
                <TableHead>{{ t('scheduledTask.lastExecuted') }}</TableHead>
                <TableHead class="w-[150px]">{{ t('common.actions') }}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="task in tasks" :key="task.id">
                <TableCell class="font-medium">
                  <div>{{ task.name }}</div>
                  <div class="text-xs text-muted-foreground truncate max-w-[150px]">{{ task.description }}</div>
                </TableCell>
                <TableCell>
                  <div class="flex flex-col gap-1">
                    <Badge variant="outline" class="whitespace-nowrap w-fit">
                      {{ formatCron(task.cron_expression) }}
                    </Badge>
                    <span class="text-xs text-muted-foreground font-mono">{{ task.cron_expression }}</span>
                  </div>
                </TableCell>
                <TableCell>{{ getAgentName(task.agent_id) }}</TableCell>
                <TableCell>
                  <Switch 
                    :checked="task.enabled" 
                    @update:checked="(val) => handleToggle(task, val)"
                  />
                </TableCell>
                <TableCell>
                  {{ formatDate(task.last_executed_at) }}
                </TableCell>
                <TableCell>
                  <div class="flex items-center gap-2">
                    <Button variant="ghost" size="icon" @click="handleEdit(task)">
                      <Edit class="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" @click="handleHistory(task)">
                      <History class="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" @click="handleDelete(task)">
                      <Trash2 class="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
              <TableRow v-if="tasks.length === 0">
                <TableCell colspan="6" class="h-24 text-center">
                  {{ t('common.noData') }}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </TabsContent>

      <TabsContent v-if="activeTab === 'one-time'" value="one-time" class="flex-1 overflow-hidden flex flex-col h-full">
        <div class="border rounded-md overflow-auto flex-1">
          <Table class="min-w-[800px]">
            <TableHeader>
              <TableRow>
                <TableHead>{{ t('scheduledTask.name') }}</TableHead>
                <TableHead>{{ t('scheduledTask.agent') }}</TableHead>
                <TableHead>{{ t('scheduledTask.status') }}</TableHead>
                <TableHead>{{ t('scheduledTask.executeAt') }}</TableHead>
                <TableHead>{{ t('scheduledTask.completedAt') }}</TableHead>
                <TableHead class="w-[120px]">{{ t('common.actions') }}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="task in oneTimeTasks" :key="task.id">
                <TableCell class="font-medium">
                  <div>{{ task.name }}</div>
                  <div class="text-xs text-muted-foreground truncate max-w-[150px]">{{ task.description }}</div>
                </TableCell>
                <TableCell>{{ getAgentName(task.agent_id) }}</TableCell>
                <TableCell>
                  <Badge :variant="getStatusVariant(task.status)">{{ task.status }}</Badge>
                </TableCell>
                <TableCell>
                  {{ formatDate(task.execute_at) }}
                </TableCell>
                <TableCell>
                  {{ formatDate(task.completed_at) }}
                </TableCell>
                <TableCell>
                  <div class="flex items-center gap-2">
                    <Button variant="ghost" size="icon" @click="handleEditOneTime(task)">
                      <Edit class="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" @click="handleDeleteOneTime(task)">
                      <Trash2 class="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
              <TableRow v-if="oneTimeTasks.length === 0">
                <TableCell colspan="6" class="h-24 text-center">
                  {{ t('common.noData') }}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </TabsContent>
    </Tabs>

    <!-- Create/Edit Dialog -->
    <Dialog :open="dialogOpen" @update:open="dialogOpen = $event">
      <DialogContent class="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{{ isEdit ? t('scheduledTask.editTitle') : t('scheduledTask.createTitle') }}</DialogTitle>
        </DialogHeader>
        <div class="grid gap-4 py-4">
          <div class="grid gap-2">
            <Label>{{ t('scheduledTask.name') }} <span class="text-destructive">*</span></Label>
            <Input v-model="form.name" :placeholder="t('scheduledTask.namePlaceholder')" />
          </div>
          <div class="grid gap-2">
            <Label>{{ t('scheduledTask.description') }}</Label>
            <Textarea v-model="form.description" :placeholder="t('scheduledTask.descPlaceholder')" />
          </div>
          <div class="grid gap-2">
            <Label>{{ t('scheduledTask.agent') }} <span class="text-destructive">*</span></Label>
            <Select v-model="form.agent_id">
              <SelectTrigger>
                <SelectValue :placeholder="t('scheduledTask.agentPlaceholder')" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="agent in agents" :key="agent.id" :value="agent.id">
                  {{ agent.name }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="grid gap-2">
            <Label>{{ t('scheduledTask.cron') }} <span class="text-destructive">*</span></Label>
            <CronEditor v-model="form.cron_expression" />
          </div>
          <div class="flex items-center gap-2">
             <Label>{{ t('scheduledTask.enabled') }}</Label>
             <Switch :checked="form.enabled" @update:checked="(val) => form.enabled = val" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="dialogOpen = false">{{ t('common.cancel') }}</Button>
          <Button @click="submitForm">{{ t('common.save') }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- One-Time Task Dialog -->
    <Dialog :open="oneTimeDialogOpen" @update:open="oneTimeDialogOpen = $event">
      <DialogContent class="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{{ oneTimeIsEdit ? (t('scheduledTask.editTitle') || 'Edit One-Time Task') : (t('scheduledTask.createOneTime') || 'Create One-Time Task') }}</DialogTitle>
        </DialogHeader>
        <div class="grid gap-4 py-4">
          <div class="grid gap-2">
            <Label>{{ t('scheduledTask.name') }} <span class="text-destructive">*</span></Label>
            <Input v-model="oneTimeForm.name" :placeholder="t('scheduledTask.namePlaceholder')" />
          </div>
          <div class="grid gap-2">
            <Label>{{ t('scheduledTask.description') }}</Label>
            <Textarea v-model="oneTimeForm.description" :placeholder="t('scheduledTask.descPlaceholder')" />
          </div>
          <div class="grid gap-2">
            <Label>{{ t('scheduledTask.agent') }} <span class="text-destructive">*</span></Label>
            <Select v-model="oneTimeForm.agent_id">
              <SelectTrigger>
                <SelectValue :placeholder="t('scheduledTask.agentPlaceholder')" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="agent in agents" :key="agent.id" :value="agent.id">
                  {{ agent.name }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="grid gap-2">
            <Label>{{ t('scheduledTask.executeAt') }} <span class="text-destructive">*</span></Label>
            <Input type="datetime-local" v-model="oneTimeForm.execute_at" :min="minDateTime" />
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
           <Table>
             <TableHeader>
               <TableRow>
                 <TableHead>{{ t('scheduledTask.executeAt') }}</TableHead>
                 <TableHead>{{ t('scheduledTask.status') }}</TableHead>
                 <TableHead>{{ t('scheduledTask.retryCount') }}</TableHead>
                 <TableHead>{{ t('scheduledTask.completedAt') }}</TableHead>
                 <TableHead class="w-[80px]">{{ t('common.actions') }}</TableHead>
               </TableRow>
             </TableHeader>
             <TableBody>
               <TableRow v-for="item in historyList" :key="item.id">
                 <TableCell>{{ formatDate(item.execute_at) }}</TableCell>
                 <TableCell>
                    <Badge :variant="getStatusVariant(item.status)">{{ item.status }}</Badge>
                 </TableCell>
                 <TableCell>{{ item.retry_count }}</TableCell>
                 <TableCell>{{ formatDate(item.completed_at) }}</TableCell>
                 <TableCell>
                    <Button 
                      v-if="item.session_id" 
                      variant="ghost" 
                      size="icon" 
                      @click="handleViewSession(item.session_id)"
                      :title="t('scheduledTask.viewSession') || 'View Session'"
                    >
                      <MessageSquare class="h-4 w-4" />
                    </Button>
                 </TableCell>
               </TableRow>
               <TableRow v-if="historyList.length === 0">
                 <TableCell colspan="4" class="text-center h-24">{{ t('common.noData') }}</TableCell>
               </TableRow>
             </TableBody>
           </Table>
        </div>
      </DialogContent>
    </Dialog>
    <AppConfirmDialog ref="confirmDialogRef" />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed, watch } from 'vue'
import { Plus, Edit, Trash2, History, MessageSquare } from 'lucide-vue-next'
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
    if (res.agents) {
      agents.value = res.agents
    } else if (Array.isArray(res)) {
      agents.value = res
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

const fetchTasks = async () => {
  try {
    const res = await taskAPI.getRecurringTasks()
    tasks.value = res.items || []
  } catch (error) {
    console.error('Failed to fetch tasks:', error)
    toast.error('Failed to fetch tasks')
  }
}

const fetchOneTimeTasks = async () => {
  try {
    const res = await taskAPI.getOneTimeTasks()
    oneTimeTasks.value = res.items || []
  } catch (error) {
    console.error('Failed to fetch one-time tasks:', error)
    toast.error('Failed to fetch one-time tasks')
  }
}

const handleCreate = () => {
  isEdit.value = false
  currentId.value = null
  form.name = ''
  form.description = ''
  form.agent_id = ''
  form.cron_expression = '* * * * *'
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
    toast.error(t('scheduledTask.futureTimeRequired') || 'Execution time must be in the future')
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
    // Revert visually if failed
    task.enabled = !checked
  }
}

const handleHistory = async (task) => {
  try {
    const res = await taskAPI.getTaskHistory(task.id)
    historyList.value = res.items || []
    historyOpen.value = true
  } catch (error) {
    toast.error('Failed to fetch history')
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
    case 'completed': return 'default' // or success if available
    case 'failed': return 'destructive'
    case 'processing': return 'secondary'
    default: return 'outline'
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  try {
    // Compatibility for SQLite timestamps (replace space with T for ISO format)
    const isoStr = typeof dateStr === 'string' ? dateStr.replace(' ', 'T') : dateStr
    return new Date(isoStr).toLocaleString()
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
