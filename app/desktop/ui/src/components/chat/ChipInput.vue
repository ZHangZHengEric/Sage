<template>
  <div
    ref="editorRef"
    class="chip-input"
    :class="[wrapperClass, { 'chip-input--disabled': disabled }]"
    :contenteditable="disabled ? 'false' : 'true'"
    :data-placeholder="placeholder"
    :data-empty="isEmpty ? '' : undefined"
    role="textbox"
    aria-multiline="true"
    spellcheck="false"
    @input="handleInput"
    @keydown="forward('keydown', $event)"
    @keyup="onCaretActivity('keyup', $event)"
    @click="onCaretActivity('click', $event)"
    @paste="forward('paste', $event)"
    @focus="onCaretActivity('focus', $event)"
    @blur="forward('blur', $event)"
    @compositionstart="onCompositionStart"
    @compositionend="onCompositionEnd"
  ></div>
</template>

<script setup>
import { ref, watch, onMounted, computed, nextTick } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  wrapperClass: { type: [String, Array, Object], default: '' }
})

const emit = defineEmits([
  'update:modelValue',
  'keydown',
  'paste',
  'compositionstart',
  'compositionend',
  'focus',
  'blur',
  'caret-update'
])

const editorRef = ref(null)
const isComposing = ref(false)

const ATTACHMENT_PLACEHOLDER_RE = /(!?)\[([^\]]*)\]\(attachment:\/\/([^)]+)\)/g

const isEmpty = computed(() => !props.modelValue || props.modelValue.length === 0)

const buildSegments = (text) => {
  const segments = []
  let last = 0
  ATTACHMENT_PLACEHOLDER_RE.lastIndex = 0
  let m
  while ((m = ATTACHMENT_PLACEHOLDER_RE.exec(text)) !== null) {
    if (m.index > last) {
      segments.push({ type: 'text', text: text.slice(last, m.index) })
    }
    segments.push({
      type: 'chip',
      id: m[3],
      name: m[2] || 'file',
      isImage: m[1] === '!'
    })
    last = ATTACHMENT_PLACEHOLDER_RE.lastIndex
  }
  if (last < text.length) {
    segments.push({ type: 'text', text: text.slice(last) })
  }
  return segments
}

const createChipElement = (seg) => {
  const chip = document.createElement('span')
  chip.setAttribute('contenteditable', 'false')
  chip.className = 'chip-input__chip'
  chip.dataset.attId = seg.id
  chip.dataset.attName = seg.name
  chip.dataset.attIsImage = seg.isImage ? 'true' : 'false'
  chip.title = seg.name

  const icon = document.createElement('span')
  icon.className = 'chip-input__chip-icon'
  icon.textContent = seg.isImage ? '🖼️' : '📎'

  const name = document.createElement('span')
  name.className = 'chip-input__chip-name'
  name.textContent = seg.name

  chip.appendChild(icon)
  chip.appendChild(name)
  return chip
}

const renderText = (text) => {
  const root = editorRef.value
  if (!root) return
  while (root.firstChild) root.removeChild(root.firstChild)

  const segments = buildSegments(text || '')
  if (segments.length === 0) return

  for (const seg of segments) {
    if (seg.type === 'text') {
      const lines = seg.text.split('\n')
      lines.forEach((line, i) => {
        if (i > 0) root.appendChild(document.createElement('br'))
        if (line.length > 0) root.appendChild(document.createTextNode(line))
      })
    } else {
      root.appendChild(createChipElement(seg))
      // 在 chip 后追加一个零宽空格，方便光标定位与中文输入
      root.appendChild(document.createTextNode('\u200B'))
    }
  }
}

const nodeToText = (node) => {
  let s = ''
  for (const child of node.childNodes) {
    if (child.nodeType === Node.TEXT_NODE) {
      s += child.nodeValue.replace(/\u200B/g, '')
    } else if (child.nodeName === 'BR') {
      s += '\n'
    } else if (
      child.nodeType === Node.ELEMENT_NODE &&
      child.classList &&
      child.classList.contains('chip-input__chip')
    ) {
      const id = child.dataset.attId
      const rawName = child.dataset.attName || child.textContent || 'file'
      const name = String(rawName).replace(/\n/g, ' ').trim() || 'file'
      const isImage = child.dataset.attIsImage === 'true'
      const prefix = isImage ? '!' : ''
      s += `${prefix}[${name}](attachment://${id})`
    } else if (child.nodeType === Node.ELEMENT_NODE) {
      // 浏览器在 contenteditable 中常用 <div> 包裹换行段落
      if (s.length > 0 && !s.endsWith('\n')) s += '\n'
      s += nodeToText(child)
    }
  }
  return s
}

const readText = () => {
  const root = editorRef.value
  return root ? nodeToText(root) : ''
}

