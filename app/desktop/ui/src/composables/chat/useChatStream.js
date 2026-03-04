export const useChatStream = ({
  chatAPI,
  toast,
  t,
  activeSessions,
  getSessionLastIndex,
  updateActiveSessionLastIndex,
  updateActiveSession,
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
  ensureFirstUserMessageForRunningSession,
  isHistoryLoading,
  removeSessionFromCache,
  shouldRemoveCompletedSession
}) => {
  const markCompletedAndCleanupCurrentSession = (sessionId) => {
    updateActiveSession(sessionId, false, null, null, true)
    if (typeof shouldRemoveCompletedSession === 'function' && shouldRemoveCompletedSession(sessionId)) {
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

  const checkAndResumeStream = async (sessionId) => {
    let resumedAndCompleted = false
    isLoading.value = true
      loadingSessionId.value = sessionId
      // 这里应该只初始化 shouldAutoScroll 为 true（新对话开始时），但后续流式过程中不应反复强制重置
      // 但因为 checkAndResumeStream 是“开始”动作，所以重置为 true 是合理的，
      // 只要后续 handleMessage 不强制重置即可
      shouldAutoScroll.value = true
      let resumeLastIndex = getSessionLastIndex(sessionId)
    abortControllerRef.value = new AbortController()
    try {
      const response = await chatAPI.resumeStream(sessionId, resumeLastIndex, abortControllerRef.value)
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
          // onMessage: handleMessage 已经不强制滚底了
          // 这里也不需要额外逻辑，只要 handleMessage 调用 scrollToBottom()，
          // 并且 shouldAutoScroll 保持用户滚动状态即可
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
      await loadConversationMessages(sessionId)
      ensureFirstUserMessageForRunningSession(sessionId)
      const resumedAndCompleted = await checkAndResumeStream(sessionId)
      if (resumedAndCompleted) {
        await loadConversationMessages(sessionId)
      }
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
    onComplete
  }) => {
    try {
      if (abortControllerRef) {
        abortControllerRef.value = new AbortController()
      }
      const requestBody = {
        messages: [{ role: 'user', content: message }],
        session_id: sessionId,
        deep_thinking: config.deepThinking,
        agent_mode: config.agentMode,
        more_suggest: config.moreSuggest,
        max_loop_count: config.maxLoopCount,
        agent_id: selectedAgent.id
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
          if (data.type === 'chunk_start' || data.type === 'json_chunk' || data.type === 'chunk_end') return
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

  const handleSendMessage = async (content) => {
    if (!content.trim() || isLoading.value || !selectedAgent.value) return
    let sessionId = currentSessionId.value
    if (!sessionId) {
      sessionId = await createSession(selectedAgent.value.id)
    }
    await syncSessionIdToRoute(sessionId)
    updateActiveSession(sessionId, true, deriveSessionTitle(content), content.trim(), false)
    addUserMessage(content, sessionId)
    try {
      isLoading.value = true
      loadingSessionId.value = sessionId
      // 新消息开始，重置自动滚动，因为是用户主动发的
      shouldAutoScroll.value = true
      // 这里的 scrollToBottom(true) 强制滚动是必要的，因为用户刚发了消息
      scrollToBottom(true)
      await sendMessageApi({
        message: content,
        sessionId,
        selectedAgent: selectedAgent.value,
        config: config.value,
        abortControllerRef,
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
    if (abortControllerRef.value) {
      abortControllerRef.value.abort()
      abortControllerRef.value = null
      isLoading.value = false
      loadingSessionId.value = null
    }
    if (currentSessionId.value) {
      try {
        await chatAPI.interruptSession(currentSessionId.value, '用户请求中断')
      } catch (error) {
        console.error('Error interrupting session:', error)
      }
    }
  }

  return {
    handleSessionLoad,
    handleSendMessage,
    stopGeneration
  }
}
