const offlineView = document.getElementById("offlineView");
const chatView = document.getElementById("chatView");
const offlineStatusText = document.getElementById("offlineStatusText");
const offlineProbeLine = document.getElementById("offlineProbeLine");
const redetectBtn = document.getElementById("redetectBtn");
const historyToggleBtn = document.getElementById("historyToggleBtn");
const historyPanel = document.getElementById("historyPanel");
const historyList = document.getElementById("historyList");
const historyRefreshBtn = document.getElementById("historyRefreshBtn");
const debugToggleBtn = document.getElementById("debugToggleBtn");
const debugPanel = document.getElementById("debugPanel");
const debugContent = document.getElementById("debugContent");
const planToggleBtn = document.getElementById("planToggleBtn");
const deepThinkToggleBtn = document.getElementById("deepThinkToggleBtn");
const agentSelect = document.getElementById("agentSelect");
const messagesEl = document.getElementById("messages");
const chatForm = document.getElementById("chatForm");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("sendBtn");
const screenshotBtn = document.getElementById("screenshotBtn");

function createDesktopStyleSessionId() {
  return `session_${Date.now()}`;
}

const state = {
  apiBase: "",
  connected: false,
  sessionId: createDesktopStyleSessionId(),
  sending: false,
  historyOpen: false,
  debugOpen: false,
  planEnabled: false,
  deepThinkEnabled: false,
  pendingScreenshotDataUrl: ""
};

const PLUGIN_SOURCE_CHANNEL = "browser_sidepanel";
const REQUIRED_BROWSER_TOOLS = [
  "browser_get_context",
  "browser_navigate",
  "browser_dom_action"
];

const ALL_BROWSER_TOOLS = [
  "browser_get_context",
  "browser_navigate",
  "browser_find_text",
  "browser_scroll",
  "browser_send_keys",
  "browser_wait",
  "browser_list_tabs",
  "browser_switch_tab",
  "browser_select_dropdown",
  "browser_upload_file",
  "browser_screenshot",
  "browser_dom_action"
];
let isComposing = false;

function showOffline(message) {
  state.connected = false;
  closeHistoryPanel();
  closeDebugPanel();
  offlineView.classList.remove("hidden");
  chatView.classList.add("hidden");
  offlineStatusText.textContent = message || "未检测到 Sage Desktop 服务，请先启动本地 Desktop。";
}

function showChat(message) {
  state.connected = true;
  offlineView.classList.add("hidden");
  chatView.classList.remove("hidden");
  sendBtn.disabled = state.sending;
  inputEl.disabled = state.sending;
  if (message) {
    addSystemMessage(message);
  }
}

