import { ref } from 'vue'
import { taskAPI } from '@/api/task.js'

export const useChatWorkspace = ({
  t,
  toast,
  currentSessionId
}) => {
  const showWorkspace = ref(false)
  const workspaceFiles = ref([])
  const taskStatus = ref(null)
  const expandedTasks = ref(new Set())
  const lastMessageId = ref(null)

  const fetchWorkspaceFiles = async (sessionId) => {
    if (!sessionId) return
    try {
      const data = await taskAPI.getWorkspaceFiles(sessionId)
      workspaceFiles.value = data.files || []
    } catch (error) {
      console.error('获取工作空间文件出错:', error)
    }
  }

  const updateTaskAndWorkspace = (sessionId) => {
    if (sessionId) {
      fetchWorkspaceFiles(sessionId)
    }
  }

  const handleWorkspacePanel = () => {
    showWorkspace.value = !showWorkspace.value
    if (showWorkspace.value) {
      updateTaskAndWorkspace(currentSessionId.value)
    }
  }

  const downloadWorkspaceFile = async (sessionId, itemOrPath) => {
    if (!sessionId || !itemOrPath) return
    const filePath = typeof itemOrPath === 'string' ? itemOrPath : itemOrPath.path
    const isDirectory = typeof itemOrPath === 'object' ? itemOrPath.is_directory : false
    if (!filePath) return
    try {
      const blob = await taskAPI.downloadFile(sessionId, filePath)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.style.display = 'none'
      a.href = url
      let filename = filePath.split('/').pop()
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
      if (currentSessionId.value) {
        await downloadWorkspaceFile(currentSessionId.value, item)
      }
    } catch (error) {
      toast.error(t('chat.downloadError'))
    }
  }

  const clearTaskAndWorkspace = () => {
    taskStatus.value = null
    workspaceFiles.value = []
    expandedTasks.value = new Set()
    lastMessageId.value = null
  }

  return {
    showWorkspace,
    workspaceFiles,
    handleWorkspacePanel,
    downloadWorkspaceFile,
    downloadFile,
    clearTaskAndWorkspace
  }
}
