<template>
  <div class="h-full flex flex-col p-6 space-y-6">
    <div class="flex items-center justify-end">
      <Button @click="handleCreate">
        <Plus class="mr-2 h-4 w-4" />
        {{ t('common.create') }}
      </Button>
    </div>

    <div class="border rounded-md overflow-x-auto">
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
              {{ task.last_executed_at ? new Date(task.last_executed_at).toLocaleString() : '-' }}
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
               </TableRow>
             </TableHeader>
             <TableBody>
               <TableRow v-for="item in historyList" :key="item.id">
                 <TableCell>{{ new Date(item.execute_at).toLocaleString() }}</TableCell>
                 <TableCell>
                    <Badge :variant="getStatusVariant(item.status)">{{ item.status }}</Badge>
                 </TableCell>
                 <TableCell>{{ item.retry_count }}</TableCell>
                 <TableCell>{{ item.completed_at ? new Date(item.completed_at).toLocaleString() : '-' }}</TableCell>
               </TableRow>
               <TableRow v-if="historyList.length === 0">
                 <TableCell colspan="4" class="text-center h-24">{{ t('common.noData') }}</TableCell>
               </TableRow>
             </TableBody>
           </Table>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { Plus, Edit, Trash2, History } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
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

const { t, isZhCN } = useLanguage()
const tasks = ref([])
const historyList = ref([])
const agents = ref([])
const dialogOpen = ref(false)
const historyOpen = ref(false)
const isEdit = ref(false)
const currentId = ref(null)

const form = reactive({
  name: '',
  description: '',
  agent_id: '',
  cron_expression: '',
  enabled: true
})

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
  if (confirm(t('common.confirmDelete'))) {
    try {
      await taskAPI.deleteRecurringTask(task.id)
      toast.success(t('common.deleteSuccess'))
      fetchTasks()
    } catch (error) {
      toast.error(error.message)
    }
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

const formatCron = (cron) => {
  try {
    return cronstrue.toString(cron, { locale: isZhCN.value ? 'zh_CN' : 'en' })
  } catch (e) {
    return cron
  }
}

onMounted(() => {
  fetchTasks()
  fetchAgents()
})
</script>
