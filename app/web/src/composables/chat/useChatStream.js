import { normalizeAgentMode } from '@/utils/agentMode.js'

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
  isHistoryLoading,
  removeSessionFromCache
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
        messageContent = multimodalContent
      } else {
        // Use plain string format otherwise
        messageContent = message
      }

      const requestBody = {
        messages: [{ role: 'user', content: messageContent }],
        session_id: sessionId,
        deep_thinking: config.deepThinking,
        agent_mode: normalizeAgentMode(config.agentMode),
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

  const handleSendMessage = async (content, options = {}) => {
    const { displayContent, multimodalContent } = options
    if (!content.trim() || isLoading.value || !selectedAgent.value) return
    let sessionId = currentSessionId.value
    if (!sessionId) {
      sessionId = await createSession(selectedAgent.value.id)
    }
    await syncSessionIdToRoute(sessionId)
    const shownContent = (displayContent ?? content).trim()
    updateActiveSession(sessionId, true, deriveSessionTitle(shownContent), shownContent, false)
    // 根据 agent 的 enableMultimodal 配置决定是否使用多模态格式
    const enableMultimodal = selectedAgent.value?.enableMultimodal === true
    addUserMessage(shownContent, sessionId, multimodalContent, enableMultimodal)
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
    stopGeneration
  }
}
