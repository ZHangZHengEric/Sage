const DEFAULT_CANDIDATE_BASES = [
  "http://127.0.0.1:18080",
  "http://localhost:18080",
  "http://127.0.0.1:18081",
  "http://localhost:18081",
  "http://127.0.0.1:18082",
  "http://localhost:18082",
  "http://127.0.0.1:8080",
  "http://localhost:8080",
  "http://127.0.0.1:8000",
  "http://localhost:8000",
  "http://127.0.0.1:18090",
  "http://localhost:18090"
];

const DEFAULT_STATE = {
  detected: false,
  apiBase: "",
  lastActiveAt: 0,
  lastError: "",
  lastProbeLine: ""
};

const COMMAND_RUNTIME_STATE = {
  polling: false,
  executing: false,
  currentCommandId: "",
  lastCommandAt: 0,
};

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function getState() {
  const { sageState } = await chrome.storage.local.get("sageState");
  return { ...DEFAULT_STATE, ...(sageState || {}) };
}

async function setState(patch) {
  const next = { ...(await getState()), ...patch };
  await chrome.storage.local.set({ sageState: next });
  return next;
}

async function fetchJson(base, path, options = {}) {
  const response = await fetch(`${base}${path}`, {
    method: options.method || "GET",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const data = await response.json();
  return data;
}

async function fetchWithTimeout(url, timeoutMs = 800) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { method: "GET", signal: controller.signal });
    return response;
  } finally {
    clearTimeout(timer);
  }
}

async function checkBackend(base) {
  try {
    const response = await fetchWithTimeout(`${base}/active`, 800);
    if (!response.ok) return false;
    const text = (await response.text()).trim().toLowerCase();
    return text.includes("service is available");
  } catch (_err) {
    return false;
  }
}

async function probeBackend(base) {
  try {
    const response = await fetchWithTimeout(`${base}/active`, 800);
    if (!response.ok) {
      return { ok: false, reason: `HTTP ${response.status}` };
    }
    const text = (await response.text()).trim().toLowerCase();
    if (text.includes("service is available")) {
      return { ok: true, reason: "active-ok" };
    }
    return { ok: false, reason: "active-mismatch" };
  } catch (err) {
    return { ok: false, reason: err?.name === "AbortError" ? "timeout" : "network-error" };
  }
}

async function scanFallbackPorts() {
  const scannedBases = [];
  // Bounded scan range for desktop fallback ports.
  for (let port = 18083; port <= 18120; port++) {
    scannedBases.push(`http://127.0.0.1:${port}`);
    scannedBases.push(`http://localhost:${port}`);
  }

  const batchSize = 12;
  for (let i = 0; i < scannedBases.length; i += batchSize) {
    const batch = scannedBases.slice(i, i + batchSize);
    const checks = await Promise.all(batch.map(async (base) => ({ base, ok: await checkBackend(base) })));
    const matched = checks.find((item) => item.ok);
    if (matched) return matched.base;
  }
  return "";
}

async function detectBackend(force = false) {
  const state = await getState();
  if (state.detected && state.apiBase && !force) {
    try {
      if (await checkBackend(state.apiBase)) {
        return state;
      }
    } catch (err) {
      console.warn("Current backend unavailable, redetecting", err);
    }
  }

  const { customApiBase, recentApiBase } = await chrome.storage.local.get(["customApiBase", "recentApiBase"]);
  const candidates = [];
  if (customApiBase && typeof customApiBase === "string") {
    candidates.push(customApiBase.trim());
  }
  if (recentApiBase && typeof recentApiBase === "string") {
    candidates.push(recentApiBase.trim());
  }
  candidates.push(...DEFAULT_CANDIDATE_BASES);
  const diagnostics = [];

  for (const base of candidates) {
    if (!base) continue;
    const result = await probeBackend(base);
    diagnostics.push(`${base} -> ${result.reason}`);
    if (result.ok) {
      await chrome.storage.local.set({ recentApiBase: base });
      return await setState({
        detected: true,
        apiBase: base,
        lastActiveAt: Date.now(),
        lastError: "",
        lastProbeLine: `已命中 ${base}`
      });
    }
  }

  const scanned = await scanFallbackPorts();
  if (scanned) {
    await chrome.storage.local.set({ recentApiBase: scanned });
    return await setState({
      detected: true,
      apiBase: scanned,
      lastActiveAt: Date.now(),
      lastError: "",
      lastProbeLine: `端口扫描命中 ${scanned}`
    });
  }

  const probeLine = diagnostics.slice(0, 6).join(" | ");

  return await setState({
    detected: false,
    apiBase: "",
    lastError: "Sage Desktop service not found on localhost",
    lastProbeLine: probeLine || "未发现可用 /active 接口"
  });
}

async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs || tabs.length === 0) return null;
  const tab = tabs[0];
  return {
    id: tab.id,
    title: tab.title || "",
    url: tab.url || "",
    windowId: tab.windowId
  };
}

