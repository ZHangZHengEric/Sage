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
  const taskStatus = ref(null)
  const expandedTasks = ref(new Set())
  const lastMessageId = ref(null)

  const fetchWorkspaceFiles = async (agentId) => {
    if (!agentId) return
    try {
      const data = await taskAPI.getWorkspaceFiles(agentId)
      workspaceFiles.value = data.files || []
    } catch (error) {
      console.error('获取工作空间文件出错:', error)
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
      let filename = filePath.split('/').pop()
      if (isDirectory && !filename.endsWith('.zip')) {
        filename += '.zip'
      }
      if (window.__TAURI__) {
        try {
          const { save } = await import('@tauri-apps/api/dialog')
          const { writeBinaryFile } = await import('@tauri-apps/api/fs')
          const { documentDir, join } = await import('@tauri-apps/api/path')
          const defaultDir = await documentDir()
          const defaultPath = await join(defaultDir, filename)
          const ext = filename.split('.').pop()
          const filters = ext && ext !== filename ? [{
            name: ext.toUpperCase() + ' File',
            extensions: [ext]
          }] : []
          const savePath = await save({
            defaultPath,
            filters
          })
          if (savePath) {
            const arrayBuffer = await blob.arrayBuffer()
            await writeBinaryFile(savePath, new Uint8Array(arrayBuffer))
            toast.success(t('chat.downloadSuccess') || 'Download successful')
          }
          return
        } catch (tauriError) {
          console.warn('Tauri download failed, falling back to web download:', tauriError)
        }
      }
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.style.display = 'none'
      a.href = url
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
