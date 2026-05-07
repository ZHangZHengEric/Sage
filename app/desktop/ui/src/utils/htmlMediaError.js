/**
 * HTMLMediaElement.error（video/audio）的可读说明。
 * 多数浏览器下 MediaError.message 为空，需结合 code。
 * @param {HTMLMediaElement | null | undefined} el
 * @returns {string}
 */
export function describeHtmlMediaElementError(el) {
  const mediaErr = el?.error
  if (!mediaErr) {
    return '无法加载媒体资源'
  }
  const byCode = {
    1: '加载已中止',
    2: '网络错误导致加载失败',
    3: '解码失败或文件损坏',
    4: '不支持的格式或资源不可用',
  }
  const raw =
    mediaErr.message != null ? String(mediaErr.message).trim() : ''
  if (raw) return raw
  return byCode[mediaErr.code] || '无法播放'
}
