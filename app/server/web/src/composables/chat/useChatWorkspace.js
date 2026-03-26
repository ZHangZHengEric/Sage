import { ref, watch } from 'vue'
import { agentAPI } from '@/api/agent.js'
import { usePanelStore } from '@/stores/panel.js'

export const useChatWorkspace = ({
  t,
  toast,
  sessionId
}) => {
  const panelStore = usePanelStore()
  // const showWorkspace = ref(false) // Use panelStore instead
  const workspaceFiles = ref([])
  const taskStatus = ref(null)
  const expandedTasks = ref(new Set())
  const lastMessageId = ref(null)

  const fetchWorkspaceFiles = async () => {
    try {
      const sid = typeof sessionId?.value === 'string' ? sessionId.value : sessionId
      const data = await agentAPI.getWorkspaceFiles(sid)
      workspaceFiles.value = data.files || []
    } catch (error) {
      console.error('获取工作空间文件出错:', error)
    }
  }

  const updateTaskAndWorkspace = () => {
    fetchWorkspaceFiles()
  }

  // Watch for panel open to fetch files
  watch(() => panelStore.showWorkspace, (newVal) => {
    if (newVal) {
      updateTaskAndWorkspace()
    }
  })

  const downloadWorkspaceFile = async (itemOrPath) => {
    if (!itemOrPath) return
    let filePath = typeof itemOrPath === 'string' ? itemOrPath : itemOrPath.path
    const sid = typeof sessionId?.value === 'string' ? sessionId.value : sessionId
    
    // Clean path: remove /sage-workspace/ prefix and leading slash
    if (filePath) {
      if (filePath.startsWith('/sage-workspace/')) {
        filePath = filePath.replace('/sage-workspace/', '')
      }
      if (filePath.startsWith('/')) {
        filePath = filePath.substring(1)
      }
    }

    const isDirectory = typeof itemOrPath === 'object' ? itemOrPath.is_directory : false
    if (!filePath) return
    try {
      const blob = await agentAPI.downloadFile(filePath, sid)
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
      await downloadWorkspaceFile(item)
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
    workspaceFiles,
    downloadWorkspaceFile,
    downloadFile,
    clearTaskAndWorkspace
  }
}
