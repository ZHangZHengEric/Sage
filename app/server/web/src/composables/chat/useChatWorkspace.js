import { ref } from 'vue'
import { taskAPI } from '@/api/task.js'

export const useChatWorkspace = ({
  t,
  toast,
  currentSessionId,
  selectedAgentId
}) => {
  const showWorkspace = ref(false)
  const workspaceFiles = ref([])
  const isWorkspaceLoading = ref(false)
  const taskStatus = ref(null)
  const expandedTasks = ref(new Set())
  const lastMessageId = ref(null)

  const fetchWorkspaceFiles = async (agentId) => {
    if (!agentId) return
    isWorkspaceLoading.value = true
    try {
      const data = await taskAPI.getWorkspaceFiles(agentId)
      workspaceFiles.value = data.files || []
    } catch (error) {
      console.error('获取工作空间文件出错:', error)
    } finally {
      isWorkspaceLoading.value = false
    }
  }

  const updateTaskAndWorkspace = () => {
    if (selectedAgentId.value) {
      fetchWorkspaceFiles(selectedAgentId.value)
    }
  }

  const handleWorkspacePanel = () => {
    showWorkspace.value = !showWorkspace.value
    if (showWorkspace.value) {
      updateTaskAndWorkspace(currentSessionId.value)
    }
  }

  const downloadWorkspaceFile = async (_sessionId, itemOrPath) => {
    const agentId = selectedAgentId.value
    if (!agentId || !itemOrPath) return
    const filePath = typeof itemOrPath === 'string' ? itemOrPath : itemOrPath.path
    const isDirectory = typeof itemOrPath === 'object' ? itemOrPath.is_directory : false
    if (!filePath) return
    try {
      const blob = await taskAPI.downloadFile(agentId, filePath)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.style.display = 'none'
      a.href = url
      let filename = filePath.split(/[/\\]/).pop()
      if (isDirectory && !filename.endsWith('.zip')) {
        filename += '.zip'
      }
      a.download = filename
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (error) {
      console.error('下载文件出错:', error)
      toast.error(t('chat.downloadError') || `Download failed: ${error.message}`)
    }
  }

  const downloadFile = async (item) => {
    try {
      if (selectedAgentId.value) {
        await downloadWorkspaceFile(selectedAgentId.value, item)
      }
    } catch (error) {
      toast.error(t('chat.downloadError'))
    }
  }

  const deleteFile = async (item) => {
    if (!item || !item.path) {
      toast.error(t('common.invalidFileItem') || '无效的文件项')
      return
    }
    try {
      const filePath = item.path
      const agentId = selectedAgentId.value
      if (agentId) {
        await taskAPI.deleteWorkspaceFile(agentId, null, filePath)
        toast.success(t('common.deleteSuccess') || 'Delete successful')
        updateTaskAndWorkspace()
      }
    } catch (error) {
      console.error('删除文件出错:', error)
      toast.error(t('common.deleteError') || 'Delete failed')
    }
  }

  const clearTaskAndWorkspace = () => {
    taskStatus.value = null
    isWorkspaceLoading.value = false
    workspaceFiles.value = []
    expandedTasks.value = new Set()
    lastMessageId.value = null
  }

  const refreshWorkspace = () => {
    if (selectedAgentId.value) {
      fetchWorkspaceFiles(selectedAgentId.value)
    }
  }

  return {
    showWorkspace,
    workspaceFiles,
    isWorkspaceLoading,
    handleWorkspacePanel,
    downloadWorkspaceFile,
    downloadFile,
    deleteFile,
    clearTaskAndWorkspace,
    refreshWorkspace
  }
}
