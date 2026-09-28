import { ref } from 'vue'
import { defineStore } from 'pinia'

export const usePanelStore = defineStore('panel', () => {
  // State
  const showWorkbench = ref(false)
  const showWorkspace = ref(false)
  const showSettings = ref(false)
  const activePanel = ref(null) // 'workbench' | 'workspace' | 'settings' | null

  // Actions
  const openWorkbench = () => {
    activePanel.value = 'workbench'
    showWorkbench.value = true
    showWorkspace.value = false
    showSettings.value = false
  }

  const openWorkspace = () => {
    activePanel.value = 'workspace'
    showWorkbench.value = false
    showWorkspace.value = true
    showSettings.value = false
  }

  const openSettings = () => {
    activePanel.value = 'settings'
    showWorkbench.value = false
    showWorkspace.value = false
    showSettings.value = true
  }

  const closeAll = () => {
    activePanel.value = null
    showWorkbench.value = false
    showWorkspace.value = false
    showSettings.value = false
  }

  const toggleWorkbench = () => {
    if (showWorkbench.value) {
      closeAll()
    } else {
      openWorkbench()
    }
  }

  return {
    // State
    showWorkbench,
    showWorkspace,
    showSettings,
    activePanel,
    // Actions
    openWorkbench,
    openWorkspace,
    openSettings,
    closeAll,
    toggleWorkbench
  }
})
