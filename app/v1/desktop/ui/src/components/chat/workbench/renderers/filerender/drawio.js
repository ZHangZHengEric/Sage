const DRAWIO_BASE_URL = 'https://app.diagrams.net/'

const DIRECT_DRAWIO_EXTENSIONS = new Set([
  'drawio',
  'dio',
  'vsdx',
  'vssx',
  'vstx',
  'gliffy',
  'lucid',
  'lucidchart'
])

const EMBEDDED_DRAWIO_EXTENSIONS = new Set([
  'xml',
  'svg',
  'html',
  'htm',
  'png',
  'jpg',
  'jpeg',
  'pdf'
])

const MERMAID_LANGUAGES = new Set(['mermaid', 'mmd'])

const DRAWIO_MARKERS = [
  '<mxfile',
  '<mxgraphmodel',
  'data-mxgraph=',
  'content="%3cmxfile',
  'content=&quot;%3cmxfile',
  '%3cmxgraphmodel',
  'mxgraphmodel'
]

export function isMermaidLanguage(language) {
  return MERMAID_LANGUAGES.has((language || '').trim().toLowerCase())
}

export function isDirectDrawioExtension(extension) {
  return DIRECT_DRAWIO_EXTENSIONS.has((extension || '').toLowerCase())
}

export function isPotentialDrawioExtension(extension) {
  const normalized = (extension || '').toLowerCase()
  return isDirectDrawioExtension(normalized) || EMBEDDED_DRAWIO_EXTENSIONS.has(normalized)
}

export function contentLooksLikeDrawioText(content = '') {
  const sample = String(content).slice(0, 200000).toLowerCase()
  return DRAWIO_MARKERS.some(marker => sample.includes(marker))
}

export function arrayBufferLooksLikeDrawio(arrayBuffer) {
  if (!(arrayBuffer instanceof ArrayBuffer)) return false
  const sampleBuffer = arrayBuffer.slice(0, Math.min(arrayBuffer.byteLength, 200000))
  try {
    const sample = new TextDecoder('utf-8', { fatal: false }).decode(sampleBuffer).toLowerCase()
    return DRAWIO_MARKERS.some(marker => sample.includes(marker))
  } catch (error) {
    return false
  }
}

function inferMimeType(fileName = '', extension = '') {
  const normalized = (extension || fileName.split('.').pop() || '').toLowerCase()
  const mimeMap = {
    drawio: 'application/xml',
    dio: 'application/xml',
    xml: 'application/xml',
    svg: 'image/svg+xml',
    html: 'text/html;charset=utf-8',
    htm: 'text/html;charset=utf-8',
    png: 'image/png',
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    pdf: 'application/pdf',
    gliffy: 'application/json',
    lucid: 'application/json',
    lucidchart: 'application/json',
    vsdx: 'application/vnd.visio',
    vssx: 'application/vnd.visio',
    vstx: 'application/vnd.visio'
  }

  return mimeMap[normalized] || 'application/octet-stream'
}

export function buildDataUrlFromText(content, mimeType = 'text/plain;charset=utf-8') {
  return `data:${mimeType},${encodeURIComponent(content)}`
}

export function buildDataUrlFromArrayBuffer(arrayBuffer, mimeType = 'application/octet-stream') {
  const bytes = new Uint8Array(arrayBuffer)
  const chunkSize = 0x8000
  let binary = ''

  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize))
  }

  return `data:${mimeType};base64,${btoa(binary)}`
}

export function buildDrawioFileUrl({ dataUrl, fileName = 'diagram.drawio' }) {
  const params = new URLSearchParams({
    ui: 'min',
    chrome: '0',
    nav: '1',
    layers: '1',
    title: '0',
    edit: '_blank',
    dark: 'auto',
    'template-filename': fileName
  })

  return `${DRAWIO_BASE_URL}?${params.toString()}#U${encodeURIComponent(dataUrl)}`
}

export function buildDrawioMermaidUrl(code) {
  const params = new URLSearchParams({
    ui: 'min',
    chrome: '0',
    nav: '1',
    layers: '1',
    title: '0',
    edit: '_blank',
    dark: 'auto',
    create: JSON.stringify({
      type: 'mermaid',
      data: code
    })
  })

  return `${DRAWIO_BASE_URL}?${params.toString()}`
}

export function buildDrawioOpenUrl({ dataUrl, fileName = 'diagram.drawio' }) {
  const params = new URLSearchParams({
    ui: 'min',
    title: fileName,
    edit: '_blank',
    dark: 'auto'
  })

  return `${DRAWIO_BASE_URL}?${params.toString()}#U${encodeURIComponent(dataUrl)}`
}

export function buildDrawioPreviewUrlFromText({ content, fileName, extension, force = false }) {
  if (!force && !contentLooksLikeDrawioText(content)) return ''
  const mimeType = inferMimeType(fileName, extension)
  return buildDrawioOpenUrl({
    dataUrl: buildDataUrlFromText(content, mimeType),
    fileName
  })
}

export function buildDrawioPreviewUrlFromArrayBuffer({ arrayBuffer, fileName, extension, force = false }) {
  if (!force && !arrayBufferLooksLikeDrawio(arrayBuffer)) return ''
  const mimeType = inferMimeType(fileName, extension)
  return buildDrawioOpenUrl({
    dataUrl: buildDataUrlFromArrayBuffer(arrayBuffer, mimeType),
    fileName
  })
}