async function readPageContext(tabId) {
  if (!tabId) return null;
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const bodyText = (document.body?.innerText || "").replace(/\s+/g, " ").trim();
        const selectedText = window.getSelection ? String(window.getSelection()) : "";
        const isVisible = (el) => {
          if (!el) return false;
          const style = window.getComputedStyle(el);
          if (!style || style.display === "none" || style.visibility === "hidden") return false;
          const rect = el.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        };
        const interactiveNodes = Array.from(
          document.querySelectorAll(
            "a,button,input,textarea,select,[role='button'],[role='link'],[role='textbox'],[contenteditable='true'],[tabindex]"
          )
        )
          .filter(isVisible)
          .slice(0, 120)
          .map((el, idx) => ({
            dom_id: `d${idx}`,
            tag: (el.tagName || "").toLowerCase(),
            text: (el.innerText || el.textContent || "").trim().slice(0, 80),
            role: el.getAttribute("role") || "",
            type: el.getAttribute("type") || "",
            placeholder: el.getAttribute("placeholder") || "",
            aria_label: el.getAttribute("aria-label") || "",
          }));
        const serializedLines = interactiveNodes.map((node) => {
          const chunks = [node.dom_id, node.tag];
          if (node.role) chunks.push(`role=${node.role}`);
          if (node.type) chunks.push(`type=${node.type}`);
          if (node.placeholder) chunks.push(`placeholder=${node.placeholder}`);
          if (node.text) chunks.push(`text=${node.text}`);
          return chunks.join(" | ");
        });
        return {
          schema_version: "browser_context.v2",
          title: document.title || "",
          url: location.href,
          domain: location.hostname || "",
          language: document.documentElement?.lang || "",
          ready_state: document.readyState,
          selectedText: selectedText.slice(0, 5000),
          page_summary: bodyText.slice(0, 1200),
          dom_nodes: interactiveNodes,
          serialized_dom: serializedLines.join("\n"),
        };
      }
    });
    return results?.[0]?.result || null;
  } catch (err) {
    return {
      error: `Cannot read page context: ${err?.message || String(err)}`
    };
  }
}

async function listWindowTabs(windowId) {
  const tabs = await chrome.tabs.query({ windowId });
  return (tabs || []).map((tab) => ({
    id: tab.id,
    windowId: tab.windowId,
    active: Boolean(tab.active),
    title: tab.title || "",
    url: tab.url || "",
    status: tab.status || "",
  }));
}

async function resolveTargetTabId(args, activeTab) {
  if (args?.tabId) {
    const parsed = Number(args.tabId);
    if (Number.isFinite(parsed) && parsed > 0) return parsed;
  }
  if (args?.tab_id) {
    const parsed = Number(args.tab_id);
    if (Number.isFinite(parsed) && parsed > 0) return parsed;
  }
  if (args?.tabIdSuffix || args?.tab_id_suffix) {
    const suffix = String(args.tabIdSuffix || args.tab_id_suffix);
    const tabs = await listWindowTabs(activeTab?.windowId);
    const matched = tabs.find((tab) => String(tab.id || "").endsWith(suffix));
    if (matched?.id) return matched.id;
  }
  return activeTab?.id || null;
}

function parseDomIndex(args) {
  const raw = args?.domId || args?.dom_id || "";
  if (!raw) return null;
  const text = String(raw).trim().toLowerCase();
  const matched = text.match(/^d(\d+)$/);
  if (!matched) return null;
  const idx = Number(matched[1]);
  if (!Number.isFinite(idx) || idx < 0) return null;
  return idx;
}

async function waitForTabComplete(tabId, timeoutMs = 30000) {
  const timeout = Math.max(1000, Math.min(180000, Number(timeoutMs) || 30000));
  const start = Date.now();

  try {
    const current = await chrome.tabs.get(tabId);
    if (current?.status === "complete") {
      return { ok: true, waitMs: Date.now() - start, status: "complete" };
    }
  } catch (err) {
    return { ok: false, error: `Tab unavailable: ${err?.message || String(err)}` };
  }

  return await new Promise((resolve) => {
    let done = false;
    let timer = null;

    const finish = (payload) => {
      if (done) return;
      done = true;
      if (timer) clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      resolve(payload);
    };

    const onUpdated = (updatedTabId, changeInfo) => {
      if (updatedTabId !== tabId) return;
      if (changeInfo?.status === "complete") {
        finish({ ok: true, waitMs: Date.now() - start, status: "complete" });
      }
    };

    chrome.tabs.onUpdated.addListener(onUpdated);
    timer = setTimeout(() => {
      finish({
        ok: false,
        error: `Timed out waiting tab complete after ${timeout}ms`,
        waitedMs: Date.now() - start,
      });
    }, timeout);
  });
}

async function probeDocumentReady(tabId) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => ({
        readyState: document.readyState,
        hasBody: Boolean(document.body),
        url: location.href,
        title: document.title || "",
      }),
    });
    return { ok: true, ...(results?.[0]?.result || {}) };
  } catch (err) {
    return { ok: false, error: err?.message || String(err) };
  }
}

