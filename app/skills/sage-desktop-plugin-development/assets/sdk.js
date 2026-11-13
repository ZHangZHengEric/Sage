(() => {
  const token = document.currentScript.dataset.token;
  const pending = new Map();
  let sequence = 0;
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = String(++sequence);
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error('Sage Desktop did not respond'));
    }, 120000);
    pending.set(id, {resolve, reject, timer});
    window.SagePluginBridge.postMessage(JSON.stringify({version: 1, token, id, method, params}));
  });
  window.__sagePluginReceive = message => {
    if (message.event) {
      if (message.event === 'environment') {
        const {theme, locale, colors} = message.value;
        document.documentElement.dataset.theme = theme;
        document.documentElement.lang = locale;
        for (const [key, value] of Object.entries(colors)) {
          document.documentElement.style.setProperty(`--sage-${key}`, value);
        }
      }
      window.dispatchEvent(new CustomEvent(`sage:${message.event}`, {detail: message.value}));
      return;
    }
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    clearTimeout(request.timer);
    if (message.ok) request.resolve(message.value);
    else request.reject(new Error(message.error));
  };
  window.sageDesktop = Object.freeze({call, ready: call('ready')});
  window.sageDesktop.ready.then(value => {
    window.__sagePluginReceive({event: 'environment', value});
  }).catch(() => {});
  window.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !event.defaultPrevented && !event.isComposing) {
      call('collapse').catch(() => {});
    }
  });
})();
