import { ref, nextTick } from 'vue'

export const useChatScroll = () => {
  const messagesListRef = ref(null)
  const messagesEndRef = ref(null)
  const isUserScrolling = ref(false)
  const isAutoScrolling = ref(false)
  const shouldAutoScroll = ref(true)
  const scrollTimeout = ref(null)

  const scrollToBottom = (force = false) => {
    if (!shouldAutoScroll.value && !force) return
    isAutoScrolling.value = true
    nextTick(() => {
      if (messagesListRef.value) {
        messagesListRef.value.scrollTop = messagesListRef.value.scrollHeight
        setTimeout(() => {
          isAutoScrolling.value = false
        }, 100)
      } else {
        isAutoScrolling.value = false
      }
    })
  }

  const isScrolledToBottom = () => {
    if (!messagesListRef.value) return true
    const { scrollTop, scrollHeight, clientHeight } = messagesListRef.value
    const threshold = 50
    return scrollHeight - scrollTop - clientHeight <= threshold
  }

  const handleScroll = () => {
    if (!messagesListRef.value) return
    if (isAutoScrolling.value) return
    if (scrollTimeout.value) {
      clearTimeout(scrollTimeout.value)
    }
    isUserScrolling.value = true
    const atBottom = isScrolledToBottom()
    shouldAutoScroll.value = !!atBottom
    scrollTimeout.value = setTimeout(() => {
      isUserScrolling.value = false
    }, 150)
  }

  const clearScrollTimer = () => {
    if (scrollTimeout.value) clearTimeout(scrollTimeout.value)
  }

  return {
    messagesListRef,
    messagesEndRef,
    shouldAutoScroll,
    scrollToBottom,
    handleScroll,
    clearScrollTimer
  }
}