async function waitForDocumentReady(tabId, timeoutMs = 12000) {
  const timeout = Math.max(500, Math.min(60000, Number(timeoutMs) || 12000));
  const start = Date.now();
  let lastProbe = null;

  while (Date.now() - start <= timeout) {
    lastProbe = await probeDocumentReady(tabId);
    if (
      lastProbe?.ok &&
      Boolean(lastProbe?.hasBody) &&
      (lastProbe?.readyState === "interactive" || lastProbe?.readyState === "complete")
    ) {
      return { ok: true, waitMs: Date.now() - start, ready: lastProbe };
    }
    await sleep(180);
  }

  return {
    ok: false,
    error: `Timed out waiting DOM ready after ${timeout}ms`,
    waitedMs: Date.now() - start,
    lastProbe,
  };
}

async function waitForNavigationSettled(tabId, timeoutMs = 30000) {
  const complete = await waitForTabComplete(tabId, timeoutMs);
  if (!complete.ok) return { ok: false, stage: "tab-complete", detail: complete };
  const remaining = Math.max(1500, timeoutMs - (complete.waitMs || 0));
  const dom = await waitForDocumentReady(tabId, remaining);
  if (!dom.ok) return { ok: false, stage: "dom-ready", detail: dom };
  return { ok: true, complete, dom };
}

async function ensureTabInteractionReady(tabId, timeoutMs = 10000) {
  const dom = await waitForDocumentReady(tabId, timeoutMs);
  if (!dom.ok) {
    throw new Error(dom.error || "Page is not ready for interaction");
  }
  return dom.ready;
}

async function sendHeartbeat() {
  const state = await detectBackend(false);
  if (!state.detected || !state.apiBase) return state;

  const activeTab = await getActiveTab();
  const pageContext = activeTab?.id ? await readPageContext(activeTab.id) : null;
  try {
    await fetchJson(state.apiBase, "/api/browser-extension/heartbeat", {
      method: "POST",
      body: {
        extension_id: chrome.runtime.id,
        extension_version: chrome.runtime.getManifest().version,
        active_tab: activeTab,
        page_context: pageContext,
        capabilities: [
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
          "browser_dom_action",
        ]
      }
    });
    return await setState({
      detected: true,
      lastActiveAt: Date.now(),
      lastError: ""
    });
  } catch (err) {
    return await setState({
      detected: false,
      apiBase: "",
      lastError: `Heartbeat failed: ${err?.message || String(err)}`
    });
  }
}

