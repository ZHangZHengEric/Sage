<template>
  <Dialog :open="visible" @update:open="$emit('update:visible', $event)">
    <DialogContent class="sm:max-w-[500px]">
      <DialogHeader>
        <DialogTitle>{{ t('agent.auth.title') }}</DialogTitle>
        <DialogDescription>
          {{ t('agent.auth.description') }}
        </DialogDescription>
      </DialogHeader>

      <div class="py-4 space-y-4">
        <!-- Search Input -->
        <div class="relative">
          <Input 
            v-model="searchQuery" 
            :placeholder="t('agent.auth.searchPlaceholder')" 
            class="pl-9"
          />
          <Search class="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
        </div>

        <!-- User List -->
        <div class="border rounded-md">
          <ScrollArea class="h-[300px] w-full p-4">
            <div v-if="loading" class="flex justify-center py-4">
              <Loader2 class="h-6 w-6 animate-spin text-primary" />
            </div>
            <div v-else-if="filteredUsers.length === 0" class="text-center text-muted-foreground py-4">
              {{ t('common.noData') }}
            </div>
            <div v-else class="space-y-2">
              <div 
                v-for="user in filteredUsers" 
                :key="user.value"
                class="flex items-center space-x-2 hover:bg-muted/50 p-2 rounded cursor-pointer"
                @click="toggleUser(user.value)"
              >
                <Checkbox 
                  :checked="selectedUsers.includes(user.value)" 
                  @update:checked="(val) => handleCheckboxChange(val, user.value)"
                  @click.stop
                />
                <label class="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer flex-1">
                  {{ user.label }}
                  <span v-if="user.value === currentUserId" class="ml-2 text-xs text-muted-foreground">({{ t('common.you') }})</span>
                </label>
              </div>
            </div>
          </ScrollArea>
        </div>
        
        <div class="text-sm text-muted-foreground text-right">
          {{ t('agent.auth.selectedCount', { count: selectedUsers.length }) }}
        </div>
      </div>

      <DialogFooter>
        <Button variant="outline" @click="$emit('update:visible', false)">
          {{ t('common.cancel') }}
        </Button>
        <Button @click="handleSave" :disabled="saving">
          <Loader2 v-if="saving" class="mr-2 h-4 w-4 animate-spin" />
          {{ t('common.save') }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Checkbox } from '@/components/ui/checkbox'
import { Search, Loader2 } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n'
import { agentAPI } from '../api/agent'
import { userAPI } from '../api/user'
import { toast } from 'vue-sonner'
import { getCurrentUser } from '../utils/auth'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  agentId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['update:visible', 'saved'])
const { t } = useLanguage()

const users = ref([])
const selectedUsers = ref([])
const searchQuery = ref('')
const loading = ref(false)
const saving = ref(false)
const currentUserId = ref('')

// Initialize
onMounted(() => {
  const user = getCurrentUser()
  if (user) {
    currentUserId.value = user.userid
  }
})

// Filter users
const filteredUsers = computed(() => {
  let result = users.value
  
  // Filter by search query
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    result = result.filter(u => u.label.toLowerCase().includes(query))
  }
  
  // Exclude current user from list (requirement: authorize non-self users)
  // Actually, usually we might want to see ourselves but disabled?
  // But requirement says "choose from existing users to authorize non-self users".
  // So hiding self is cleaner.
  result = result.filter(u => u.value !== currentUserId.value)
  
  return result
})

// Load data when dialog opens
watch(() => props.visible, async (newVal) => {
  if (newVal && props.agentId) {
    await loadData()
  } else {
    // Reset state on close
    searchQuery.value = ''
    users.value = []
    selectedUsers.value = []
  }
})

const loadData = async () => {
  loading.value = true
  try {
    // Load all users options
    const optionsRes = await userAPI.getUserOptions()
    if (optionsRes.data) {
      users.value = optionsRes.data
    } else {
      users.value = optionsRes || []
    }

    // Load current authorizations
    const authRes = await agentAPI.getAgentAuth(props.agentId)
    if (authRes.data) {
      selectedUsers.value = authRes.data
    } else {
      selectedUsers.value = authRes || []
    }
  } catch (error) {
    console.error('Failed to load auth data:', error)
    toast.error(t('agent.auth.loadError'))
  } finally {
    loading.value = false
  }
}

const toggleUser = (userId) => {
  const index = selectedUsers.value.indexOf(userId)
  if (index === -1) {
    selectedUsers.value.push(userId)
  } else {
    selectedUsers.value.splice(index, 1)
  }
}

const handleCheckboxChange = (checked, userId) => {
  // Checkbox component might return boolean or array depending on usage
  // Here we manually manage the array, so we just use toggle logic if checked state mismatches
  const index = selectedUsers.value.indexOf(userId)
  if (checked && index === -1) {
    selectedUsers.value.push(userId)
  } else if (!checked && index !== -1) {
    selectedUsers.value.splice(index, 1)
  }
}

const handleSave = async () => {
  saving.value = true
  try {
    await agentAPI.updateAgentAuth(props.agentId, selectedUsers.value)
    toast.success(t('agent.auth.saveSuccess'))
    emit('saved')
    emit('update:visible', false)
  } catch (error) {
    console.error('Failed to save authorizations:', error)
    toast.error(t('agent.auth.saveError'))
  } finally {
    saving.value = false
  }
}
</script>
