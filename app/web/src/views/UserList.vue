<template>
  <div class="h-full flex flex-col bg-slate-50">
    <!-- Header -->
    <div class="bg-white border-b px-4 py-3 sm:px-6 sm:py-4 flex justify-between items-center">
      <h2 class="text-lg font-semibold">{{ t('sidebar.userList') }}</h2>
      <Button @click="showAddUserDialog = true">
        <Plus class="w-4 h-4 mr-2" />
        {{ t('user.addUser') }}
      </Button>
    </div>

    <!-- Content -->
    <div class="flex-1 p-4 sm:p-6 overflow-hidden">
      <Card class="h-full flex flex-col">
        <div v-if="loading" class="flex-1 flex items-center justify-center min-h-[400px]">
            <Loader2 class="h-8 w-8 animate-spin text-primary" />
        </div>
        <div v-else class="flex-1 overflow-auto min-h-0">
          <!-- Desktop View -->
          <div class="hidden md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>{{ t('user.username') }}</TableHead>
                  <TableHead>{{ t('user.nickname') }}</TableHead>
                  <TableHead>{{ t('user.email') }}</TableHead>
                  <TableHead>{{ t('user.role') }}</TableHead>
                  <TableHead>{{ t('user.createdAt') }}</TableHead>
                  <TableHead class="text-right">{{ t('common.actions') }}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="user in userList" :key="user.id">
                  <TableCell>{{ user.id }}</TableCell>
                  <TableCell>{{ user.username }}</TableCell>
                  <TableCell>{{ user.nickname }}</TableCell>
                  <TableCell>{{ user.email }}</TableCell>
                  <TableCell>
                    <Badge :variant="user.role === 'admin' ? 'default' : 'secondary'">
                      {{ user.role }}
                    </Badge>
                  </TableCell>
                  <TableCell>{{ formatDate(user.created_at) }}</TableCell>
                  <TableCell class="text-right">
                    <Button variant="ghost" size="icon" class="text-destructive hover:text-destructive" @click="confirmDelete(user)" :disabled="user.role === 'admin'">
                      <Trash2 class="w-4 h-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>

          <!-- Mobile View -->
          <div class="md:hidden p-4 space-y-4">
            <div v-for="user in userList" :key="user.id" class="border rounded-lg p-4 space-y-3 bg-card text-card-foreground shadow-sm">
              <div class="flex justify-between items-start">
                <div>
                  <div class="font-medium flex items-center gap-2">
                    {{ user.username }}
                    <Badge :variant="user.role === 'admin' ? 'default' : 'secondary'" class="text-xs px-1.5 py-0 h-5">
                      {{ user.role }}
                    </Badge>
                  </div>
                  <div class="text-sm text-muted-foreground mt-0.5">{{ user.nickname || '-' }}</div>
                </div>
                <Button variant="ghost" size="icon" class="h-8 w-8 text-destructive hover:text-destructive -mr-2 -mt-2" @click="confirmDelete(user)" :disabled="user.role === 'admin'">
                  <Trash2 class="w-4 h-4" />
                </Button>
              </div>
              
              <div class="text-sm space-y-1 text-muted-foreground">
                <div class="flex items-center gap-2">
                  <span class="w-12 shrink-0">Email:</span>
                  <span class="text-foreground truncate">{{ user.email }}</span>
                </div>
                <div class="flex items-center gap-2">
                  <span class="w-12 shrink-0">Date:</span>
                  <span class="text-foreground">{{ formatDate(user.created_at) }}</span>
                </div>
                <div class="flex items-center gap-2 text-xs text-muted-foreground/70">
                   <span class="w-12 shrink-0">ID:</span>
                   <span>{{ user.id }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        
        <!-- Pagination -->
        <div class="p-4 border-t flex justify-between sm:justify-end gap-2 items-center">
            <Button variant="outline" size="sm" :disabled="page <= 1" @click="prevPage" class="w-20 sm:w-auto">
              <span class="sm:hidden">&lt;</span>
              <span class="hidden sm:inline">{{ t('common.previous') }}</span>
            </Button>
            <span class="flex items-center text-sm whitespace-nowrap">{{ t('common.page') }} {{ page }}</span>
            <Button variant="outline" size="sm" :disabled="userList.length < pageSize" @click="nextPage" class="w-20 sm:w-auto">
              <span class="sm:hidden">&gt;</span>
              <span class="hidden sm:inline">{{ t('common.next') }}</span>
            </Button>
        </div>
      </Card>
    </div>

    <!-- Add User Dialog -->
    <Dialog v-model:open="showAddUserDialog">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{{ t('user.addUser') }}</DialogTitle>
        </DialogHeader>
        <div class="space-y-4 py-4">
          <div class="space-y-2">
            <Label>{{ t('user.username') }}</Label>
            <Input v-model="newUser.username" />
          </div>
          <div class="space-y-2">
            <Label>{{ t('user.password') }}</Label>
            <Input type="password" v-model="newUser.password" />
          </div>
          <div class="space-y-2">
             <Label>{{ t('user.role') }}</Label>
             <Select v-model="newUser.role">
                <SelectTrigger>
                    <SelectValue :placeholder="t('user.selectRole')" />
                </SelectTrigger>
                <SelectContent>
                    <SelectItem value="user">{{ t('user.roleUser') }}</SelectItem>
                    <SelectItem value="admin">{{ t('user.roleAdmin') }}</SelectItem>
                </SelectContent>
             </Select>
          </div>
        </div>
        <DialogFooter>
            <Button variant="outline" @click="showAddUserDialog = false">{{ t('common.cancel') }}</Button>
            <Button @click="handleAddUser">{{ t('common.confirm') }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { userAPI } from '../api/user'
import { useLanguage } from '../utils/i18n'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Plus, Trash2, Loader2 } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

const { t } = useLanguage()
const userList = ref([])
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const showAddUserDialog = ref(false)
const newUser = ref({ username: '', password: '', role: 'user' })

const fetchUsers = async () => {
    try {
        loading.value = true
        const res = await userAPI.getUserList(page.value, pageSize.value)
        if (res.success) {
            userList.value = res.data.items || []
        }
    } finally {
        loading.value = false
    }
}

const prevPage = () => {
    if (page.value > 1) {
        page.value--
        fetchUsers()
    }
}

const nextPage = () => {
    page.value++
    fetchUsers()
}

const handleAddUser = async () => {
    const res = await userAPI.addUser(newUser.value)
    if (res.success) {
        toast.success(t('user.addSuccess'))
        showAddUserDialog.value = false
        fetchUsers()
        newUser.value = { username: '', password: '', role: 'user' }
    } else {
        toast.error(res.message || t('user.addError'))
    }
}

const confirmDelete = async (user) => {
    if (confirm(t('user.deleteConfirm').replace('{name}', user.username))) {
        const res = await userAPI.deleteUser(user.id)
        if (res.success) {
            toast.success(t('user.deleteSuccess'))
            fetchUsers()
        } else {
             toast.error(res.message || t('user.deleteError'))
        }
    }
}

const formatDate = (dateStr) => {
    if (!dateStr) return '-'
    return new Date(dateStr).toLocaleString()
}

onMounted(fetchUsers)
</script>