async function executeCommand(command) {
  const activeTab = await getActiveTab();
  const args = command?.args || {};
  const action = command?.action;
  let tabId = await resolveTargetTabId(args, activeTab);
  const readyTimeoutMs = Math.max(
    800,
    Math.min(
      60000,
      Math.round(Number(args.readyTimeoutSeconds || args.ready_timeout_seconds || 10) * 1000)
    )
  );

  if (!tabId && !["wait"].includes(action)) {
    throw new Error("No active tab found.");
  }

  if (action === "navigate") {
    if (!args.url) throw new Error("navigate requires args.url");
    const navTimeoutMs = Math.max(
      3000,
      Math.min(
        180000,
        Math.round(Number(args.timeoutSeconds || args.timeout_seconds || 30) * 1000)
      )
    );
    await chrome.tabs.update(tabId, { url: args.url });
    const settled = await waitForNavigationSettled(tabId, navTimeoutMs);
    if (!settled.ok) {
      return {
        ok: false,
        error: "Navigation did not fully settle",
        navigatedTo: args.url,
        settle: settled,
      };
    }
    return { ok: true, navigatedTo: args.url, settle: settled };
  }

  if (action === "click") {
    await ensureTabInteractionReady(tabId, readyTimeoutMs);
    const selector = args.selector || args.cssSelector || "";
    const domIndex = parseDomIndex(args);
    const index = domIndex ?? Number(args.index);
    const textHint = String(args.text || args.textHint || "").trim();
    if (!selector && !Number.isFinite(index) && !textHint) {
      throw new Error("click requires args.selector or args.index or args.text");
    }
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      args: [selector, Number.isFinite(index) ? index : null, textHint],
      func: (selectorValue, indexValue, textValue) => {
        const isVisible = (el) => {
          if (!el) return false;
          const style = window.getComputedStyle(el);
          if (!style || style.display === "none" || style.visibility === "hidden") return false;
          const rect = el.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        };
        const resolveByText = (text) => {
          if (!text) return null;
          const normalized = text.toLowerCase();
          const candidates = Array.from(
            document.querySelectorAll(
              "button,a,[role='button'],[role='link'],input[type='button'],input[type='submit'],label,span,div"
            )
          ).filter(isVisible);
          let best = null;
          let bestScore = -1;
          for (const candidate of candidates) {
            const content = (candidate.innerText || candidate.textContent || "").trim();
            if (!content) continue;
            const lower = content.toLowerCase();
            let score = 0;
            if (lower === normalized) score = 100;
            else if (lower.includes(normalized)) score = 60;
            else if (normalized.includes(lower) && lower.length >= 2) score = 40;
            if (score > bestScore) {
              bestScore = score;
              best = candidate;
            }
          }
          return bestScore > 0 ? best : null;
        };

        let element = null;
        if (typeof indexValue === "number" && indexValue >= 0) {
          const candidates = Array.from(
            document.querySelectorAll(
              "a,button,input,textarea,select,[role='button'],[role='link'],[contenteditable='true'],[tabindex]"
            )
          ).filter(isVisible);
          element = candidates[indexValue] || null;
        }
        if (!element && selectorValue) {
          element = document.querySelector(selectorValue) || null;
          if (element && !isVisible(element)) element = null;
        }
        if (!element) element = resolveByText(textValue);
        if (!element) return { ok: false, error: "Element not found" };
        if (typeof element.scrollIntoView === "function") {
          element.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
        }
        element.click();
        return { ok: true };
      }
    });
    return results?.[0]?.result || { ok: false, error: "Unknown click result" };
  }

  if (action === "fill") {
    await ensureTabInteractionReady(tabId, readyTimeoutMs);
    const selector = args.selector || args.cssSelector || "";
    const domIndex = parseDomIndex(args);
    const index = domIndex ?? Number(args.index);
    const textHint = String(args.text || args.textHint || "").trim();
    if (!selector && !Number.isFinite(index) && !textHint) {
      throw new Error("fill requires args.selector or args.index or args.text");
    }
    const value = typeof args.value === "string" ? args.value : "";
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      args: [selector, Number.isFinite(index) ? index : null, textHint, value, Boolean(args.submit)],
      func: (selectorValue, indexValue, textValue, text, submit) => {
        const isVisible = (el) => {
          if (!el) return false;
          const style = window.getComputedStyle(el);
          if (!style || style.display === "none" || style.visibility === "hidden") return false;
          const rect = el.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        };
        const resolveByText = (hint) => {
          if (!hint) return null;
          const normalized = hint.toLowerCase();
          const candidates = Array.from(document.querySelectorAll("input,textarea,[contenteditable='true']"))
            .filter(isVisible);
          let best = null;
          let bestScore = -1;
          for (const candidate of candidates) {
            const bag = [
              candidate.getAttribute("placeholder") || "",
              candidate.getAttribute("name") || "",
              candidate.getAttribute("aria-label") || "",
              candidate.id || "",
              candidate.labels?.[0]?.innerText || "",
            ].join(" ").toLowerCase();
            let score = 0;
            if (bag.includes(normalized)) score = 80;
            if ((candidate.type || "").toLowerCase() === normalized) score = Math.max(score, 40);
            if (score > bestScore) {
              best = candidate;
              bestScore = score;
            }
          }
          return bestScore > 0 ? best : null;
        };

        let element = null;
        if (typeof indexValue === "number" && indexValue >= 0) {
          const candidates = Array.from(
            document.querySelectorAll("input,textarea,[contenteditable='true'],select")
          ).filter(isVisible);
          element = candidates[indexValue] || null;
        }
        if (!element && selectorValue) {
          element = document.querySelector(selectorValue);
          if (element && !isVisible(element)) element = null;
        }
        if (!element) element = resolveByText(textValue);
        if (!element) return { ok: false, error: "Element not found" };
        if (typeof element.scrollIntoView === "function") {
          element.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
        }
        element.focus();
        if ("value" in element) {
          element.value = text;
          element.dispatchEvent(new Event("input", { bubbles: true }));
          element.dispatchEvent(new Event("change", { bubbles: true }));
        } else {
          element.textContent = text;
        }
        if (submit) {
          const form = element.closest("form");
          if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
        }
        return { ok: true };
      }
    });
    return results?.[0]?.result || { ok: false, error: "Unknown fill result" };
  }

  if (action === "select_dropdown") {
    await ensureTabInteractionReady(tabId, readyTimeoutMs);
    const selector = String(args.selector || args.cssSelector || "");
    const domIndex = parseDomIndex(args);
    const index = domIndex ?? Number(args.index);
    const text = String(args.text || args.value || args.option || "").trim();
    if (!selector && !Number.isFinite(index)) {
      throw new Error("select_dropdown requires args.selector or args.index");
    }
    if (!text) throw new Error("select_dropdown requires args.text/value");

    const results = await chrome.scripting.executeScript({
      target: { tabId },
      args: [selector, Number.isFinite(index) ? index : null, text],
      func: (selectorValue, indexValue, textValue) => {
        const isVisible = (el) => {
          if (!el) return false;
          const style = window.getComputedStyle(el);
          if (!style || style.display === "none" || style.visibility === "hidden") return false;
          const rect = el.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        };
        let element = null;
        if (typeof indexValue === "number" && indexValue >= 0) {
          const candidates = Array.from(document.querySelectorAll("select,[role='listbox'],[role='combobox']"))
            .filter(isVisible);
          element = candidates[indexValue] || null;
        }
        if (!element && selectorValue) {
          element = document.querySelector(selectorValue);
          if (element && !isVisible(element)) element = null;
        }
        if (!element) return { ok: false, error: "Dropdown element not found" };

        const normalized = textValue.toLowerCase();
        if (element.tagName.toLowerCase() === "select") {
          const options = Array.from(element.options || []);
          const found = options.find((opt) => {
            const t = (opt.text || "").trim().toLowerCase();
            const v = (opt.value || "").trim().toLowerCase();
            return t === normalized || v === normalized || t.includes(normalized);
          });
          if (!found) {
            return { ok: false, error: `Option not found: ${textValue}` };
          }
          element.value = found.value;
          found.selected = true;
          element.dispatchEvent(new Event("input", { bubbles: true }));
          element.dispatchEvent(new Event("change", { bubbles: true }));
          return { ok: true, value: found.value, text: found.text };
        }

        // ARIA/custom dropdown fallback
        if (element.getAttribute("aria-expanded") === "false" || element.getAttribute("aria-expanded") === null) {
          element.click();
        }
        const listboxId = element.getAttribute("aria-controls");
        const listRoot = (listboxId && document.getElementById(listboxId))
          || document.querySelector("[role='listbox'],[role='menu']");
        if (!listRoot) return { ok: false, error: "Dropdown list not found" };
        const options = Array.from(listRoot.querySelectorAll("[role='option'],[role='menuitem'],.option,.item"));
        const found = options.find((opt) => {
          const text = (opt.textContent || "").trim().toLowerCase();
          const value = (opt.getAttribute("data-value") || "").toLowerCase();
          return text === normalized || value === normalized || text.includes(normalized);
        });
        if (!found) return { ok: false, error: `Option not found: ${textValue}` };
        found.click();
        return { ok: true, text: (found.textContent || "").trim(), value: found.getAttribute("data-value") || "" };
      },
    });
    return results?.[0]?.result || { ok: false, error: "Unknown select_dropdown result" };
  }

  if (action === "upload_file") {
    await ensureTabInteractionReady(tabId, readyTimeoutMs);
    const selector = String(args.selector || args.cssSelector || "");
    const domIndex = parseDomIndex(args);
    const index = domIndex ?? Number(args.index);
    const fileName = String(args.fileName || args.file_name || "upload.bin");
    const mimeType = String(args.mimeType || args.file_mime_type || "application/octet-stream");
    const base64Data = String(
      args.fileDataBase64 || args.file_data_base64 || args.file_data || ""
    );
    if (!selector && !Number.isFinite(index)) {
      throw new Error("upload_file requires args.selector or args.index");
    }
    if (!base64Data) throw new Error("upload_file requires base64 file data");

    const results = await chrome.scripting.executeScript({
      target: { tabId },
      args: [selector, Number.isFinite(index) ? index : null, fileName, mimeType, base64Data],
      func: (selectorValue, indexValue, nameValue, mimeValue, dataValue) => {
        const isVisible = (el) => {
          if (!el) return false;
          const style = window.getComputedStyle(el);
          if (!style || style.display === "none" || style.visibility === "hidden") return false;
          const rect = el.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        };
        let input = null;
        if (typeof indexValue === "number" && indexValue >= 0) {
          const candidates = Array.from(document.querySelectorAll("input[type='file']")).filter(isVisible);
          input = candidates[indexValue] || null;
        }
        if (!input && selectorValue) {
          const el = document.querySelector(selectorValue);
          if (el && el.tagName?.toLowerCase() === "input" && el.type === "file") {
            input = el;
          }
        }
        if (!input) return { ok: false, error: "File input not found" };

        const binary = atob(dataValue);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i += 1) {
          bytes[i] = binary.charCodeAt(i);
        }
        const file = new File([bytes], nameValue, { type: mimeValue });
        const dt = new DataTransfer();
        dt.items.add(file);
        input.files = dt.files;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        return { ok: true, fileName: nameValue, size: file.size, mimeType: mimeValue };
      },
    });
    return results?.[0]?.result || { ok: false, error: "Unknown upload_file result" };
  }

  if (action === "screenshot") {
    const format = String(args.format || "png").toLowerCase() === "jpeg" ? "jpeg" : "png";
    const qualityRaw = Number(args.quality);
    const quality = Number.isFinite(qualityRaw) ? Math.max(0, Math.min(100, qualityRaw)) : 85;

    const currentActiveTab = await getActiveTab();
    if (!currentActiveTab?.windowId) {
      throw new Error("No active window for screenshot");
    }

    // CaptureVisibleTab captures active tab in the target window.
    if (currentActiveTab.id !== tabId && tabId) {
      await chrome.tabs.update(tabId, { active: true });
      await waitForDocumentReady(tabId, readyTimeoutMs);
    }

    const dataUrl = await chrome.tabs.captureVisibleTab(currentActiveTab.windowId, {
      format,
      quality,
    });

    const meta = await chrome.tabs.get(tabId);
    return {
      ok: true,
      format,
      quality,
      data_url: dataUrl,
      tab: {
        id: meta.id,
        title: meta.title || "",
        url: meta.url || "",
        windowId: meta.windowId,
      },
    };
  }

  if (action === "extract_text") {
    await ensureTabInteractionReady(tabId, readyTimeoutMs);
    const selector = args.selector || "body";
    const maxChars = Number(args.maxChars || 12000);
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      args: [selector, maxChars],
      func: (selectorValue, maxValue) => {
        const element = document.querySelector(selectorValue);
        if (!element) return { ok: false, error: "Element not found" };
        const text = (element.innerText || element.textContent || "").replace(/\s+/g, " ").trim();
        return { ok: true, text: text.slice(0, Math.max(0, maxValue || 12000)) };
      }
    });
    return results?.[0]?.result || { ok: false, error: "Unknown extract result" };
  }

  if (action === "run_script") {
    await ensureTabInteractionReady(tabId, readyTimeoutMs);
    if (!args.code) throw new Error("run_script requires args.code");
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      args: [args.code],
      func: (code) => {
        const evaluator = new Function(`"use strict"; return (${code});`);
        const output = evaluator();
        return { ok: true, output };
      }
    });
    return results?.[0]?.result || { ok: false, error: "Unknown script result" };
  }

  if (action === "browser_state") {
    const ready = await probeDocumentReady(tabId);
    const maxElements = Math.max(20, Math.min(400, Number(args.maxElements || 120)));
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      args: [maxElements],
      func: (maxCount) => {
        const buildSelector = (el) => {
          if (!el || !el.tagName) return "";
          if (el.id) return `#${el.id}`;
          const parts = [];
          let current = el;
          let depth = 0;
          while (current && current.tagName && depth < 4) {
            let part = current.tagName.toLowerCase();
            if (current.classList && current.classList.length) {
              part += `.${Array.from(current.classList).slice(0, 2).join(".")}`;
            }
            const parent = current.parentElement;
            if (parent) {
              const siblings = Array.from(parent.children).filter((n) => n.tagName === current.tagName);
              if (siblings.length > 1) {
                part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
              }
            }
            parts.unshift(part);
            current = current.parentElement;
            depth += 1;
          }
          return parts.join(" > ");
        };

        const candidates = Array.from(
          document.querySelectorAll(
            "a,button,input,textarea,select,[role='button'],[role='link'],[role='textbox'],[contenteditable='true'],[tabindex]"
          )
        )
          .filter((el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return (
              style &&
              style.display !== "none" &&
              style.visibility !== "hidden" &&
              rect.width > 0 &&
              rect.height > 0
            );
          })
          .slice(0, maxCount)
          .map((el, idx) => {
            const rect = el.getBoundingClientRect();
            return {
              index: idx,
              tag: (el.tagName || "").toLowerCase(),
              text: (el.innerText || el.textContent || "").trim().slice(0, 120),
              selector: buildSelector(el),
              placeholder: el.getAttribute("placeholder") || "",
              type: el.getAttribute("type") || "",
              role: el.getAttribute("role") || "",
              href: el.getAttribute("href") || "",
              x: Math.round(rect.x),
              y: Math.round(rect.y),
              width: Math.round(rect.width),
              height: Math.round(rect.height),
            };
          });

        return {
          ok: true,
          title: document.title || "",
          url: location.href,
          readyState: document.readyState,
          viewport: {
            width: window.innerWidth,
            height: window.innerHeight,
            scrollX: window.scrollX,
            scrollY: window.scrollY,
            pageHeight: document.documentElement?.scrollHeight || 0,
          },
          elements: candidates,
          bodyTextExcerpt: (document.body?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 4000),
        };
      },
    });
    return {
      ok: true,
      ready,
      state: results?.[0]?.result || { ok: false, error: "Unknown browser_state result" },
    };
  }

  if (action === "find_text") {
    await ensureTabInteractionReady(tabId, readyTimeoutMs);
    const keyword = String(args.text || args.keyword || "").trim();
    if (!keyword) throw new Error("find_text requires args.text");
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      args: [keyword],
      func: (kw) => {
        const normalized = kw.toLowerCase();
        const text = (document.body?.innerText || "").replace(/\s+/g, " ").trim();
        const idx = text.toLowerCase().indexOf(normalized);
        let snippet = "";
        if (idx >= 0) {
          const start = Math.max(0, idx - 80);
          const end = Math.min(text.length, idx + kw.length + 120);
          snippet = text.slice(start, end);
        }
        // window.find scrolls to one match and is faster for agent follow-up click.
        const found = window.find(kw, false, false, true, false, false, false);
        return { ok: true, found, snippet };
      },
    });
    return results?.[0]?.result || { ok: false, error: "Unknown find_text result" };
  }

  if (action === "scroll") {
    await ensureTabInteractionReady(tabId, readyTimeoutMs);
    const direction = String(args.direction || "down").toLowerCase();
    const pages = Math.max(0.25, Math.min(8, Number(args.pages || 1)));
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      args: [direction, pages],
      func: (dir, pageCount) => {
        const amount = Math.round(window.innerHeight * pageCount);
        const deltaY = dir === "up" ? -Math.abs(amount) : Math.abs(amount);
        window.scrollBy({ top: deltaY, left: 0, behavior: "smooth" });
        return {
          ok: true,
          direction: dir,
          deltaY,
          scrollY: window.scrollY,
          pageHeight: document.documentElement?.scrollHeight || 0,
        };
      },
    });
    return results?.[0]?.result || { ok: false, error: "Unknown scroll result" };
  }

  if (action === "send_keys") {
    await ensureTabInteractionReady(tabId, readyTimeoutMs);
    const keys = String(args.keys || "").trim();
    if (!keys) throw new Error("send_keys requires args.keys");
    const selector = String(args.selector || "");
    const textHint = String(args.text || args.textHint || "").trim();
    const domIndex = parseDomIndex(args);
    const submit = Boolean(args.submit);
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      args: [keys, selector, textHint, Number.isFinite(domIndex) ? domIndex : null, submit],
      func: (keysValue, selectorValue, textValue, domIndexValue, shouldSubmit) => {
        const isVisible = (el) => {
          if (!el) return false;
          const style = window.getComputedStyle(el);
          if (!style || style.display === "none" || style.visibility === "hidden") return false;
          const rect = el.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        };
        let target = null;
        if (typeof domIndexValue === "number" && domIndexValue >= 0) {
          const candidates = Array.from(document.querySelectorAll("input,textarea,[contenteditable='true']"))
            .filter(isVisible);
          target = candidates[domIndexValue] || null;
        }
        if (!target) target = selectorValue ? document.querySelector(selectorValue) : null;
        if (!target && textValue) {
          const normalized = textValue.toLowerCase();
          target = Array.from(document.querySelectorAll("input,textarea,[contenteditable='true']")).find((candidate) => {
            const bag = [
              candidate.getAttribute("placeholder") || "",
              candidate.getAttribute("name") || "",
              candidate.getAttribute("aria-label") || "",
              candidate.id || "",
              candidate.labels?.[0]?.innerText || "",
            ].join(" ").toLowerCase();
            return bag.includes(normalized);
          }) || null;
        }
        if (!target) target = document.activeElement || document.body;
        if (!target) return { ok: false, error: "No target element for send_keys" };
        if (typeof target.focus === "function") target.focus();

        const fire = (type, key) =>
          target.dispatchEvent(new KeyboardEvent(type, { key, bubbles: true, cancelable: true }));

        if (keysValue.toUpperCase() === "ENTER") {
          fire("keydown", "Enter");
          fire("keypress", "Enter");
          fire("keyup", "Enter");
          if (shouldSubmit) {
            const form = target.closest?.("form");
            if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
          }
          return { ok: true, mode: "enter" };
        }

        if ("value" in target) {
          target.value += keysValue;
          target.dispatchEvent(new Event("input", { bubbles: true }));
          target.dispatchEvent(new Event("change", { bubbles: true }));
        } else if (target.isContentEditable) {
          document.execCommand("insertText", false, keysValue);
        }
        return { ok: true, mode: "text", length: keysValue.length };
      },
    });
    return results?.[0]?.result || { ok: false, error: "Unknown send_keys result" };
  }

  if (action === "wait") {
    const seconds = Math.max(0.1, Math.min(30, Number(args.seconds || 1)));
    await sleep(Math.round(seconds * 1000));
    return { ok: true, waited_seconds: seconds };
  }

  if (action === "ping") {
    // 后端 /api/browser-extension/probe 主动探活用，必须立即返回
    return { ok: true, pong: true, ts: Date.now() };
  }

  if (action === "list_tabs") {
    const tabs = await listWindowTabs(activeTab?.windowId);
    return { ok: true, activeTabId: activeTab?.id || null, tabs };
  }

  if (action === "switch_tab") {
    if (!tabId) throw new Error("switch_tab requires args.tabId/tab_id/tabIdSuffix");
    await chrome.tabs.update(tabId, { active: true });
    const waitAfterSwitch = args.waitAfterSwitch !== false;
    let settle = null;
    if (waitAfterSwitch) {
      const timeoutMs = Math.max(
        1000,
        Math.min(
          120000,
          Math.round(Number(args.timeoutSeconds || args.timeout_seconds || 20) * 1000)
        )
      );
      settle = await waitForNavigationSettled(tabId, timeoutMs);
    }
    const tab = await chrome.tabs.get(tabId);
    return {
      ok: true,
      active_tab: {
        id: tab.id,
        title: tab.title || "",
        url: tab.url || "",
        windowId: tab.windowId,
      },
      settle,
    };
  }

  throw new Error(`Unsupported action: ${action}`);
}

