/**
 * 与 sagents stream_merger / agent_base 一致：增量合并 tool function.arguments。
 * - 流式大多为「字符串片段」首尾覆盖或首尾拼接；
 * - 禁止用空的 {} 抹掉已累计内容；
 * - 若混入「对象快照」或非空对象，会先序列化后再与存量字符串做同上合并，避免出现
 *   “已有字符串 + 新到字符串却因存量为 object 而整段丢弃” 或 “非空对象整段顶替已拼半的 JSON” 的错乱。
 */

function snapshotArgumentsString (args) {
  if (args == null || args === '') return ''
  if (typeof args === 'string') return args
  if (typeof args === 'object' && !Array.isArray(args)) {
    try {
      return JSON.stringify(args)
    } catch {
      return ''
    }
  }
  return String(args)
}

function mergeSnapshots (aSnap, bSnap) {
  if (!aSnap) return bSnap
  if (!bSnap) return aSnap
  if (bSnap.startsWith(aSnap)) return bSnap
  if (aSnap.startsWith(bSnap)) return aSnap
  return `${aSnap}${bSnap}`
}

export function mergeToolFunctionArguments (existingArgs, incomingArgs) {
  if (incomingArgs === undefined) {
    return existingArgs
  }
  if (incomingArgs === null) {
    return existingArgs !== undefined ? existingArgs : incomingArgs
  }
  if (incomingArgs === '') {
    return existingArgs !== undefined && existingArgs !== null ? existingArgs : incomingArgs
  }

  if (typeof incomingArgs === 'object' && !Array.isArray(incomingArgs)) {
    if (Object.keys(incomingArgs).length === 0) {
      return existingArgs !== undefined && existingArgs !== null ? existingArgs : incomingArgs
    }
  }

  const hasExisting =
    existingArgs !== undefined && existingArgs !== null && existingArgs !== ''

  if (!hasExisting) {
    return typeof incomingArgs === 'object' && !Array.isArray(incomingArgs)
      ? incomingArgs
      : snapshotArgumentsString(incomingArgs)
  }

  const left = snapshotArgumentsString(existingArgs)
  const right = snapshotArgumentsString(incomingArgs)

  return mergeSnapshots(left, right)
}
