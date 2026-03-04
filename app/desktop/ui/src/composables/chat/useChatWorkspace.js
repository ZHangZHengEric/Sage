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
          const { save } = await import('@tauri-apps/plugin-dialog')
          const { writeFile } = await import('@tauri-apps/plugin-fs')
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
            await writeFile(savePath, new Uint8Array(arrayBuffer))
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

  const deleteFile = async (item) => {
    if (!confirm(t('common.confirmDelete') || 'Are you sure you want to delete this file?')) return
    
    try {
      const filePath = item.path
      const agentId = selectedAgentId.value
      // 如果有 sessionId，优先使用 session 接口（目前逻辑是混用的，需要厘清）
      // 这里根据后端实现，Agent 路由和 Session 路由是分开的。
      // useChatWorkspace 中 fetchWorkspaceFiles 用的是 taskAPI.getWorkspaceFiles(agentId)
      // 这意味着当前 WorkspacePanel 展示的是 Agent 的 workspace，而不是 Session 的。
      // 但是 downloadWorkspaceFile 里却用了 currentSessionId.value ? 
      // 不，fetchWorkspaceFiles 用的是 agentId。
      // downloadWorkspaceFile 的第一个参数被命名为 _sessionId，但在实现里是用 selectedAgentId.value 作为 agentId。
      
      // 所以删除也应该用 agentId。
      if (agentId) {
        await taskAPI.deleteWorkspaceFile(agentId, null, filePath)
        toast.success(t('common.deleteSuccess') || 'Delete successful')
        // 刷新列表
        updateTaskAndWorkspace()
      }
    } catch (error) {
      console.error('删除文件出错:', error)
      toast.error(t('common.deleteError') || 'Delete failed')
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
    deleteFile,
    clearTaskAndWorkspace
  }
}