async function pollAndHandleOneCommand({ pollTimeoutSec = 20 } = {}) {
  if (COMMAND_RUNTIME_STATE.polling) return { handled: false, reason: "already_polling" };
  COMMAND_RUNTIME_STATE.polling = true;
  const state = await detectBackend(false);
  if (!state.detected || !state.apiBase) {
    COMMAND_RUNTIME_STATE.polling = false;
    return { handled: false, reason: "no_backend" };
  }
  try {
    const safeTimeout = Math.max(1, Math.min(60, Number(pollTimeoutSec) || 20));
    const payload = await fetchJson(state.apiBase, `/api/browser-extension/commands/poll?timeout=${safeTimeout}`, { method: "GET" });
    const command = payload?.data?.command || null;
    if (!command) return { handled: false, reason: "no_command" };

    try {
      COMMAND_RUNTIME_STATE.executing = true;
      COMMAND_RUNTIME_STATE.currentCommandId = command.command_id || "";
      const result = await executeCommand(command);
      if (result && typeof result === "object" && result.ok === false) {
        throw new Error(result.error || `Action ${command.action} returned ok=false`);
      }
      await fetchJson(state.apiBase, `/api/browser-extension/commands/${command.command_id}/result`, {
        method: "POST",
        body: {
          success: true,
          result: {
            ...result,
            _meta: {
              command_id: command.command_id,
              action: command.action,
              executed_at: Date.now(),
            },
          }
        }
      });
    } catch (err) {
      await fetchJson(state.apiBase, `/api/browser-extension/commands/${command.command_id}/result`, {
        method: "POST",
        body: {
          success: false,
          error: err?.message || String(err)
        }
      });
    } finally {
      COMMAND_RUNTIME_STATE.executing = false;
      COMMAND_RUNTIME_STATE.currentCommandId = "";
      COMMAND_RUNTIME_STATE.lastCommandAt = Date.now();
    }
    return { handled: true };
  } catch (err) {
    return { handled: false, reason: "error" };
  } finally {
    COMMAND_RUNTIME_STATE.polling = false;
  }
}

