
export function normalizeFilePath(path) {
  if (!path) return ''
  
  // 去掉两端空白
  path = path.trim()

  // 去除成对反引号
  if (path.startsWith('`') && path.endsWith('`')) {
    path = path.slice(1, -1).trim()
  }
  
  // decode URL
  try {
    path = decodeURIComponent(path)
  } catch (e) { }

  path = path
    .replace(/^\{workspace_root\}\//i, '/')
    .replace(/^\$\{workspace_root\}\//i, '/')
    .replace(/^file:\/\/\/?/i, '/')
    .replace(/^\/sage-workspace\//, '/')

  return path
}

export function getDisplayFileName(filePath, fileName = '') {
  fileName = fileName.replace(/^\/sage-workspace\//, '/')
  return fileName || (filePath ? filePath.split('/').pop() : '') || 'file'
}

export function getFileExtension(filePath, fileName = '') {
  // 优先从文件路径获取扩展名
  if (filePath) {
    const pathMatch = filePath.match(/\.([^.]+)$/)
    if (pathMatch) return pathMatch[1].toLowerCase()
  }
  
  // 其次从显示名称获取
  if (fileName) {
    const match = fileName.match(/\.([^.]+)$/)
    return match ? match[1].toLowerCase() : ''
  }
  
  return ''
}

export const IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico', 'bmp']

export function isImageFile(ext) {
  return IMAGE_EXTENSIONS.includes(ext)
}

export function getFileIcon(ext, isDirectory = false) {
  if (isDirectory) return '📁'

  const iconMap = {
    // Microsoft Office
    'doc': '📘', 'docx': '📘',
    'xls': '📗', 'xlsx': '📗', 'csv': '📗',
    'ppt': '📙', 'pptx': '📙',

    // PDF
    'pdf': '📕',

    // 图片
    'png': '🖼️', 'jpg': '🖼️', 'jpeg': '🖼️', 'gif': '🖼️',
    'webp': '🖼️', 'svg': '🎨', 'ico': '🎨', 'bmp': '🖼️',

    // 代码文件
    'html': '🌐', 'htm': '🌐',          // Web
    'css': '🎨', 'scss': '🎨', 'less': '🎨',

    'js': '🟨', 'jsx': '⚛️',           // JS / React
    'ts': '🔷', 'tsx': '⚛️',

    'vue': '🟩',                      // Vue
    'svelte': '🔥',

    'py': '🐍', 'ipynb': '📓',        // Jupyter

    'java': '☕', 'class': '📦',

    'c': '🔧', 'h': '📄',
    'cpp': '⚙️',

    'go': '🐹',
    'rs': '🦀',

    'rb': '💎',
    'php': '🐘',

    'swift': '🕊️',
    'kt': '🟣',                       // Kotlin

    'sql': '🗄️',
    // 数据格式
    'json': '📋', 'xml': '📋', 'yaml': '📋', 'yml': '📋',

    // 文本
    'md': '📝', 'markdown': '📝',
    'txt': '📃', 'log': '📃',

    // 脚本
    'sh': '🔧', 'bash': '🔧', 'zsh': '🔧', 'ps1': '🔧',

    // 特殊
    'excalidraw': '✏️',
    'drawio': '📊',

    // 压缩包
    'zip': '📦', 'rar': '📦', '7z': '📦', 'tar': '📦', 'gz': '📦',

    // 可执行
    'exe': '⚡', 'dmg': '🍎', 'app': '🍎',

    // 音频视频
    'mp3': '🎵', 'mp4': '🎬', 'wav': '🎵', 'avi': '🎬', 'mov': '🎬'
  }

  return iconMap[ext] || '📎'
}

export function getFileType(ext) {
  const typeMap = {
    'pdf': 'pdf',
    'png': 'image', 'jpg': 'image', 'jpeg': 'image', 'gif': 'image', 'webp': 'image', 'svg': 'image', 'ico': 'image', 'bmp': 'image',
    'html': 'html', 'htm': 'html',
    'md': 'markdown', 'markdown': 'markdown',
    'excalidraw': 'excalidraw',
    'js': 'code', 'ts': 'code', 'jsx': 'code', 'tsx': 'code',
    'py': 'code', 'ipynb': 'code',
    'java': 'code', 'class': 'code',
    'cpp': 'code', 'c': 'code', 'h': 'code',
    'go': 'code', 'rs': 'code',
    'json': 'code', 'xml': 'code', 'yaml': 'code', 'yml': 'code',
    'css': 'code', 'scss': 'code', 'less': 'code',
    'vue': 'code', 'svelte': 'code',
    'php': 'code', 'rb': 'code', 'swift': 'code', 'kt': 'code',
    'sql': 'code', 'sh': 'code', 'bash': 'code', 'zsh': 'code', 'ps1': 'code',
    'txt': 'text', 'log': 'text', 'csv': 'text',
    'pptx': 'office', 'ppt': 'office',
    'docx': 'office', 'doc': 'office',
    'xlsx': 'office', 'xls': 'office'
  }
  return typeMap[ext] || 'other'
}

export function getFileLanguage(ext) {
  const langMap = {
    'js': 'JavaScript', 'ts': 'TypeScript', 
    'jsx': 'JSX', 'tsx': 'TSX',
    'py': 'Python', 'ipynb': 'Jupyter Notebook',
    'java': 'Java', 'class': 'Java Class',
    'cpp': 'C++', 'c': 'C', 'h': 'C Header',
    'go': 'Go', 'rs': 'Rust',
    'json': 'JSON', 'xml': 'XML',
    'yaml': 'YAML', 'yml': 'YAML',
    'css': 'CSS', 'scss': 'SCSS', 'less': 'Less',
    'vue': 'Vue', 'svelte': 'Svelte',
    'php': 'PHP', 'rb': 'Ruby',
    'swift': 'Swift', 'kt': 'Kotlin',
    'sql': 'SQL', 'sh': 'Shell',
    'bash': 'Bash', 'zsh': 'Zsh', 'ps1': 'PowerShell'
  }
  return langMap[ext] || ext.toUpperCase()
}

export function getOfficeFileType(ext) {
  const officeMap = {
    'pptx': 'PowerPoint', 'ppt': 'PowerPoint',
    'docx': 'Word', 'doc': 'Word',
    'xlsx': 'Excel', 'xls': 'Excel', 'csv': 'Excel'
  }
  return officeMap[ext] || 'Office'
}

export function getFileTypeLabel(ext, officeType = '') {
  const fileType = getFileType(ext)
  const labels = {
    'pdf': 'PDF',
    'image': '图片',
    'html': 'HTML',
    'markdown': 'Markdown',
    'excalidraw': 'Excalidraw',
    'code': '代码',
    'text': '文本',
    'office': officeType || getOfficeFileType(ext),
    'other': '文件'
  }
  return labels[fileType] || '文件'
}
