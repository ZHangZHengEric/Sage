import { execFileSync } from 'node:child_process'
import process from 'node:process'

const FRONTEND_SOURCE_ROOT = 'app/server/web/src/'
const CHECKABLE_EXTENSIONS = ['.vue', '.js', '.ts', '.jsx', '.tsx']
const IGNORE_SEGMENTS = ['/locales/', '/__tests__/', '/tests/']
const IGNORE_SUFFIXES = ['.spec.js', '.spec.ts', '.test.js', '.test.ts', '.spec.vue', '.test.vue']
const HAN_PATTERN = /[\p{Script=Han}]/u

export function shouldCheckFile(filePath) {
  if (!filePath.startsWith(FRONTEND_SOURCE_ROOT)) return false
  if (!CHECKABLE_EXTENSIONS.some((ext) => filePath.endsWith(ext))) return false
  if (IGNORE_SEGMENTS.some((segment) => filePath.includes(segment))) return false
  if (IGNORE_SUFFIXES.some((suffix) => filePath.endsWith(suffix))) return false
  return true
}

function isIgnorableLine(trimmedLine) {
  return (
    !trimmedLine
    || trimmedLine.startsWith('//')
    || trimmedLine.startsWith('/*')
    || trimmedLine.startsWith('*')
    || trimmedLine.startsWith('*/')
    || trimmedLine.startsWith('<!--')
    || trimmedLine.startsWith('* @')
  )
}

function looksLocalized(trimmedLine) {
  return trimmedLine.includes('t(') || trimmedLine.includes('$t(')
}

export function collectViolationsFromDiff(diffText) {
  const violations = []
  let currentFile = null
  let currentLineNumber = 0

  for (const rawLine of diffText.split('\n')) {
    if (rawLine.startsWith('+++ b/')) {
      currentFile = rawLine.slice(6)
      currentLineNumber = 0
      continue
    }

    if (!currentFile || !shouldCheckFile(currentFile)) continue

    if (rawLine.startsWith('@@')) {
      const match = rawLine.match(/\+(?<start>\d+)/)
      currentLineNumber = match?.groups?.start ? Number(match.groups.start) - 1 : 0
      continue
    }

    if (rawLine.startsWith('+') && !rawLine.startsWith('+++')) {
      currentLineNumber += 1
      const content = rawLine.slice(1)
      const trimmed = content.trim()
      if (isIgnorableLine(trimmed) || looksLocalized(trimmed)) continue
      if (!HAN_PATTERN.test(content)) continue
      violations.push({
        file: currentFile,
        lineNumber: currentLineNumber,
        line: trimmed,
      })
      continue
    }

    if (rawLine.startsWith(' ')) {
      currentLineNumber += 1
    }
  }

  return violations
}

function getBaseRef() {
  const baseRef = process.env.GITHUB_BASE_REF
  if (baseRef) return `origin/${baseRef}`
  return 'origin/main'
}

function getDiffText() {
  const targetRef = getBaseRef()
  try {
    execFileSync('git', ['fetch', 'origin', '--quiet'], { stdio: 'ignore' })
  } catch {}

  let mergeBase = targetRef
  try {
    mergeBase = execFileSync('git', ['merge-base', 'HEAD', targetRef], { encoding: 'utf8' }).trim()
  } catch {}

  try {
    return execFileSync('git', ['diff', '--unified=0', '--no-color', mergeBase, 'HEAD', '--', FRONTEND_SOURCE_ROOT], {
      encoding: 'utf8',
    })
  } catch (error) {
    if (error.stdout) return error.stdout
    throw error
  }
}

function main() {
  const diffText = getDiffText()
  const violations = collectViolationsFromDiff(diffText)

  if (!violations.length) {
    console.log('No new hard-coded Chinese frontend copy found.')
    return
  }

  console.error('Found new hard-coded Chinese frontend copy. Use i18n keys instead:')
  for (const violation of violations) {
    console.error(`- ${violation.file}:${violation.lineNumber} ${violation.line}`)
  }
  process.exitCode = 1
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main()
}