function addMessage(role, content) {
  const div = document.createElement("div");
  div.className = `message ${role}`;
  setMessageContent(div, role, content || "");
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function escapeHtml(input) {
  return String(input || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderInlineMarkdown(text) {
  const source = String(text || "");
  const linkTokens = [];
  const textWithLinkTokens = source.replace(/\[([^\]]+)\]\s*\(([^)]+)\)/g, (full, label, hrefRaw) => {
    const href = String(hrefRaw || "").trim();
    if (!/^(https?:\/\/|file:\/\/|\/)/i.test(href)) {
      return full;
    }
    const token = `@@INLINE_LINK_${linkTokens.length}@@`;
    linkTokens.push({
      label: String(label || "").trim() || href,
      href
    });
    return token;
  });

  let html = escapeHtml(textWithLinkTokens);
  html = html.replace(/@@INLINE_LINK_(\d+)@@/g, (_m, idx) => {
    const link = linkTokens[Number(idx)];
    if (!link) return "";
    return `<a href="${escapeHtml(link.href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(link.label)}</a>`;
  });

  html = html.replace(/(^|[\s(])(file:\/\/[^\s)]+)/g, "$1<a href=\"$2\" target=\"_blank\" rel=\"noopener noreferrer\">$2</a>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  return html;
}

function renderMarkdownToHtml(text) {
  const source = String(text || "");
  if (!source.trim()) return "";

  const codeBlocks = [];
  const withoutCode = source.replace(/```([\w-]*)\n?([\s\S]*?)```/g, (_m, _lang, code) => {
    const index = codeBlocks.length;
    codeBlocks.push(`<pre><code>${escapeHtml(code)}</code></pre>`);
    return `@@CODE_BLOCK_${index}@@`;
  });

  const lines = withoutCode.split("\n");
  const chunks = [];
  let bulletListBuffer = [];
  let orderedListBuffer = [];

  const flushLists = () => {
    if (bulletListBuffer.length > 0) {
      chunks.push(`<ul>${bulletListBuffer.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ul>`);
      bulletListBuffer = [];
    }
    if (orderedListBuffer.length > 0) {
      chunks.push(`<ol>${orderedListBuffer.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ol>`);
      orderedListBuffer = [];
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    const listMatch = line.match(/^\s*[-*]\s+(.+)$/);
    const orderedListMatch = line.match(/^\s*\d+\.\s+(.+)$/);
    const hrMatch = trimmed.match(/^([-*])\1{2,}$/);

    if (headingMatch) {
      flushLists();
      const level = Math.min(6, headingMatch[1].length);
      chunks.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      continue;
    }

    if (listMatch) {
      orderedListBuffer = [];
      bulletListBuffer.push(listMatch[1]);
      continue;
    }

    if (orderedListMatch) {
      bulletListBuffer = [];
      orderedListBuffer.push(orderedListMatch[1]);
      continue;
    }

    if (hrMatch) {
      flushLists();
      chunks.push("<hr>");
      continue;
    }

    flushLists();
    if (!trimmed) {
      chunks.push("<br>");
      continue;
    }
    chunks.push(`<p>${renderInlineMarkdown(line)}</p>`);
  }
  flushLists();

  let html = chunks.join("");
  html = html.replace(/@@CODE_BLOCK_(\d+)@@/g, (_m, idx) => codeBlocks[Number(idx)] || "");
  return html;
}

function setMessageContent(div, role, content) {
  const value = String(content || "");
  div.dataset.rawText = value;
  if (role === "assistant" || role === "user" || role === "system") {
    div.innerHTML = renderMarkdownToHtml(value);
    return;
  }
  div.textContent = value;
}

function addSystemMessage(content) {
  // Avoid spamming duplicate system notices.
  const items = messagesEl.querySelectorAll(".message.system");
  const last = items.length > 0 ? items[items.length - 1] : null;
  if (last && (last.dataset.rawText || last.textContent) === content) return;
  addMessage("system", content);
}

function addToolStatusMessage(toolName, ok) {
  const div = document.createElement("div");
  div.className = `message tool ${ok ? "success" : "fail"}`;
  const icon = document.createElement("span");
  icon.className = "tool-status-icon";
  icon.setAttribute("aria-hidden", "true");
  const text = document.createElement("span");
  text.className = "tool-status-text";
  text.textContent = `${toolName}`;
  div.appendChild(icon);
  div.appendChild(text);
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function getTextFromContent(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  const textParts = [];
  for (const item of content) {
    if (item?.type === "text" && typeof item.text === "string") {
      textParts.push(item.text);
    }
  }
  return textParts.join("\n").trim();
}

function parseToolSuccess(content) {
  const asObject = (value) => (typeof value === "object" && value ? value : null);

  const evaluateObject = (obj) => {
    if (!obj) return null;
    if (typeof obj.success === "boolean") return obj.success;
    if (typeof obj.ok === "boolean") return obj.ok;
    if (typeof obj.code === "number" && obj.code >= 400) return false;
    if (typeof obj.status === "string") {
      const s = obj.status.toLowerCase();
      if (["error", "failed", "fail", "timeout", "exception"].includes(s)) return false;
      if (["ok", "success", "completed", "done"].includes(s)) return true;
    }
    if (obj.error || obj.error_message || obj.exception) return false;
    if (typeof obj.result === "object" && obj.result) {
      const nested = evaluateObject(obj.result);
      if (typeof nested === "boolean") return nested;
    }
    return null;
  };

  const direct = evaluateObject(asObject(content));
  if (typeof direct === "boolean") return direct;

  if (typeof content === "string") {
    const raw = content.trim();
    if (!raw) return true;
    try {
      const parsed = JSON.parse(raw);
      const fromParsed = evaluateObject(asObject(parsed));
      if (typeof fromParsed === "boolean") return fromParsed;
      return true;
    } catch (_err) {
      const normalized = raw.toLowerCase();
      const failureHints = ["error", "failed", "fail", "exception", "traceback", "超时", "失败", "错误"];
      for (const hint of failureHints) {
        if (normalized.includes(hint)) return false;
      }
      return true;
    }
  }

  return true;
}

function appendAssistantChunk(existingContent, incomingContent) {
  if (!incomingContent) return existingContent || "";
  if (!existingContent) return incomingContent;
  if (incomingContent.startsWith(existingContent)) return incomingContent;
  return `${existingContent}${incomingContent}`;
}

function hasImageContent(content) {
  if (!Array.isArray(content)) return false;
  return content.some((item) => item?.type === "image_url" && item?.image_url?.url);
}

function formatConversationTime(input) {
  if (!input) return "";
  const date = new Date(input);
  if (Number.isNaN(date.getTime())) return "";
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  const hour = `${date.getHours()}`.padStart(2, "0");
  const minute = `${date.getMinutes()}`.padStart(2, "0");
  return `${month}-${day} ${hour}:${minute}`;
}

function closeHistoryPanel() {
  state.historyOpen = false;
  historyPanel?.classList.add("hidden");
}

function openHistoryPanel() {
  state.historyOpen = true;
  historyPanel?.classList.remove("hidden");
}

function closeDebugPanel() {
  state.debugOpen = false;
  debugPanel?.classList.add("hidden");
}

function openDebugPanel() {
  state.debugOpen = true;
  debugPanel?.classList.remove("hidden");
}

function renderHistoryList(conversations) {
  if (!historyList) return;
  historyList.innerHTML = "";

  if (!Array.isArray(conversations) || conversations.length === 0) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "暂无历史会话";
    historyList.appendChild(empty);
    return;
  }

  for (const conv of conversations) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "history-item";
    btn.dataset.sessionId = conv.session_id || "";

    const title = document.createElement("div");
    title.className = "history-item-title";
    title.textContent = conv.title || "新会话";

    const time = document.createElement("div");
    time.className = "history-item-time";
    time.textContent = formatConversationTime(conv.updated_at || conv.created_at);

    btn.appendChild(title);
    btn.appendChild(time);
    btn.addEventListener("click", async () => {
      const sessionId = btn.dataset.sessionId || "";
      if (!sessionId) return;
      await switchConversation(sessionId);
    });
    historyList.appendChild(btn);
  }
}

async function loadConversations() {
  if (!state.connected || !state.apiBase) return;
  if (historyList) {
    historyList.innerHTML = `<div class="history-empty">加载中...</div>`;
  }
  try {
    const response = await fetch(`${state.apiBase}/api/conversations?page=1&page_size=40&sort_by=date`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    const list = Array.isArray(payload?.data?.list) ? payload.data.list : [];
    renderHistoryList(list);
  } catch (err) {
    if (historyList) {
      historyList.innerHTML = `<div class="history-empty">加载失败: ${err.message}</div>`;
    }
  }
}

function buildSystemContext(activeTab = {}, pageContext = {}) {
  const browserToolText = ALL_BROWSER_TOOLS.join(", ");
  return {
    source_channel: PLUGIN_SOURCE_CHANNEL,
    current_browser_context: {
      title: activeTab.title || pageContext.title || "",
      url: activeTab.url || pageContext.url || "",
      selected_text: pageContext.selectedText || "",
      body_excerpt: pageContext.bodyTextExcerpt || ""
    },
    execution_suggestion: {
      note: `当前请求来自浏览器侧边栏，你正在浏览器环境中。可优先使用这些浏览器工具进行网页操作：${browserToolText}`
    }
  };
}

function buildDebugSnapshot(agentId, systemContext) {
  return {
    session_id: state.sessionId,
    agent_id: agentId || "",
    system_context: systemContext
  };
}

async function refreshDebugSnapshot() {
  if (!debugContent) return;
  if (!state.connected || !state.apiBase) {
    debugContent.textContent = "当前未连接到 Desktop 服务。";
    return;
  }
  try {
    await askWorker({ type: "heartbeat-now" });
    const browserStatus = await fetchBrowserStatusContext();
    const activeTab = browserStatus.active_tab || {};
    const pageContext = browserStatus.page_context || {};
    const agentId = agentSelect?.value || "";
    const systemContext = buildSystemContext(activeTab, pageContext);
    const snapshot = buildDebugSnapshot(agentId, systemContext);
    debugContent.textContent = JSON.stringify(snapshot, null, 2);
  } catch (err) {
    debugContent.textContent = `调试信息获取失败: ${err.message}`;
  }
}

function replayConversationMessages(messages) {
  messagesEl.innerHTML = "";
  const toolCallNameMap = new Map();
  const messageElById = new Map();
  for (const [index, msg] of (messages || []).entries()) {
    const messageId = msg?.message_id || "";
    if (msg?.role === "assistant") {
      const text = getTextFromContent(msg.content);
      const key = messageId || `__history_assistant_${index}`;
      let target = messageElById.get(key) || null;
      if (!target && text) {
        target = addMessage("assistant", text || "");
        messageElById.set(key, target);
      } else if (target && text) {
        const merged = appendAssistantChunk(target.dataset.rawText || "", text);
        setMessageContent(target, "assistant", merged);
      }
      if (Array.isArray(msg.tool_calls)) {
        for (const toolCall of msg.tool_calls) {
          const toolId = toolCall?.id;
          const toolName = toolCall?.function?.name || "unknown_tool";
          if (toolId) toolCallNameMap.set(toolId, toolName);
        }
      }
      continue;
    }

    if (msg?.role === "tool" && msg?.tool_call_id) {
      const toolName = toolCallNameMap.get(msg.tool_call_id) || "unknown_tool";
      const ok = parseToolSuccess(msg.content);
      addToolStatusMessage(toolName, ok);
      continue;
    }

    if (msg?.role === "user") {
      const text = getTextFromContent(msg.content);
      if (text) {
        addMessage("user", text);
      } else if (hasImageContent(msg.content)) {
        addMessage("user", "[图片]");
      }
      continue;
    }

    if (msg?.role === "system") {
      const text = getTextFromContent(msg.content) || String(msg.content || "");
      if (text) addMessage("system", text);
    }
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function switchConversation(sessionId) {
  if (!state.connected || !state.apiBase || !sessionId) return;
  try {
    const response = await fetch(`${state.apiBase}/api/conversations/${encodeURIComponent(sessionId)}/messages`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    const data = payload?.data || {};
    const historyMessages = Array.isArray(data.messages) ? data.messages : [];
    state.sessionId = sessionId;
    replayConversationMessages(historyMessages);

    const conversationAgentId = data?.conversation_info?.agent_id || "";
    if (conversationAgentId && agentSelect && agentSelect.querySelector(`option[value="${conversationAgentId}"]`)) {
      agentSelect.value = conversationAgentId;
    }

    closeHistoryPanel();
    addSystemMessage("已切换到历史会话。");
  } catch (err) {
    addSystemMessage(`加载会话失败: ${err.message}`);
  }
}

async function askWorker(message) {
  return await chrome.runtime.sendMessage(message);
}

async function detectBackend(force = false) {
  const resp = await askWorker({ type: "detect-backend", force });
  if (!resp?.ok) {
    throw new Error(resp?.error || "detect failed");
  }
  const data = resp.state || {};
  state.apiBase = data.apiBase || "";
  if (offlineProbeLine) {
    offlineProbeLine.textContent = data.lastProbeLine || "未发现可用 /active 接口";
  }
  if (data.detected && state.apiBase) {
    showChat();
  } else {
    showOffline(data.lastError || "未检测到 Sage Desktop 服务，请先启动本地 Desktop。");
  }
  return data;
}

async function loadAgents() {
  if (!state.connected || !state.apiBase) return;
  try {
    const response = await fetch(`${state.apiBase}/api/agent/list`);
    const payload = await response.json();
    const list = Array.isArray(payload?.data) ? payload.data : [];
    agentSelect.innerHTML = "";

    if (list.length === 0) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "暂无 Agent";
      agentSelect.appendChild(option);
      return;
    }

    for (const agent of list) {
      const option = document.createElement("option");
      option.value = agent.id;
      option.textContent = agent.name || agent.id;
      agentSelect.appendChild(option);
    }
  } catch (err) {
    addSystemMessage(`加载 Agent 失败: ${err.message}`);
  }
}

async function fetchBrowserStatusContext() {
  if (!state.connected || !state.apiBase) return {};
  try {
    const response = await fetch(`${state.apiBase}/api/browser-extension/status`);
    if (!response.ok) return {};
    const payload = await response.json();
    return payload?.data || {};
  } catch (_err) {
    return {};
  }
}

async function captureScreenshotDataUrl() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs || tabs.length === 0) {
    throw new Error("未找到当前活动标签页");
  }
  const activeTab = tabs[0];
  if (!activeTab.windowId) {
    throw new Error("无法获取当前窗口信息");
  }
  return await chrome.tabs.captureVisibleTab(activeTab.windowId, { format: "png" });
}

function handleStreamEvent(data, streamState) {
  if (!data || typeof data !== "object") return;

  if (data.type === "chunk_start") {
    const total = Number(data.total_chunks || 0);
    if (total > 0 && data.message_id) {
      streamState.chunkMap.set(data.message_id, new Array(total).fill(""));
    }
    return;
  }

  if (data.type === "json_chunk") {
    const arr = streamState.chunkMap.get(data.message_id);
    if (!arr) return;
    const index = Number(data.chunk_index || 0);
    if (index >= 0 && index < arr.length) {
      arr[index] = data.chunk_data || "";
    }
    return;
  }

  if (data.type === "chunk_end") {
    const arr = streamState.chunkMap.get(data.message_id);
    if (!arr) return;
    streamState.chunkMap.delete(data.message_id);
    try {
      const payload = JSON.parse(arr.join(""));
      handleStreamEvent(payload, streamState);
    } catch (_err) {
      // ignore malformed payload
    }
    return;
  }

  if (data.role === "assistant") {
    const text = getTextFromContent(data.content);
    const messageId = data.message_id || "__stream_assistant__";
    let target = streamState.messageElById.get(messageId);
    if (!target && text) {
      target = addMessage("assistant", text);
      streamState.messageElById.set(messageId, target);
    } else if (target && text) {
      const merged = appendAssistantChunk(target.dataset.rawText || "", text);
      setMessageContent(target, "assistant", merged);
    }
    if (text) streamState.receivedVisibleMessage = true;
    if (Array.isArray(data.tool_calls)) {
      for (const toolCall of data.tool_calls) {
        const toolId = toolCall?.id;
        const toolName = toolCall?.function?.name || "unknown_tool";
        if (toolId) {
          streamState.toolCallNameMap.set(toolId, toolName);
        }
      }
    }
    return;
  }

  if (data.role === "tool" && data.tool_call_id) {
    const key = data.tool_call_id;
    const toolName = streamState.toolCallNameMap.get(data.tool_call_id) || "unknown_tool";
    const ok = parseToolSuccess(data.content);
    const existing = streamState.toolStatusElByCallId.get(key);
    if (existing) {
      existing.classList.remove("success", "fail");
      existing.classList.add(ok ? "success" : "fail");
      const textNode = existing.querySelector(".tool-status-text");
      if (textNode) textNode.textContent = toolName;
    } else {
      const el = addToolStatusMessage(toolName, ok);
      streamState.toolStatusElByCallId.set(key, el);
    }
    streamState.receivedVisibleMessage = true;
    return;
  }
}

function parseStreamLine(line, streamState) {
  if (!line) return;
  const normalized = line.startsWith("data:") ? line.slice(5).trim() : line;
  if (!normalized || normalized === "[DONE]") return;
  let data;
  try {
    data = JSON.parse(normalized);
  } catch (_err) {
    return;
  }
  handleStreamEvent(data, streamState);
}

async function sendChat() {
  const rawContent = inputEl.value.trim();
  const agentId = agentSelect.value;
  const hasScreenshot = Boolean(state.pendingScreenshotDataUrl);
  if (!rawContent && !hasScreenshot) return;
  if (!agentId) {
    addSystemMessage("请先在 Desktop 创建并选择一个 Agent。");
    return;
  }
  if (!state.connected || !state.apiBase) {
    showOffline("服务连接已断开，请重新检测。");
    return;
  }

  // Keep page context fresh before each user message.
  await askWorker({ type: "heartbeat-now" });
  const browserStatus = await fetchBrowserStatusContext();
  const activeTab = browserStatus.active_tab || {};
  const pageContext = browserStatus.page_context || {};
  const systemContext = buildSystemContext(activeTab, pageContext);

  let content = rawContent
  if (state.planEnabled) {
    content = `<enable_plan>true</enable_plan>${content ? ` ${content}` : ""}`
  }
  if (state.deepThinkEnabled) {
    content = `<enable_deep_thinking>true</enable_deep_thinking>${content ? ` ${content}` : ""}`
  }

  let userContent = content;
  if (hasScreenshot) {
    const multimodalContent = [];
    if (content) {
      multimodalContent.push({ type: "text", text: content });
    }
    multimodalContent.push({
      type: "image_url",
      image_url: { url: state.pendingScreenshotDataUrl }
    });
    userContent = multimodalContent;
  }

  state.sending = true;
  sendBtn.disabled = true;
  inputEl.disabled = true;

  const userPreview = rawContent || "（仅发送截屏）";
  addMessage("user", hasScreenshot ? `${userPreview}\n[已附加截图]` : userPreview);
  inputEl.value = "";
  const streamState = {
    receivedVisibleMessage: false,
    chunkMap: new Map(),
    messageElById: new Map(),
    toolCallNameMap: new Map(),
    toolStatusElByCallId: new Map()
  };

  const payload = {
    session_id: state.sessionId,
    agent_id: agentId,
    messages: [{ role: "user", content: userContent }],
    system_context: systemContext
  };

  try {
    const response = await fetch(`${state.apiBase}/api/web-stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let raw = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      raw += decoder.decode(value, { stream: true });
      const lines = raw.split("\n");
      raw = lines.pop() || "";
      for (const line of lines) {
        parseStreamLine(line.trim(), streamState);
      }
    }
    if (raw.trim()) {
      parseStreamLine(raw.trim(), streamState);
    }

    if (!streamState.receivedVisibleMessage) {
      addSystemMessage("已发送，等待更多响应...");
    }
  } catch (err) {
    addSystemMessage(`发送失败: ${err.message}`);
  } finally {
    if (hasScreenshot) {
      state.pendingScreenshotDataUrl = "";
      screenshotBtn?.classList.remove("active");
    }
    state.sending = false;
    sendBtn.disabled = false;
    inputEl.disabled = false;
  }
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await sendChat();
});

inputEl.addEventListener("compositionstart", () => {
  isComposing = true;
});

inputEl.addEventListener("compositionend", () => {
  isComposing = false;
});

inputEl.addEventListener("keydown", async (event) => {
  if (event.key === "Enter" && !event.shiftKey && !isComposing) {
    event.preventDefault();
    await sendChat();
  }
});

redetectBtn.addEventListener("click", async () => {
  const previousText = redetectBtn.textContent;
  redetectBtn.textContent = "检测中...";
  redetectBtn.disabled = true;
  try {
    await detectBackend(true);
    if (state.connected) {
      await askWorker({ type: "heartbeat-now" });
      await askWorker({ type: "poll-command-now" });
      await loadAgents();
    }
  } finally {
    redetectBtn.disabled = false;
    redetectBtn.textContent = previousText || "重新检测";
  }
});

if (historyToggleBtn) {
  historyToggleBtn.addEventListener("click", async (event) => {
    event.stopPropagation();
    if (state.historyOpen) {
      closeHistoryPanel();
      return;
    }
    openHistoryPanel();
    await loadConversations();
  });
}

if (historyRefreshBtn) {
  historyRefreshBtn.addEventListener("click", async (event) => {
    event.stopPropagation();
    await loadConversations();
  });
}

if (debugToggleBtn) {
  debugToggleBtn.addEventListener("click", async (event) => {
    event.stopPropagation();
    if (state.debugOpen) {
      closeDebugPanel();
      return;
    }
    openDebugPanel();
    await refreshDebugSnapshot();
  });
}

document.addEventListener("click", (event) => {
  const target = event.target;
  if (state.historyOpen && historyPanel && historyToggleBtn) {
    if (!historyPanel.contains(target) && !historyToggleBtn.contains(target)) {
      closeHistoryPanel();
    }
  }
  if (state.debugOpen && debugPanel && debugToggleBtn) {
    if (!debugPanel.contains(target) && !debugToggleBtn.contains(target)) {
      closeDebugPanel();
    }
  }
});

planToggleBtn.addEventListener("click", () => {
  state.planEnabled = !state.planEnabled;
  planToggleBtn.classList.toggle("active", state.planEnabled);
});

deepThinkToggleBtn.addEventListener("click", () => {
  state.deepThinkEnabled = !state.deepThinkEnabled;
  deepThinkToggleBtn.classList.toggle("active", state.deepThinkEnabled);
});

if (screenshotBtn) {
  screenshotBtn.addEventListener("click", async () => {
    try {
      const dataUrl = await captureScreenshotDataUrl();
      state.pendingScreenshotDataUrl = dataUrl || "";
      screenshotBtn.classList.toggle("active", Boolean(state.pendingScreenshotDataUrl));
      if (state.pendingScreenshotDataUrl) {
        addSystemMessage("已截屏，将随下一条消息发送。");
      }
    } catch (err) {
      addSystemMessage(`截屏失败: ${err.message}`);
    }
  });
}

async function bootstrap() {
  try {
    const detected = await detectBackend(true);
    if (detected.detected) {
      await loadAgents();
      await askWorker({ type: "heartbeat-now" });
      await askWorker({ type: "poll-command-now" });
    }
  } catch (err) {
    showOffline(`检测失败: ${err.message}`);
  }
}

setInterval(async () => {
  try {
    const detected = await detectBackend(false);
    if (detected.detected) {
      await askWorker({ type: "heartbeat-now" });
      await askWorker({ type: "poll-command-now" });
    }
  } catch (_err) {
    // ignore periodic errors
  }
}, 12000);

bootstrap();
