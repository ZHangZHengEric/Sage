/**
 * Static check: t()/tr()/$t() string keys used in source must exist in both zh-CN and en-US.
 *
 * Usage:
 *   node scripts/check-i18n-keys.mjs --src app/server/web/src --zh app/server/web/src/locales/zh-CN.js --en app/server/web/src/locales/en-US.js
 *
 * Does not resolve dynamic keys (e.g. t(variable)); only scans literal first-argument strings.
 * Keys must look like "namespace.something" (must contain a dot) to limit false positives.
 */
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const CHECK_EXT = new Set(['.vue', '.js', '.ts', '.jsx', '.tsx', '.mjs', '.cjs'])
const IGNORE_DIR = new Set(['locales', 'node_modules', 'dist', '.vite', '__tests__', 'tests', 'e2e'])
const IGNORE_FILE = (name) => name.endsWith('.spec.ts') || name.endsWith('.test.ts') || name.endsWith('.spec.js') || name.endsWith('.test.js')

// First arg to t/tr/$t: "foo.bar" or more segments; no dynamic segments
const RE_QUOTED = /\b(?:t|tr|\$t)\(\s*['"]([a-zA-Z][a-zA-Z0-9_]*\.[a-zA-Z0-9_.]+)['"]/g
// t(`foo.bar`) with no ${...} in the same literal (single line)
const RE_TEMPLATE = /\b(?:t|tr|\$t)\(\s*`([a-zA-Z][a-zA-Z0-9_]*\.[a-zA-Z0-9_.]+)`/g

function loadLocaleKeys(filePath) {
  const text = fs.readFileSync(filePath, 'utf8')
  const keys = new Set()
  for (const re of [/'([^']+)'\s*:/g, /"([^"]+)"\s*:/g]) {
    re.lastIndex = 0
    let m
    while ((m = re.exec(text))) {
      if (m[1] && !m[1].includes('\n')) keys.add(m[1])
    }
  }
  return keys
}

function* walkDir(dir) {
  let entries
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true })
  } catch {
    return
  }
  for (const ent of entries) {
    const full = path.join(dir, ent.name)
    if (ent.isDirectory()) {
      if (IGNORE_DIR.has(ent.name)) continue
      yield* walkDir(full)
    } else {
      if (CHECK_EXT.has(path.extname(ent.name)) && !IGNORE_FILE(ent.name)) {
        yield full
      }
    }
  }
}

function extractKeysFromContent(content) {
  const out = new Set()
  for (const re of [RE_QUOTED, RE_TEMPLATE]) {
    re.lastIndex = 0
    let m
    while ((m = re.exec(content))) {
      if (m[1]) out.add(m[1])
    }
  }
  return out
}

function collectUsedKeys(srcRoot) {
  const used = new Set()
  const absRoot = path.resolve(srcRoot)
  if (!fs.existsSync(absRoot)) {
    console.error(`check-i18n-keys: source root not found: ${absRoot}`)
    process.exit(1)
  }
  for (const file of walkDir(absRoot)) {
    const content = fs.readFileSync(file, 'utf8')
    for (const k of extractKeysFromContent(content)) {
      used.add(k)
    }
  }
  return used
}

function parseArgs() {
  const args = process.argv.slice(2)
  const o = { src: null, zh: null, en: null }
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--src' && args[i + 1]) o.src = args[++i]
    else if (args[i] === '--zh' && args[i + 1]) o.zh = args[++i]
    else if (args[i] === '--en' && args[i + 1]) o.en = args[++i]
  }
  return o
}

function main() {
  const { src, zh, en } = parseArgs()
  if (!src || !zh || !en) {
    console.error('Usage: node scripts/check-i18n-keys.mjs --src <srcDir> --zh <zh-CN.js> --en <en-US.js>')
    process.exit(1)
  }

  const zhPath = path.isAbsolute(zh) ? zh : path.resolve(process.cwd(), zh)
  const enPath = path.isAbsolute(en) ? en : path.resolve(process.cwd(), en)
  const srcPath = path.isAbsolute(src) ? src : path.resolve(process.cwd(), src)

  const zhKeys = loadLocaleKeys(zhPath)
  const enKeys = loadLocaleKeys(enPath)
  const used = collectUsedKeys(srcPath)

  const missingZh = []
  const missingEn = []
  for (const k of used) {
    if (!zhKeys.has(k)) missingZh.push(k)
    if (!enKeys.has(k)) missingEn.push(k)
  }
  missingZh.sort()
  missingEn.sort()

  if (missingZh.length || missingEn.length) {
    console.error('i18n key check failed: static t()/tr() keys missing from locale files.')
    if (missingZh.length) {
      console.error(`\nMissing from zh (${missingZh.length}):`)
      for (const k of missingZh) console.error(`  - ${k}`)
    }
    if (missingEn.length) {
      console.error(`\nMissing from en (${missingEn.length}):`)
      for (const k of missingEn) console.error(`  - ${k}`)
    }
    console.error(`\nScanned: ${used.size} unique literal keys under ${srcPath}`)
    process.exit(1)
  }

  console.log(
    `i18n key check ok: ${used.size} literal keys in source; all present in zh-CN and en-US (${path.basename(zhPath)} / ${path.basename(enPath)}).`
  )
}

main()
