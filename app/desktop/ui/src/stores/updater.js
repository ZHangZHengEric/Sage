import { defineStore } from 'pinia'
import { ref } from 'vue'
import { check } from '@tauri-apps/plugin-updater'
import { getVersion } from '@tauri-apps/api/app'
import { relaunch } from '@tauri-apps/plugin-process'
import { confirm } from '@tauri-apps/plugin-dialog'
import { useLanguage } from '../utils/i18n'

export const useUpdaterStore = defineStore('updater', () => {
  const { t } = useLanguage()

  const currentVersion = ref('0.1.0')
  const checking = ref(false)
  const downloading = ref(false)
  const downloadProgress = ref(0)
  const downloadedBytes = ref(0)
  const totalBytes = ref(0)
  const updateStatus = ref('')
  
  // 初始化获取版本号
  const init = async () => {
    try {
      currentVersion.value = await getVersion()
    } catch (e) {
      console.error(e)
    }
  }

  const checkForUpdates = async () => {
    // 如果正在检查或正在下载，则忽略
    if (checking.value || downloading.value) return
    
    checking.value = true
    updateStatus.value = ''
    
    try {

      // Check for updates
      const update = await check()
      
      if (update) {
        updateStatus.value = t('system.foundUpdate', { version: update.version })
        
        const confirmed = await confirm(t('system.confirmUpdate', { version: update.version, notes: update.body || t('system.noReleaseNotes') }))
        
        if (confirmed) {
          // Note: In Tauri v2, we cannot modify the download URL from the JS side.
          // The 'update' object does not expose the URL, and modifying it does not affect the Rust backend.
          // To support proxying, the server endpoint must return the proxied URL, 
          // or the user must use a system proxy.
          
          await startDownload(update)
        } else {
          updateStatus.value = t('system.updateCancelled')
        }
      } else {
        updateStatus.value = t('system.latestVersion')
      }
    } catch (error) {
      console.error(error)
      const errorMessage = error instanceof Error ? error.message : String(error)
      updateStatus.value = t('system.checkUpdateError', { message: errorMessage })
    } finally {
      checking.value = false
    }
  }

  const startDownload = async (update) => {
    downloading.value = true
    downloadProgress.value = 0
    downloadedBytes.value = 0
    totalBytes.value = 0
    updateStatus.value = t('system.downloading')

    try {
      let downloaded = 0
      let contentLength = 0
      
      await update.download((event) => {
        console.log('[Updater] Download event:', event)
        switch (event.event) {
          case 'Started':
            contentLength = event.data.contentLength
            console.log('[Updater] Download started. Content length:', contentLength)
            updateStatus.value = `Download started. Size: ${contentLength || 'unknown'}`
            if (contentLength) {
              totalBytes.value = contentLength
            }
            break
          case 'Progress':
            downloaded += event.data.chunkLength
            downloadedBytes.value = downloaded
            console.log(`[Updater] Download progress: ${downloaded}/${totalBytes.value}`)
            if (totalBytes.value > 0) {
              downloadProgress.value = Math.round((downloaded / totalBytes.value) * 100)
            }
            
            // Show detailed status
            if (downloaded === 0) {
                 updateStatus.value = 'Connected, waiting for data...'
            } else if (downloaded < 1024 * 1024) { 
                 updateStatus.value = `Downloading: ${Math.round(downloaded/1024)}KB / ${Math.round(totalBytes.value/1024)}KB`
            } else {
                 updateStatus.value = `Downloading: ${(downloaded/1024/1024).toFixed(1)}MB / ${(totalBytes.value/1024/1024).toFixed(1)}MB`
            }
            break
          case 'Finished':
            console.log('[Updater] Download finished')
            updateStatus.value = 'Download finished, verifying...'
            // 下载完成
            break
        }
      })

      console.log('[Updater] Download complete, installing...')
      updateStatus.value = t('system.installing')
      await update.install()
      
      updateStatus.value = t('system.restarting')
      await relaunch()
    } catch (e) {
      console.error(e)
      updateStatus.value = t('system.checkUpdateError', { message: e.message })
      downloading.value = false
    }
  }

  return {
    currentVersion,
    checking,
    downloading,
    downloadProgress,
    downloadedBytes,
    totalBytes,
    updateStatus,
    init,
    checkForUpdates
  }
})
