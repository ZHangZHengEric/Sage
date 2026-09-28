<template>
  <div class="excalidraw-viewer" ref="containerRef"></div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import React from 'react'
import { createRoot } from 'react-dom/client'
import { Excalidraw } from '@excalidraw/excalidraw'
import '@excalidraw/excalidraw/index.css'

const props = defineProps({
  data: {
    type: Object,
    default: () => null
  },
  theme: {
    type: String,
    default: 'light'
  }
})

const containerRef = ref(null)
let reactRoot = null

const SHAPE_TYPES_WITH_INLINE_TEXT = new Set(['rectangle', 'diamond', 'ellipse'])
const GENERATED_TEXT_SUFFIX = '__generated_text'

const getBackgroundTheme = (backgroundColor) => {
  const color = (backgroundColor || '').trim().toLowerCase()
  if (!color.startsWith('#')) return props.theme

  let hex = color.slice(1)
  if (hex.length === 3) {
    hex = hex.split('').map((char) => char + char).join('')
  }
  if (hex.length !== 6) return props.theme

  const red = parseInt(hex.slice(0, 2), 16)
  const green = parseInt(hex.slice(2, 4), 16)
  const blue = parseInt(hex.slice(4, 6), 16)
  const brightness = (red * 299 + green * 587 + blue * 114) / 1000
  return brightness >= 160 ? 'light' : 'dark'
}

const estimateTextBoxHeight = (text, fontSize, lineHeight) => {
  const lines = String(text || '').split('\n').length
  return Math.max(fontSize, lines * fontSize * lineHeight)
}

const findInnerTextElements = (element, sourceElements) => {
  const left = element.x
  const top = element.y
  const right = element.x + element.width
  const bottom = element.y + element.height

  return sourceElements.filter((candidate) => {
    if (candidate?.type !== 'text' || candidate?.isDeleted) return false
    if (!String(candidate?.text || '').trim()) return false
    if ((candidate?.id || '').endsWith(GENERATED_TEXT_SUFFIX)) return false
    const candidateRight = Number(candidate.x || 0) + Number(candidate.width || 0)
    const candidateBottom = Number(candidate.y || 0) + Number(candidate.height || 0)
    return (
      Number(candidate.x || 0) >= left &&
      Number(candidate.y || 0) >= top &&
      candidateRight <= right &&
      candidateBottom <= bottom
    )
  })
}

const createGeneratedTextElement = (element, sourceElements, index) => {
  const text = String(element.text || '').trim()
  if (!text) return null

  const fontSize = Number(element.fontSize) || 16
  const lineHeight = Number(element.lineHeight) || 1.2
  const textBoxHeight = estimateTextBoxHeight(text, fontSize, lineHeight)
  const horizontalPadding = Math.min(20, Math.max(12, element.width * 0.08))
  const contentWidth = Math.max(32, element.width - horizontalPadding * 2)
  const innerTextElements = findInnerTextElements(element, sourceElements)
  const hasBodyText = innerTextElements.length > 0

  let x = element.x + horizontalPadding
  let width = contentWidth
  let textAlign = element.textAlign || 'center'

  let y = element.y + horizontalPadding
  if (hasBodyText) {
    const titleBandTop = element.y + Math.max(10, element.height * 0.10)
    const titleBandHorizontalPadding = Math.min(24, Math.max(16, element.width * 0.1))
    width = Math.max(40, element.width - titleBandHorizontalPadding * 2)
    x = element.x + (element.width - width) / 2
    y = titleBandTop
    textAlign = 'center'
  } else if (element.verticalAlign === 'middle') {
    y = element.y + (element.height - textBoxHeight) / 2
  } else if (element.verticalAlign === 'bottom') {
    y = element.y + element.height - textBoxHeight - horizontalPadding
  }

  return {
    type: 'text',
    id: `${element.id}${GENERATED_TEXT_SUFFIX}`,
    version: (element.version || 1) + 1,
    versionNonce: (element.versionNonce || 1) + index + 1,
    isDeleted: false,
    groupIds: element.groupIds || [],
    x,
    y,
    width,
    height: textBoxHeight,
    angle: element.angle || 0,
    strokeColor: element.strokeColor || '#2e2e2e',
    backgroundColor: 'transparent',
    fillStyle: 'hachure',
    strokeWidth: 1,
    strokeStyle: 'solid',
    roughness: element.roughness ?? 1,
    opacity: element.opacity ?? 100,
    text,
    fontSize,
    fontFamily: element.fontFamily || 5,
    textAlign,
    verticalAlign: hasBodyText ? 'top' : (element.verticalAlign || 'middle'),
    lineHeight,
    baseline: fontSize
  }
}