// 在一个 alarm 周期内连续长轮询，最多持续 maxDurationMs（保持在 service worker 的 30s 存活窗口内）
async function pollLoopWithinAlarmCycle(maxDurationMs = 26000) {
  const startedAt = Date.now();
  let cycles = 0;
  while (Date.now() - startedAt < maxDurationMs) {
    cycles++;
    const remaining = Math.max(1, Math.floor((maxDurationMs - (Date.now() - startedAt)) / 1000));
    const pollSec = Math.min(20, remaining);
    if (pollSec <= 0) break;
    const res = await pollAndHandleOneCommand({ pollTimeoutSec: pollSec });
    // 处理完一条命令后立即继续抓下一条；否则就让长轮询自然超时返回
    if (!res.handled && res.reason === "no_backend") {
      await sleep(2000);
    }
    if (res.reason === "already_polling") break;
  }
}

async function tryInjectContentScript(tabId) {
  if (!tabId) return;
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content-script.js"],
    });
  } catch (_err) {
    // Ignore restricted pages (e.g. chrome://) and unsupported tabs.
  }
}

async function injectContentScriptToExistingTabs() {
  try {
    const tabs = await chrome.tabs.query({});
    for (const tab of tabs || []) {
      await tryInjectContentScript(tab.id);
    }
  } catch (_err) {
    // ignore
  }
}

