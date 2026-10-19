import { Marked, Renderer } from 'marked'
const escape = value => String(value || '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]))
function safeHref(value, image = false) {
  try { return (image ? ['http:', 'https:'] : ['http:', 'https:', 'mailto:']).includes(new URL(value, 'https://sage.local').protocol) }
  catch { return false }
}
const markdown = new Marked({ breaks: true, gfm: true, renderer: {
  // Model text is untrusted content. Render Markdown, never model-supplied HTML.
  html: ({ text }) => escape(text),
  link({ href, title, tokens }) {
    const text = this.parser.parseInline(tokens)
    return safeHref(href) ? `<a href="${escape(href)}"${title ? ` title="${escape(title)}"` : ''} target="_blank" rel="noopener noreferrer">${text}</a>` : text
  },
  image({ href, title, text }) {
    return safeHref(href, true) ? `<img src="${escape(href)}" alt="${escape(text)}"${title ? ` title="${escape(title)}"` : ''} loading="lazy">` : escape(text)
  },
  code({ text, lang }) {
    return `<div class="message-code"><header><span>${escape(lang?.split(/\s+/)[0] || '代码')}</span><button type="button" data-copy-code>复制代码</button></header><pre><code>${escape(text)}</code></pre></div>`
  },
  table(token) { return `<div class="message-table">${Renderer.prototype.table.call(this, token)}</div>` },
} })
export function renderMessageMarkdown(text) { return markdown.parse(text || '', { async: false }) }
