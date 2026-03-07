import { ref } from 'vue'
import { agentAPI } from '@/api/agent.js'

export const useChatWorkspace = ({
  t,
  toast,
  agentId
}) => {
  const showWorkspace = ref(false)
  const workspaceFiles = ref([])
  const taskStatus = ref(null)
  const expandedTasks = ref(new Set())
  const lastMessageId = ref(null)

  const fetchWorkspaceFiles = async (id) => {
    if (!id) return
    try {
      const data = await agentAPI.getWorkspaceFiles(id)
      workspaceFiles.value = data.files || []
    } catch (error) {
      console.error('获取工作空间文件出错:', error)
    }
  }

  const updateTaskAndWorkspace = (id) => {
    if (id) {
      fetchWorkspaceFiles(id)
    }
  }

  const handleWorkspacePanel = () => {
    showWorkspace.value = !showWorkspace.value
    if (showWorkspace.value) {
      updateTaskAndWorkspace(agentId.value)
    }
  }

  const downloadWorkspaceFile = async (id, itemOrPath) => {
    if (!id || !itemOrPath) return
    const filePath = typeof itemOrPath === 'string' ? itemOrPath : itemOrPath.path
    const isDirectory = typeof itemOrPath === 'object' ? itemOrPath.is_directory : false
    if (!filePath) return
    try {
      const blob = await agentAPI.downloadFile(id, filePath)
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
      if (agentId.value) {
        await downloadWorkspaceFile(agentId.value, item)
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
