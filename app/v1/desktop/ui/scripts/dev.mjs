import { execFileSync, spawn } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const uiRoot = resolve(__dirname, '..')
const viteBin = resolve(uiRoot, 'node_modules', 'vite', 'bin', 'vite.js')
const devPort = 1420

function cleanupDevPort() {
  if (process.platform === 'win32') {
    try {
      const output = execFileSync('netstat', ['-ano', '-p', 'tcp'], { encoding: 'utf8' })
      const pids = new Set()
      for (const line of output.split(/\r?\n/)) {
        const match = line.match(/^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$/i)
        if (match && Number(match[1]) === devPort) {
          pids.add(match[2])
        }
      }
      for (const pid of pids) {
        execFileSync('taskkill', ['/F', '/PID', pid], { stdio: 'ignore' })
      }
    } catch {
      // Ignore missing listeners and continue to start Vite.
    }
    return
  }

  try {
    execFileSync('sh', ['-c', `lsof -ti:${devPort} | xargs kill -9 2>/dev/null || true`], {
      stdio: 'ignore',
    })
  } catch {
    // Ignore missing listeners and continue to start Vite.
  }
}

cleanupDevPort()

const child = spawn(process.execPath, [viteBin, ...process.argv.slice(2)], {
  cwd: uiRoot,
  stdio: 'inherit',
  env: process.env,
})

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal)
    return
  }
  process.exit(code ?? 0)
})