// Chrome 120+ 支持 0.5 分钟（30s）。低版本 Chrome 会被向下取整到 1 分钟，仍可用
const HEARTBEAT_PERIOD_MIN = 0.5;

chrome.runtime.onInstalled.addListener(async () => {
  await detectBackend(true);
  await injectContentScriptToExistingTabs();
  chrome.alarms.create("sage-heartbeat", { periodInMinutes: HEARTBEAT_PERIOD_MIN });
  if (chrome.sidePanel?.setPanelBehavior) {
    await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  }
});

chrome.runtime.onStartup.addListener(async () => {
  await detectBackend(false);
  await injectContentScriptToExistingTabs();
  chrome.alarms.create("sage-heartbeat", { periodInMinutes: HEARTBEAT_PERIOD_MIN });
  if (chrome.sidePanel?.setPanelBehavior) {
    await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  }
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== "sage-heartbeat") return;
  await sendHeartbeat();
  // 长轮询一段时间，让后端入队的命令（含 ping 探活）能在 1-2 秒内被消费
  await pollLoopWithinAlarmCycle();
});

chrome.tabs.onActivated.addListener(async () => {
  await sendHeartbeat();
  await pollAndHandleOneCommand({ pollTimeoutSec: 5 });
});

chrome.tabs.onUpdated.addListener(async (_tabId, changeInfo) => {
  if (changeInfo.status === "complete") {
    await sleep(200);
    await tryInjectContentScript(_tabId);
    await sendHeartbeat();
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (message?.type === "detect-backend") {
      const state = await detectBackend(Boolean(message.force));
      sendResponse({ ok: true, state });
      return;
    }

    if (message?.type === "get-state") {
      sendResponse({ ok: true, state: await getState() });
      return;
    }

    if (message?.type === "set-custom-api-base") {
      await chrome.storage.local.set({ customApiBase: String(message.apiBase || "").trim() });
      const state = await detectBackend(true);
      sendResponse({ ok: true, state });
      return;
    }

    if (message?.type === "heartbeat-now") {
      const state = await sendHeartbeat();
      sendResponse({ ok: true, state });
      return;
    }

    if (message?.type === "open-side-panel") {
      let windowId = _sender?.tab?.windowId;
      if (!windowId) {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        windowId = tabs?.[0]?.windowId;
      }
      if (!windowId) {
        sendResponse({ ok: false, error: "No target window for side panel" });
        return;
      }
      await chrome.sidePanel.open({ windowId });
      const state = await sendHeartbeat();
      await pollLoopWithinAlarmCycle();
      sendResponse({ ok: true, state });
      return;
    }

    if (message?.type === "poll-command-now") {
      await pollLoopWithinAlarmCycle();
      sendResponse({ ok: true });
      return;
    }

    sendResponse({ ok: false, error: "Unknown message type" });
  })().catch((err) => {
    sendResponse({ ok: false, error: err?.message || String(err) });
  });
  return true;
});