const normalizeElements = (elements) => {
  const sourceElements = Array.isArray(elements) ? elements : []
  const normalized = [...sourceElements]
  const existingGeneratedIds = new Set(sourceElements.map((element) => element.id))
  const existingContainerTextIds = new Set(
    sourceElements
      .filter((element) => element?.type === 'text' && element?.containerId)
      .map((element) => element.containerId)
  )

  sourceElements.forEach((element, index) => {
    if (!SHAPE_TYPES_WITH_INLINE_TEXT.has(element?.type)) return
    if (!String(element?.text || '').trim()) return
    if (existingContainerTextIds.has(element.id)) return

    const generatedId = `${element.id}${GENERATED_TEXT_SUFFIX}`
    if (existingGeneratedIds.has(generatedId)) return

    const generatedText = createGeneratedTextElement(element, sourceElements, index)
    if (!generatedText) return

    existingGeneratedIds.add(generatedId)
    normalized.push(generatedText)
  })

  return normalized
}

const buildInitialData = () => {
  const appState = props.data?.appState || {}
  const sceneTheme = appState.theme || getBackgroundTheme(appState.viewBackgroundColor)
  return {
    elements: normalizeElements(props.data?.elements),
    files: props.data?.files || {},
    appState: {
      ...appState,
      theme: sceneTheme,
      viewModeEnabled: true,
      zenModeEnabled: true,
      gridSize: null
    },
    scrollToContent: true
  }
}

const renderReactApp = () => {
  if (!containerRef.value) return
  const initialData = buildInitialData()

  if (!reactRoot) {
    reactRoot = createRoot(containerRef.value)
  }

  reactRoot.render(
    React.createElement(
      'div',
      { className: 'official-excalidraw-host' },
      React.createElement(Excalidraw, {
        theme: initialData.appState.theme || 'light',
        initialData,
        viewModeEnabled: true,
        zenModeEnabled: true,
        gridModeEnabled: false,
        handleKeyboardGlobally: false,
        autoFocus: false,
        name: 'Sage Excalidraw Preview',
        UIOptions: {
          canvasActions: {
            export: false,
            loadScene: false,
            saveToActiveFile: false,
            toggleTheme: false,
            changeViewBackgroundColor: false,
            clearCanvas: false
          }
        },
        renderTopRightUI: () => null
      })
    )
  )
}

onMounted(() => {
  renderReactApp()
})

watch(
  () => [props.data, props.theme],
  () => {
    renderReactApp()
  },
  { deep: true }
)

onUnmounted(() => {
  reactRoot?.unmount?.()
  reactRoot = null
})
</script>

<style scoped>
.excalidraw-viewer {
  width: 100%;
  height: 100%;
  min-height: 420px;
  overflow: hidden;
  background: transparent;
}

:deep(.official-excalidraw-host) {
  width: 100%;
  height: 100%;
}

:deep(.official-excalidraw-host .excalidraw) {
  height: 100%;
}

:deep(.official-excalidraw-host .layer-ui__wrapper__top-right),
:deep(.official-excalidraw-host .layer-ui__wrapper__footer-left),
:deep(.official-excalidraw-host .layer-ui__wrapper__footer-right),
:deep(.official-excalidraw-host .help-icon),
:deep(.official-excalidraw-host .Island.App-menu__left),
:deep(.official-excalidraw-host .Island.App-menu__right) {
  display: none !important;
}
</style>
