export const THEME_KEY = 'sage.server_v2.theme'
export const themeOptions = [
  { value: 'light', label: '浅色', icon: 'sun' },
  { value: 'dark', label: '暗色', icon: 'moon' },
  { value: 'system', label: '跟随系统', icon: 'monitor' },
]
const validMode = value => themeOptions.some(option => option.value === value)
export function readThemePreference(storage) {
  try { const value = storage.getItem(THEME_KEY); return validMode(value) ? value : 'system' }
  catch { return 'system' }
}
export function resolveTheme(mode, systemDark) { return mode === 'system' ? systemDark ? 'dark' : 'light' : mode }

export function createThemeController({ root, storage, media, onChange = () => {} }) {
  let mode = readThemePreference(storage)
  function apply() {
    root.dataset.theme = resolveTheme(mode, media.matches)
    onChange(mode)
  }
  function systemChanged() { if (mode === 'system') apply() }
  media.addEventListener('change', systemChanged)
  apply()
  return {
    get mode() { return mode },
    setMode(value) {
      if (!validMode(value)) return
      mode = value
      try { storage.setItem(THEME_KEY, value) } catch { /* The current tab still supports switching when storage is unavailable. */ }
      apply()
    },
    dispose() { media.removeEventListener('change', systemChanged) },
  }
}
