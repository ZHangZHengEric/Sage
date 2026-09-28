const TERMINAL = new Set(['RUN_FINISHED', 'RUN_ERROR'])

export function lastEventIdFromSse(text) {
  let last = ''
  for (const block of String(text || '').split('\n\n')) {
    for (const line of block.split('\n')) {
      if (line.startsWith('id:')) last = line.slice(3).trim()
    }
  }
  return last
}

export function hasTerminalEvent(text) {
  for (const block of String(text || '').split('\n\n')) {
    const data = block
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trim())
      .join('\n')
    if (!data) continue
    try {
      if (TERMINAL.has(JSON.parse(data).type)) return true
    } catch {
      // ignore a torn JSON frame; the next chunk or retry will complete it
    }
  }
  return false
}

export function createResumableFetch({ maxRetries = 3, retryDelayMs = 200 } = {}) {
  return async function resumableFetch(url, init = {}) {
    const signal = init.signal
    let lastEventId = ''

    async function connect() {
      const headers = new Headers(init.headers)
      if (lastEventId) headers.set('Last-Event-ID', lastEventId)
      return fetch(url, { ...init, headers })
    }

    const first = await connect()
    if (!first.ok || !first.body) return first

    const decoder = new TextDecoder()
    let remainder = ''
    let sawTerminal = false
    let retries = 0
    let reader = first.body.getReader()

    const stream = new ReadableStream({
      async pull(controller) {
        while (true) {
          let chunk
          try {
            chunk = await reader.read()
          } catch (error) {
            if (signal?.aborted || sawTerminal || retries >= maxRetries) {
              controller.error(error)
              return
            }
            retries += 1
            await wait(retryDelayMs * retries, signal)
            const next = await connect()
            if (!next.ok || !next.body) {
              controller.error(error)
              return
            }
            reader = next.body.getReader()
            continue
          }

          if (chunk.done) {
            if (sawTerminal || signal?.aborted || retries >= maxRetries) {
              controller.close()
              return
            }
            retries += 1
            await wait(retryDelayMs * retries, signal)
            const next = await connect()
            if (!next.ok || !next.body) {
              controller.close()
              return
            }
            reader = next.body.getReader()
            continue
          }

          remainder += decoder.decode(chunk.value, { stream: true })
          const parts = remainder.split('\n\n')
          remainder = parts.pop() || ''
          const complete = parts.length ? `${parts.join('\n\n')}\n\n` : ''
          if (complete) {
            lastEventId = lastEventIdFromSse(complete) || lastEventId
            sawTerminal = sawTerminal || hasTerminalEvent(complete)
          }
          controller.enqueue(chunk.value)
          return
        }
      },
      cancel(reason) {
        return reader.cancel(reason)
      },
    })

    return new Response(stream, {
      status: first.status,
      statusText: first.statusText,
      headers: first.headers,
    })
  }
}

function wait(ms, signal) {
  if (!ms) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        reject(signal.reason || new DOMException('Aborted', 'AbortError'))
      },
      { once: true },
    )
  })
}