// 记录最近一次落在编辑器内的光标 range，便于失焦后（如点击下拉选项）仍能精确删除/恢复。
let lastRange = null
const rememberCaret = () => {
  const root = editorRef.value
  if (!root) return
  const sel = window.getSelection()
  if (!sel || sel.rangeCount === 0) return
  const r = sel.getRangeAt(0)
  if (root.contains(r.endContainer)) {
    lastRange = r.cloneRange()
  }
}

const restoreCaret = () => {
  if (!lastRange) return false
  const root = editorRef.value
  if (!root || !root.contains(lastRange.endContainer)) return false
  const sel = window.getSelection()
  if (!sel) return false
  sel.removeAllRanges()
  sel.addRange(lastRange.cloneRange())
  return true
}

const handleInput = () => {
  if (isComposing.value) return
  const text = readText()
  if (text !== props.modelValue) emit('update:modelValue', text)
  rememberCaret()
  emit('caret-update', { source: 'input' })
}

const onCaretActivity = (source, e) => {
  if (source === 'focus') emit('focus', e)
  if (isComposing.value) return
  // 在 keyup/click/focus 时通知父组件重新计算 slash query 等基于光标的状态
  rememberCaret()
  emit('caret-update', { source })
}

const onCompositionStart = (e) => {
  isComposing.value = true
  emit('compositionstart', e)
}

const onCompositionEnd = (e) => {
  isComposing.value = false
  emit('compositionend', e)
  handleInput()
}

const forward = (name, e) => {
  emit(name, e)
}

const placeCaretAtEnd = () => {
  const root = editorRef.value
  if (!root) return
  const range = document.createRange()
  range.selectNodeContents(root)
  range.collapse(false)
  const sel = window.getSelection()
  if (!sel) return
  sel.removeAllRanges()
  sel.addRange(range)
}

watch(() => props.modelValue, (next) => {
  if (readText() === (next || '')) return
  renderText(next || '')
  // 不抢焦点，但若已有焦点则把光标置于末尾
  if (document.activeElement === editorRef.value) {
    placeCaretAtEnd()
  }
})

onMounted(() => {
  if (props.modelValue) {
    renderText(props.modelValue)
  }
})

const focusEditor = (placeAtEnd = true) => {
  const root = editorRef.value
  if (!root) return
  root.focus()
  if (placeAtEnd) placeCaretAtEnd()
}

const insertPlaceholder = (file) => {
  if (!file || file.id == null) return
  const root = editorRef.value
  if (!root) return
  root.focus()
  let sel = window.getSelection()
  let range
  if (sel && sel.rangeCount > 0 && root.contains(sel.anchorNode)) {
    range = sel.getRangeAt(0)
  } else {
    range = document.createRange()
    range.selectNodeContents(root)
    range.collapse(false)
    if (sel) {
      sel.removeAllRanges()
      sel.addRange(range)
    }
  }
  range.deleteContents()
  const chip = createChipElement({
    id: file.id,
    name: file.name || 'file',
    isImage: file.type === 'image'
  })
  range.insertNode(chip)
  const spacer = document.createTextNode('\u200B')
  if (chip.parentNode) {
    chip.parentNode.insertBefore(spacer, chip.nextSibling)
  }
  const newRange = document.createRange()
  newRange.setStartAfter(spacer)
  newRange.collapse(true)
  sel = window.getSelection()
  if (sel) {
    sel.removeAllRanges()
    sel.addRange(newRange)
  }
  handleInput()
}

const insertText = (text) => {
  if (!text) return
  const root = editorRef.value
  if (!root) return
  root.focus()
  let sel = window.getSelection()
  let range
  if (sel && sel.rangeCount > 0 && root.contains(sel.anchorNode)) {
    range = sel.getRangeAt(0)
  } else {
    range = document.createRange()
    range.selectNodeContents(root)
    range.collapse(false)
  }
  range.deleteContents()
  const lines = text.split('\n')
  let lastNode = null
  lines.forEach((line, i) => {
    if (i > 0) {
      const br = document.createElement('br')
      range.insertNode(br)
      range.setStartAfter(br)
      range.collapse(true)
      lastNode = br
    }
    if (line.length > 0) {
      const tn = document.createTextNode(line)
      range.insertNode(tn)
      range.setStartAfter(tn)
      range.collapse(true)
      lastNode = tn
    }
  })
  if (lastNode) {
    const newRange = document.createRange()
    if (lastNode.nodeName === 'BR') {
      newRange.setStartAfter(lastNode)
    } else {
      newRange.setStart(lastNode, lastNode.nodeValue?.length ?? 0)
    }
    newRange.collapse(true)
    sel = window.getSelection()
    if (sel) {
      sel.removeAllRanges()
      sel.addRange(newRange)
    }
  }
  handleInput()
}

const setText = (text) => {
  renderText(text || '')
  if (text === props.modelValue) return
  emit('update:modelValue', text || '')
}

