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
    updateActiveSession(sessionId, false, null, null, true)
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
        
        // 简单的时间片管理，避免长时间阻塞 UI
        const processStartTime = performance.now()
        
        for (const line of lines) {
          const trimmedLine = line.trim()
          // 忽略空行、心跳行或以冒号开头的 SSE 注释
          if (!trimmedLine || trimmedLine.startsWith(':')) continue
          try {
            const messageData = JSON.parse(trimmedLine)
            if (onMessage) onMessage(messageData)
            
            // 如果单次处理超过 16ms (1帧)，让出主线程
            if (performance.now() - processStartTime > 16) {
              await new Promise(resolve => setTimeout(resolve, 0))
            }
          } catch (e) {
            console.error('JSON Parse Error', e)
          }
        }
        
        // 在每一批数据读取后，也强制让出主线程，确保 WebView2 IPC 能够处理消息
        await new Promise(resolve => setTimeout(resolve, 0))
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
          if (data.type === 'chunk_start' || data.type === 'json_chunk' || data.type === 'chunk_end') return
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
        agent_mode: config.agentMode,
        more_suggest: config.moreSuggest,
        max_loop_count: config.maxLoopCount,
        agent_id: selectedAgent.id,
        system_context: {
          response_language: normalizeResponseLanguage(language?.value)
        }
      }
      if (config.subAgentSelectionMode === 'manual') {
        requestBody.available_sub_agent_ids = Array.isArray(config.availableSubAgentIds) ? config.availableSubAgentIds : []
      }

      const response = await chatAPI.streamChat(requestBody, abortControllerRef?.value)
      // 后端已创建会话，触发同步以在侧边栏显示
      updateActiveSession(sessionId, true)
      let streamLastIndex = 0
      await readStreamResponse(
        response,
        (data) => {
          console.log('[ChatStream] onMessage callback called, data.type:', data.type)
          streamLastIndex += 1
          updateActiveSessionLastIndex(sessionId, streamLastIndex)
          if (streamLastIndex % 20 === 0) updateActiveSessionLastIndex(sessionId, streamLastIndex, true)
          if (data.type === 'stream_end') {
            updateActiveSessionLastIndex(sessionId, streamLastIndex, true)
            markCompletedAndCleanupCurrentSession(sessionId)
          }
          if (data.type === 'chunk_start' || data.type === 'json_chunk' || data.type === 'chunk_end') return
          if (onMessage) {
            console.log('[ChatStream] Calling handleMessage')
            onMessage(data)
          }
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
        agent_mode: config?.agentMode,
        more_suggest: config?.moreSuggest,
        max_loop_count: config?.maxLoopCount,
        agent_id: selectedAgent?.id,
        system_context: {
          response_language: normalizeResponseLanguage(language?.value)
        }
      }
      if (guidanceContent && String(guidanceContent).trim()) {
        requestBody.guidance_content = String(guidanceContent).trim()
        if (guidanceId) requestBody.guidance_id = guidanceId
      }
      if (config?.subAgentSelectionMode === 'manual') {
        requestBody.available_sub_agent_ids = Array.isArray(config?.availableSubAgentIds) ? config.availableSubAgentIds : []
      }

      const response = await chatAPI.rerunConversationStream(sessionId, requestBody, abortControllerRef?.value)
      updateActiveSession(sessionId, true)
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
          if (data.type === 'chunk_start' || data.type === 'json_chunk' || data.type === 'chunk_end') return
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
    
    // 如果需要中断（用户正在生成回复时发送新消息）
    if (needInterrupt && isLoading.value) {
      console.log('[ChatStream] Interrupting current generation before sending new message')
      await stopGeneration()
      // 等待一小段时间确保中断完成
      await new Promise(resolve => setTimeout(resolve, 300))
    }
    
    // 如果中断后 isLoading 仍然是 true，说明中断失败，不继续发送
    if (isLoading.value) {
      console.warn('[ChatStream] Failed to interrupt, cannot send new message')
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
    if (shownContent || hasVisibleMultimodalContent(cleanedMultimodal)) {
      addUserMessage(shownContent, sessionId, cleanedMultimodal)
    }
    try {
      isLoading.value = true
      loadingSessionId.value = sessionId
      shouldAutoScroll.value = true
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
        window.dispatchEvent(new CustomEvent('questionnaire-session-interrupted', {
          detail: { sessionId }
        }))
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
