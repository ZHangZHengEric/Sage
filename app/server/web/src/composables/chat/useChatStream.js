import { normalizeAgentMode } from '@/utils/agentMode.js'

const ENABLE_PLAN_TAG_RE = /^\s*<enable_plan>\s*(true|false)\s*<\/enable_plan>\s*/i
const ENABLE_DEEP_THINKING_TAG_RE = /^\s*<enable_deep_thinking>\s*(true|false)\s*<\/enable_deep_thinking>\s*/i

const stripControlTags = (text) => {
  if (typeof text !== 'string') return { text, enablePlan: false, enableDeepThinking: false }
  let remaining = text
  let enablePlan = false
  let enableDeepThinking = false
  let planMatched = false
  let deepThinkingMatched = false

  while (true) {
    let matched = false
    const planMatch = remaining.match(ENABLE_PLAN_TAG_RE)
    if (planMatch) {
      matched = true
      planMatched = true
      enablePlan = planMatch[1].toLowerCase() === 'true'
      remaining = remaining.slice(planMatch[0].length)
    }
    const deepThinkingMatch = remaining.match(ENABLE_DEEP_THINKING_TAG_RE)
    if (deepThinkingMatch) {
      matched = true
      deepThinkingMatched = true
      enableDeepThinking = deepThinkingMatch[1].toLowerCase() === 'true'
      remaining = remaining.slice(deepThinkingMatch[0].length)
    }
    if (!matched) break
  }

  return {
    text: remaining,
    enablePlan: planMatched ? enablePlan : false,
    enableDeepThinking: deepThinkingMatched ? enableDeepThinking : false
  }
}

const stripControlTagsFromMultimodal = (multimodalContent) => {
  if (!Array.isArray(multimodalContent)) {
    return { content: multimodalContent, enablePlan: false, enableDeepThinking: false }
  }
  const next = []
  let parsedText = false
  let enablePlan = false
  let enableDeepThinking = false

  for (const item of multimodalContent) {
    if (!parsedText && item?.type === 'text' && typeof item.text === 'string') {
      parsedText = true
      const result = stripControlTags(item.text)
      enablePlan = result.enablePlan
      enableDeepThinking = result.enableDeepThinking
      if (result.text) {
        next.push({ ...item, text: result.text })
      }
      continue
    }
    next.push(item)
  }

  return { content: next, enablePlan, enableDeepThinking }
}

const prependControlTags = (text, { enablePlan, enableDeepThinking }) => {
  if (typeof text !== 'string') return text
  const tags = []
  if (typeof enablePlan === 'boolean') {
    tags.push(`<enable_plan>${enablePlan ? 'true' : 'false'}</enable_plan>`)
  }
  if (typeof enableDeepThinking === 'boolean') {
    tags.push(`<enable_deep_thinking>${enableDeepThinking ? 'true' : 'false'}</enable_deep_thinking>`)
  }
  if (tags.length === 0) return text
  return `${tags.join('')} ${text}`.trim()
}

const prependControlTagsToMultimodal = (multimodalContent, controlOptions) => {
  if (!Array.isArray(multimodalContent)) return multimodalContent
  const next = [...multimodalContent]
  const controlText = prependControlTags('', controlOptions)
  if (!controlText) return next

  const textIndex = next.findIndex(item => item?.type === 'text' && typeof item.text === 'string')
  if (textIndex >= 0) {
    next[textIndex] = { ...next[textIndex], text: prependControlTags(next[textIndex].text, controlOptions) }
    return next
  }
  return [{ type: 'text', text: controlText }, ...next]
}

const hasVisibleMultimodalContent = (multimodalContent) => {
  if (!Array.isArray(multimodalContent) || multimodalContent.length === 0) return false
  return multimodalContent.some(item => {
    if (item?.type === 'text') return typeof item.text === 'string' && item.text.trim().length > 0
    return true
  })
}

const normalizeResponseLanguage = (language) => {
  const value = String(language || '').trim()
  if (!value || ['enUS', 'en', 'en-US'].includes(value)) return 'en-US'
  if (['zhCN', 'zh', 'zh-CN'].includes(value)) return 'zh-CN'
  if (['ptBR', 'pt', 'pt-BR'].includes(value)) return 'pt-BR'
  return 'en-US'
}