/** 取出"从编辑器开头到当前光标"之间的扁平文本（chip 会渲染为占位符 `![name](attachment://id)`）。 */
const getTextBeforeCaret = () => {
  const root = editorRef.value
  if (!root) return ''
  const sel = window.getSelection()
  if (!sel || sel.rangeCount === 0) return ''
  const range = sel.getRangeAt(0)
  if (!root.contains(range.endContainer)) return ''
  const r = document.createRange()
  r.setStart(root, 0)
  r.setEnd(range.endContainer, range.endOffset)
  const tmp = document.createElement('div')
  tmp.appendChild(r.cloneContents())
  return nodeToText(tmp)
}

/**
 * 检测光标紧挨着的 slash 查询，例如输入 "hello /sea" 光标在 'a' 后会返回 { keyword: 'sea', deleteLength: 4 }。
 * 仅当 `/` 出现在行首或空白后才视为 slash 命令，避免与 URL 等结构冲突。
 */
const SKILL_QUERY_RE = /(?:^|[\s])\/([^\s/<>]*)$/
const getSkillQuery = () => {
  const text = getTextBeforeCaret()
  const m = text.match(SKILL_QUERY_RE)
  if (!m) return null
  return { keyword: m[1] || '', deleteLength: (m[1] || '').length + 1 }
}

/** 删除光标前 N 个字符（基于 Selection.modify，过 chip/换行也按 1 字符跨过）。 */
const deleteCharsBeforeCaret = (n) => {
  if (!n || n <= 0) return
  const root = editorRef.value
  if (!root) return
  // 调用时编辑器可能已失焦（例如点击 popup 选项），先聚焦并恢复上次记忆的 caret。
  root.focus()
  const sel = window.getSelection()
  if (!sel) return
  const inside = sel.rangeCount > 0 && root.contains(sel.getRangeAt(0).endContainer)
  if (!inside) {
    if (!restoreCaret()) return
  }
  if (typeof sel.modify !== 'function' || sel.rangeCount === 0) return
  if (!sel.isCollapsed) sel.collapseToEnd()
  for (let i = 0; i < n; i++) {
    sel.modify('extend', 'backward', 'character')
  }
  if (sel.rangeCount > 0) {
    sel.getRangeAt(0).deleteContents()
    sel.collapseToStart()
  }
  rememberCaret()
  handleInput()
}

/**
 * 上传完成后用真实的服务端文件名刷新 chip：
 * - 更新 dataset.attName / title / 文本节点，让 readText() 生成的占位符 alt 与 URL 末段一致；
 * - 同步触发一次 update:modelValue，让父组件持有的 inputValue 跟着变。
 */
const updateChipName = (id, newName) => {
  if (id == null || !newName) return false
  const root = editorRef.value
  if (!root) return false
  const target = root.querySelector(`.chip-input__chip[data-att-id="${CSS.escape(String(id))}"]`)
  if (!target) return false
  target.dataset.attName = newName
  target.setAttribute('title', newName)
  const nameNode = target.querySelector('.chip-input__chip-name')
  if (nameNode) nameNode.textContent = newName
  // 触发一次同步：让 readText() 的输出立即写回 modelValue
  handleInput()
  return true
}

defineExpose({
  focus: focusEditor,
  insertPlaceholder,
  insertText,
  setText,
  getElement: () => editorRef.value,
  getTextBeforeCaret,
  getSkillQuery,
  deleteCharsBeforeCaret,
  updateChipName
})
</script>

<style scoped>
.chip-input {
  width: 100%;
  min-height: 44px;
  max-height: 200px;
  overflow-y: auto;
  outline: none;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.875rem;
  line-height: 1.6;
  padding: 6px 4px;
  cursor: text;
}

.chip-input--disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.chip-input[data-empty]::before {
  content: attr(data-placeholder);
  color: hsl(var(--muted-foreground));
  pointer-events: none;
  display: block;
}
</style>

<!-- 非 scoped：chip 元素由 JS 动态创建，没有 data-v-xxx 属性，scoped 选择器匹配不到 -->
<style>
.chip-input__chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px 2px 8px;
  margin: 0 3px;
  background: hsl(var(--primary) / 0.12);
  color: hsl(var(--primary));
  border: 1px solid hsl(var(--primary) / 0.35);
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
  user-select: none;
  vertical-align: baseline;
  white-space: nowrap;
  max-width: 220px;
  box-shadow: 0 1px 2px hsl(var(--primary) / 0.08);
  transition: background 0.15s ease, border-color 0.15s ease;
}

.chip-input__chip:hover {
  background: hsl(var(--primary) / 0.18);
  border-color: hsl(var(--primary) / 0.55);
}

.chip-input__chip-icon {
  font-size: 14px;
  line-height: 1;
  flex-shrink: 0;
}

.chip-input__chip-name {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
