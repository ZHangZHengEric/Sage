import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getVersion } from '@tauri-apps/api/app'
import { confirm } from '@tauri-apps/plugin-dialog'
import { relaunch } from '@tauri-apps/plugin-process'
import { check } from '@tauri-apps/plugin-updater'
import { useLanguage } from '../utils/i18n'

// Tauri v2 updater flow:
// https://v2.tauri.app/plugin/updater/#checking-for-updates
export const useUpdaterStore = defineStore('updater', () => {
  const { t } = useLanguage()
  const currentVersion = ref('')
  const checking = ref(false)
  const installing = ref(false)
  const downloadProgress = ref(0)
  const updateStatus = ref('')

  const init = async () => {
    try {
      currentVersion.value = await getVersion()
    } catch (error) {
      console.error('[Updater] Failed to read app version:', error)
    }
  }

  const checkForUpdates = async () => {
    if (checking.value || installing.value) return

    checking.value = true
    updateStatus.value = ''

    try {
      const update = await check()
      if (!update) {
        updateStatus.value = t('system.latestVersion')
        return
      }

      updateStatus.value = t('system.foundUpdate', { version: update.version })
      const accepted = await confirm(
        t('system.confirmUpdate', {
          version: update.version,
          notes: update.body || t('system.noReleaseNotes'),
        }),
      )
      if (!accepted) {
        updateStatus.value = t('system.updateCancelled')
        return
      }

      installing.value = true
      downloadProgress.value = 0
      let downloaded = 0
      let contentLength = 0
      updateStatus.value = t('system.downloading')

      await update.downloadAndInstall((event) => {
        if (event.event === 'Started') {
          contentLength = event.data.contentLength || 0
          return
        }
        if (event.event === 'Progress') {
          downloaded += event.data.chunkLength
          if (contentLength > 0) {
            downloadProgress.value = Math.min(
              100,
              Math.round((downloaded / contentLength) * 100),
            )
          }
          return
        }
        if (event.event === 'Finished') {
          downloadProgress.value = 100
          updateStatus.value = t('system.installing')
        }
      })

      updateStatus.value = t('system.restarting')
      await relaunch()
    } catch (error) {
      console.error('[Updater] Update failed:', error)
      const message = error instanceof Error ? error.message : String(error)
      updateStatus.value = t('system.checkUpdateError', { message })
      installing.value = false
    } finally {
      checking.value = false
    }
  }

  return {
    currentVersion,
    checking,
    installing,
    downloadProgress,
    updateStatus,
    init,
    checkForUpdates,
  }
})