export const useChatStream = ({
  chatAPI,
  toast,
  t,
  activeSessions,
  getSessionLastIndex,
  updateActiveSessionLastIndex,
  updateActiveSession,
  markSessionInterrupted,
  deriveSessionTitle,
  shouldAutoScroll,
  scrollToBottom,
  isLoading,
  loadingSessionId,
  abortControllerRef,
  currentSessionId,
  selectedAgent,
  config,
  currentTraceId,
  syncSessionIdToRoute,
  addUserMessage,
  addErrorMessage,
  handleMessage,
  createSession,
  clearCurrentStreamViewState,
  loadConversationMessages,
  isHistoryLoading,
  removeSessionFromCache,
  language
}) => {
  const markCompletedAndCleanupCurrentSession = (sessionId) => {
    updateActiveSession(sessionId, false, null, null, false)
    if (currentSessionId.value === sessionId) {
      removeSessionFromCache(sessionId)
    }
  }

  const readStreamResponse = async (response, onMessage, onComplete, onError) => {
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (line.trim() === '') continue
          try {
            const messageData = JSON.parse(line)
            if (onMessage) onMessage(messageData)
          } catch (e) {
            console.error('JSON Parse Error', e)
          }
        }
      }
      if (onComplete) onComplete()
    } catch (e) {
      if (onError) onError(e)
    }
  }

  const checkAndResumeStream = async (sessionId, abortControllerRef, resumeFromIndex = null) => {
    let resumedAndCompleted = false
    isLoading.value = true
    loadingSessionId.value = sessionId
    shouldAutoScroll.value = true
    let resumeLastIndex = Number.isFinite(resumeFromIndex)
      ? Math.max(0, Math.floor(resumeFromIndex))
      : getSessionLastIndex(sessionId)
    
    if (abortControllerRef) {
      abortControllerRef.value = new AbortController()
    }

    try {
      const response = await chatAPI.resumeStream(sessionId, resumeLastIndex, abortControllerRef?.value)
      await readStreamResponse(
        response,
        (data) => {
          resumeLastIndex += 1
          updateActiveSessionLastIndex(sessionId, resumeLastIndex)
          if (resumeLastIndex % 20 === 0) updateActiveSessionLastIndex(sessionId, resumeLastIndex, true)
          if (data.type === 'stream_end') {
            updateActiveSessionLastIndex(sessionId, resumeLastIndex, true)
            resumedAndCompleted = true
            markCompletedAndCleanupCurrentSession(sessionId)
          }
          if (data.type === 'chunk_start' || data.type === 'json_chunk' || data.type === 'chunk_end') {
            return
          }
          handleMessage(data)
        },
        () => {
          isLoading.value = false
          loadingSessionId.value = null
          updateActiveSessionLastIndex(sessionId, resumeLastIndex, true)
          scrollToBottom()
        },
        (err) => {
          if (err?.name === 'AbortError' || err?.originalError?.name === 'AbortError') {
            isLoading.value = false
            loadingSessionId.value = null
            updateActiveSessionLastIndex(sessionId, resumeLastIndex, true)
            return
          }
          isLoading.value = false
          loadingSessionId.value = null
          updateActiveSessionLastIndex(sessionId, resumeLastIndex, true)
          updateActiveSession(sessionId, false, null, null, false)
        }
      )
    } catch (e) {
      if (e?.name === 'AbortError' || e?.originalError?.name === 'AbortError') {
        isLoading.value = false
        loadingSessionId.value = null
        updateActiveSessionLastIndex(sessionId, resumeLastIndex, true)
        return
      }
      isLoading.value = false
      loadingSessionId.value = null
      updateActiveSessionLastIndex(sessionId, resumeLastIndex, true)
      updateActiveSession(sessionId, false, null, null, false)
    }
    return resumedAndCompleted
  }

  const handleSessionLoad = async (sessionId) => {
    if (!sessionId) return
    clearCurrentStreamViewState()
    currentSessionId.value = sessionId
    isHistoryLoading.value = true
    try {
      const conversationData = await loadConversationMessages(sessionId)
      await checkAndResumeStream(sessionId, abortControllerRef, Number(conversationData?.next_stream_index))
    } catch (e) {
      toast.error(t('chat.loadConversationError') || 'Failed to load conversation')
    } finally {
      isLoading.value = false
      isHistoryLoading.value = false
    }
  }

  const sendMessageApi = async ({
    message,
    sessionId,
    selectedAgent,
    config,
    abortControllerRef,
    onMessage,
    onError,
    onComplete,
    multimodalContent
  }) => {
    try {
      if (abortControllerRef) {
        abortControllerRef.value = new AbortController()
      }

      // Check if multimodal is enabled for this agent
      const isMultimodalEnabled = selectedAgent.enableMultimodal === true

      // Determine content format based on multimodal setting
      let messageContent
      if (isMultimodalEnabled && multimodalContent && multimodalContent.length > 0) {
        // Use multimodal format when enabled and content is provided
        messageContent = prependControlTagsToMultimodal(multimodalContent, {
          enableDeepThinking: config.deepThinking
        })
      } else {
        // Use plain string format otherwise
        messageContent = prependControlTags(message, {
          enableDeepThinking: config.deepThinking
        })
      }

      const requestBody = {
        messages: [{ role: 'user', content: messageContent }],
        session_id: sessionId,
        agent_mode: normalizeAgentMode(config.agentMode),
        more_suggest: config.moreSuggest,
        max_loop_count: config.maxLoopCount,
        available_sub_agent_ids: Array.isArray(config.availableSubAgentIds) ? config.availableSubAgentIds : [],
        agent_id: selectedAgent.id,
        system_context: {
          response_language: normalizeResponseLanguage(language?.value)
        }
      }
      const response = await chatAPI.streamChat(requestBody, abortControllerRef?.value)
      let streamLastIndex = 0
      await readStreamResponse(
        response,
        (data) => {
          streamLastIndex += 1
          updateActiveSessionLastIndex(sessionId, streamLastIndex)
          if (streamLastIndex % 20 === 0) updateActiveSessionLastIndex(sessionId, streamLastIndex, true)
          if (data.type === 'stream_end') {
            updateActiveSessionLastIndex(sessionId, streamLastIndex, true)
            markCompletedAndCleanupCurrentSession(sessionId)
          }
          if (data.type === 'chunk_start' || data.type === 'json_chunk' || data.type === 'chunk_end') {
            return
          }
          if (onMessage) onMessage(data)
        },
        () => {
          updateActiveSessionLastIndex(sessionId, streamLastIndex, true)
          if (onComplete) onComplete()
        },
        (err) => {
          if (err.name === 'AbortError') {
            updateActiveSessionLastIndex(sessionId, streamLastIndex, true)
          } else {
            updateActiveSessionLastIndex(sessionId, streamLastIndex, true)
            if (onError) onError(err)
          }
        }
      )
    } catch (error) {
      if (error.name !== 'AbortError') {
        onError(error)
      }
    }
  }

  const rerunSession = async ({
    sessionId,
    selectedAgent,
    config,
    guidanceContent = null,
    guidanceId = null,
    onMessage,
    onError,
    onComplete
  }) => {
    try {
      if (abortControllerRef) {
        abortControllerRef.value = new AbortController()
      }

      const requestBody = {
        agent_mode: normalizeAgentMode(config?.agentMode),
        more_suggest: config?.moreSuggest,
        max_loop_count: config?.maxLoopCount,
        available_sub_agent_ids: Array.isArray(config?.availableSubAgentIds) ? config.availableSubAgentIds : [],
        agent_id: selectedAgent?.id,
        system_context: {
          response_language: normalizeResponseLanguage(language?.value)
        }
      }
      if (guidanceContent && String(guidanceContent).trim()) {
        requestBody.guidance_content = String(guidanceContent).trim()
        if (guidanceId) requestBody.guidance_id = guidanceId
      }

      const response = await chatAPI.rerunConversationStream(sessionId, requestBody, abortControllerRef?.value)
      let streamLastIndex = 0
      await readStreamResponse(
        response,
        (data) => {
          streamLastIndex += 1
          updateActiveSessionLastIndex(sessionId, streamLastIndex)
          if (streamLastIndex % 20 === 0) updateActiveSessionLastIndex(sessionId, streamLastIndex, true)
          if (data.type === 'stream_end') {
            updateActiveSessionLastIndex(sessionId, streamLastIndex, true)
            markCompletedAndCleanupCurrentSession(sessionId)
          }
          if (data.type === 'chunk_start' || data.type === 'json_chunk' || data.type === 'chunk_end') {
            return
          }
          if (onMessage) onMessage(data)
        },
        () => {
          updateActiveSessionLastIndex(sessionId, streamLastIndex, true)
          if (onComplete) onComplete()
        },
        (err) => {
          updateActiveSessionLastIndex(sessionId, streamLastIndex, true)
          if (err.name === 'AbortError') {
            return
          }
          if (onError) onError(err)
        }
      )
    } catch (error) {
      if (error.name !== 'AbortError' && onError) {
        onError(error)
      }
    }
  }

  const handleSendMessage = async (content, options = {}) => {
    const { displayContent, multimodalContent, needInterrupt } = options
    if (!content.trim() || !selectedAgent.value) return

    const contentControl = stripControlTags(content)
    const multimodalControl = stripControlTagsFromMultimodal(multimodalContent)
    const cleanedContent = contentControl.text
    const cleanedMultimodal = multimodalControl.content
    const enablePlan = contentControl.enablePlan || multimodalControl.enablePlan
    const visibleDisplay = displayContent != null ? stripControlTags(displayContent).text : null

    if (!cleanedContent.trim() && !hasVisibleMultimodalContent(cleanedMultimodal) && !enablePlan) return

    if (needInterrupt && isLoading.value) {
      await stopGeneration()
      await new Promise(resolve => setTimeout(resolve, 300))
    }

    if (isLoading.value) {
      toast.error(t('chat.interruptFailed') || '中断当前会话失败，请稍后重试')
      return
    }

    let sessionId = currentSessionId.value
    if (!sessionId) {
      sessionId = await createSession(selectedAgent.value.id)
    }
    await syncSessionIdToRoute(sessionId)
    const shownContent = (visibleDisplay ?? cleanedContent).trim()
    const titleSeed = shownContent || (enablePlan ? 'Planning' : shownContent)
    updateActiveSession(sessionId, true, deriveSessionTitle(titleSeed), shownContent, false)
    // 根据 agent 的 enableMultimodal 配置决定是否使用多模态格式
    const enableMultimodal = selectedAgent.value?.enableMultimodal === true
    if (shownContent || hasVisibleMultimodalContent(cleanedMultimodal)) {
      addUserMessage(shownContent, sessionId, cleanedMultimodal, enableMultimodal)
    }
    try {
      isLoading.value = true
      loadingSessionId.value = sessionId
      shouldAutoScroll.value = true
      // 这里的 scrollToBottom(true) 强制滚动是必要的，因为用户刚发了消息
      scrollToBottom(true)
      await sendMessageApi({
        message: content,
        sessionId,
        selectedAgent: selectedAgent.value,
        config: config.value,
        abortControllerRef,
        multimodalContent,
        onMessage: (data) => {
          if (data.type === 'trace_info') {
            currentTraceId.value = data.trace_id
            return
          }
          handleMessage(data)
        },
        onComplete: async () => {
          scrollToBottom()
          isLoading.value = false
          loadingSessionId.value = null
        },
        onError: (error) => {
          addErrorMessage(error)
          isLoading.value = false
          loadingSessionId.value = null
        }
      })
    } catch (error) {
      toast.error(t('chat.sendError'))
      isLoading.value = false
      loadingSessionId.value = null
    }
  }

  const stopGeneration = async () => {
    const sessionId = currentSessionId.value
    if (abortControllerRef.value) {
      abortControllerRef.value.abort()
      abortControllerRef.value = null
    }
    try {
      if (sessionId) {
        if (typeof markSessionInterrupted === 'function') {
          markSessionInterrupted(sessionId, '用户请求中断', true)
        }
        await chatAPI.interruptSession(sessionId, '用户请求中断')
      }
    } catch (error) {
      console.error('Error interrupting session:', error)
    } finally {
      isLoading.value = false
      loadingSessionId.value = null
    }
  }

  return {
    handleSessionLoad,
    handleSendMessage,
    stopGeneration,
    rerunSession
  }
}
