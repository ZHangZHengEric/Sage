(function () {
  const INIT_FLAG = "__sage_browser_content_script_initialized__";
  const FAB_ID = "sage-browser-floating-entry";
  const POS_KEY = "sage_fab_position_v1";

  if (globalThis[INIT_FLAG]) {
    return;
  }
  globalThis[INIT_FLAG] = true;

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function loadPosition() {
    try {
      const raw = localStorage.getItem(POS_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (typeof parsed?.x !== "number" || typeof parsed?.y !== "number") return null;
      return parsed;
    } catch (_err) {
      return null;
    }
  }

  function savePosition(x, y) {
    try {
      localStorage.setItem(POS_KEY, JSON.stringify({ x, y }));
    } catch (_err) {
      // ignore storage errors
    }
  }

  function createFab() {
    const button = document.createElement("button");
    button.id = FAB_ID;
    button.type = "button";
    button.title = "打开 Sage 侧边栏";
    button.setAttribute("aria-label", "打开 Sage 侧边栏");

    Object.assign(button.style, {
      position: "fixed",
      right: "10px",
      top: "45%",
      width: "30px",
      height: "30px",
      borderRadius: "8px",
      border: "0",
      background: "transparent",
      boxShadow: "none",
      backdropFilter: "none",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      zIndex: "2147483647",
      cursor: "pointer",
      padding: "0",
      userSelect: "none",
      WebkitUserSelect: "none"
    });

    const img = document.createElement("img");
    img.src = chrome.runtime.getURL("sage_logo.png");
    img.alt = "Sage";
    Object.assign(img.style, {
      width: "100%",
      height: "100%",
      borderRadius: "8px",
      pointerEvents: "none"
    });
    button.appendChild(img);

    const saved = loadPosition();
    if (saved) {
      button.style.left = `${saved.x}px`;
      button.style.top = `${saved.y}px`;
      button.style.right = "auto";
    }

    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let originLeft = 0;
    let originTop = 0;

    const pointerMove = (event) => {
      const dx = event.clientX - startX;
      const dy = event.clientY - startY;
      if (!isDragging && Math.hypot(dx, dy) > 4) {
        isDragging = true;
        button.style.cursor = "grabbing";
      }
      if (!isDragging) return;

      const nextLeft = clamp(originLeft + dx, 6, window.innerWidth - button.offsetWidth - 6);
      const nextTop = clamp(originTop + dy, 6, window.innerHeight - button.offsetHeight - 6);
      button.style.left = `${nextLeft}px`;
      button.style.top = `${nextTop}px`;
      button.style.right = "auto";
    };

    const pointerUp = async () => {
      window.removeEventListener("pointermove", pointerMove, true);
      window.removeEventListener("pointerup", pointerUp, true);
      button.style.cursor = "pointer";

      if (isDragging) {
        const left = button.offsetLeft;
        const top = button.offsetTop;
        const edgePadding = 6;
        const leftDistance = left;
        const rightDistance = window.innerWidth - (left + button.offsetWidth);
        const snappedLeft = leftDistance <= rightDistance
          ? edgePadding
          : window.innerWidth - button.offsetWidth - edgePadding;
        button.style.transition = "left 120ms ease";
        button.style.left = `${snappedLeft}px`;
        button.style.right = "auto";
        setTimeout(() => {
          button.style.transition = "";
        }, 140);
        savePosition(snappedLeft, top);
        return;
      }
      try {
        await chrome.runtime.sendMessage({ type: "open-side-panel" });
      } catch (_err) {
        // ignore
      }
    };

    button.addEventListener("pointerdown", (event) => {
      startX = event.clientX;
      startY = event.clientY;
      originLeft = button.offsetLeft;
      originTop = button.offsetTop;
      isDragging = false;
      window.addEventListener("pointermove", pointerMove, true);
      window.addEventListener("pointerup", pointerUp, true);
      event.preventDefault();
    });

    return button;
  }

  function mountFab() {
    if (window.top !== window) return;
    if (!document.body) return;
    const existing = document.getElementById(FAB_ID);
    if (existing) {
      existing.remove();
    }
    const fab = createFab();
    document.body.appendChild(fab);
  }

  mountFab();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountFab, { once: true });
  }

  chrome.runtime.sendMessage({ type: "heartbeat-now" }).catch(() => {});
})();
