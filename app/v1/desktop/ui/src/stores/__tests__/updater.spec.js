import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      clear: vi.fn(),
      getItem: vi.fn(() => null),
      key: vi.fn(() => null),
      length: 0,
      removeItem: vi.fn(),
      setItem: vi.fn(),
    },
  })
  return {
    check: vi.fn(),
    confirm: vi.fn(),
    getVersion: vi.fn(),
    relaunch: vi.fn(),
  }
})

vi.mock('@tauri-apps/plugin-updater', () => ({ check: mocks.check }))
vi.mock('@tauri-apps/plugin-dialog', () => ({ confirm: mocks.confirm }))
vi.mock('@tauri-apps/api/app', () => ({ getVersion: mocks.getVersion }))
vi.mock('@tauri-apps/plugin-process', () => ({ relaunch: mocks.relaunch }))
vi.mock('../../utils/i18n', () => ({
  useLanguage: () => ({
    t: (key, params = {}) => params.version ? `${key}:${params.version}` : key,
  }),
}))

import { useUpdaterStore } from '../updater'


describe('updater store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mocks.getVersion.mockResolvedValue('1.0.0')
  })

  it('reports the current version and no-update result', async () => {
    mocks.check.mockResolvedValue(null)
    const store = useUpdaterStore()

    await store.init()
    await store.checkForUpdates()

    expect(store.currentVersion).toBe('1.0.0')
    expect(store.updateStatus).toBe('system.latestVersion')
    expect(mocks.relaunch).not.toHaveBeenCalled()
  })

  it('downloads, installs, and relaunches an accepted signed update', async () => {
    const downloadAndInstall = vi.fn(async (onEvent) => {
      onEvent({ event: 'Started', data: { contentLength: 100 } })
      onEvent({ event: 'Progress', data: { chunkLength: 40 } })
      onEvent({ event: 'Progress', data: { chunkLength: 60 } })
      onEvent({ event: 'Finished', data: {} })
    })
    mocks.check.mockResolvedValue({
      version: '1.2.3',
      body: 'Release notes',
      downloadAndInstall,
    })
    mocks.confirm.mockResolvedValue(true)
    const store = useUpdaterStore()

    await store.checkForUpdates()

    expect(mocks.confirm).toHaveBeenCalledOnce()
    expect(downloadAndInstall).toHaveBeenCalledOnce()
    expect(store.downloadProgress).toBe(100)
    expect(store.updateStatus).toBe('system.restarting')
    expect(mocks.relaunch).toHaveBeenCalledOnce()
  })

  it('does not download a rejected update', async () => {
    const downloadAndInstall = vi.fn()
    mocks.check.mockResolvedValue({
      version: '1.2.3',
      body: '',
      downloadAndInstall,
    })
    mocks.confirm.mockResolvedValue(false)
    const store = useUpdaterStore()

    await store.checkForUpdates()

    expect(store.updateStatus).toBe('system.updateCancelled')
    expect(downloadAndInstall).not.toHaveBeenCalled()
    expect(mocks.relaunch).not.toHaveBeenCalled()
  })
})
