#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import random
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

try:
    import markdown as md_lib
except Exception:
    traceback.print_exc()
    md_lib = None


def slugify(text: str, used: dict[str, int]) -> str:
    base = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text.strip().lower())
    base = re.sub(r"-{2,}", "-", base).strip("-") or "section"
    count = used.get(base, 0)
    used[base] = count + 1
    return f"{base}-{count + 1}" if count else base


def extract_headings(text: str) -> list[dict]:
    headings = []
    used = {}
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            continue
        level = len(match.group(1))
        title = match.group(2).strip()
        heading_id = slugify(title, used)
        headings.append({"level": level, "title": title, "id": heading_id})
    return headings


def inline_format(text: str) -> str:
    codes = []

    def stash_code(match: re.Match) -> str:
        codes.append(html.escape(match.group(1), quote=False))
        return f"{{{{CODE{len(codes) - 1}}}}}"

    text = re.sub(r"`([^`]+)`", stash_code, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        text,
    )
    for idx, code in enumerate(codes):
        text = text.replace(f"{{{{CODE{idx}}}}}", f"<code>{code}</code>")
    return text


def parse_table(lines: list[str], start: int) -> tuple[str | None, int]:
    if start + 1 >= len(lines):
        return None, start
    header = lines[start].strip()
    separator = lines[start + 1].strip()
    if "|" not in header:
        return None, start
    if not re.match(r"^\s*\|?[\-\s:|]+\|?\s*$", separator):
        return None, start
    rows = []
    i = start + 2
    while i < len(lines):
        line = lines[i].strip()
        if not line or "|" not in line:
            break
        rows.append(line)
        i += 1
    header_cells = [c.strip() for c in header.strip("|").split("|")]
    body_rows = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
    thead = "".join(f"<th>{inline_format(c)}</th>" for c in header_cells)
    tbody = ""
    for row in body_rows:
        cols = "".join(f"<td>{inline_format(c)}</td>" for c in row)
        tbody += f"<tr>{cols}</tr>"
    table_html = f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>"
    return table_html, i - 1


def basic_markdown_to_html(text: str, headings: list[dict]) -> str:
    lines = text.splitlines()
    out = []
    i = 0
    in_code = False
    code_lang = ""
    buffer = []
    list_type = None
    list_items = []
    heading_iter = iter(headings)

    def flush_paragraph() -> None:
        nonlocal buffer
        if buffer:
            content = inline_format(" ".join(buffer).strip())
            out.append(f"<p>{content}</p>")
            buffer = []

    def flush_list() -> None:
        nonlocal list_items, list_type
        if list_items:
            tag = "ol" if list_type == "ol" else "ul"
            items_html = "".join(f"<li>{inline_format(item)}</li>" for item in list_items)
            out.append(f"<{tag}>{items_html}</{tag}>")
            list_items = []
            list_type = None

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            if in_code:
                code_html = html.escape("\n".join(buffer), quote=False)
                class_attr = f' class="language-{code_lang}"' if code_lang else ""
                out.append(f"<pre><code{class_attr}>{code_html}</code></pre>")
                buffer = []
                in_code = False
                code_lang = ""
            else:
                flush_paragraph()
                flush_list()
                in_code = True
                code_lang = line.strip()[3:].strip()
                buffer = []
            i += 1
            continue

        if in_code:
            buffer.append(line)
            i += 1
            continue

        table_html, end_idx = parse_table(lines, i)
        if table_html:
            flush_paragraph()
            flush_list()
            out.append(table_html)
            i = end_idx + 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            content = inline_format(heading.group(2).strip())
            heading_item = next(heading_iter, None)
            heading_id = heading_item["id"] if heading_item else None
            id_attr = f' id="{heading_id}"' if heading_id else ""
            out.append(f"<h{level}{id_attr}>{content}</h{level}>")
            i += 1
            continue

        if re.match(r"^\s*[-*_]{3,}\s*$", line):
            flush_paragraph()
            flush_list()
            out.append("<hr>")
            i += 1
            continue

        quote = re.match(r"^\s*>\s?(.*)$", line)
        if quote:
            flush_paragraph()
            flush_list()
            out.append(f"<blockquote>{inline_format(quote.group(1))}</blockquote>")
            i += 1
            continue

        ol = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if ol:
            flush_paragraph()
            if list_type and list_type != "ol":
                flush_list()
            list_type = "ol"
            list_items.append(ol.group(1))
            i += 1
            continue

        ul = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if ul:
            flush_paragraph()
            if list_type and list_type != "ul":
                flush_list()
            list_type = "ul"
            list_items.append(ul.group(1))
            i += 1
            continue

        if not line.strip():
            flush_paragraph()
            flush_list()
            i += 1
            continue

        buffer.append(line.strip())
        i += 1

    if in_code:
        code_html = html.escape("\n".join(buffer), quote=False)
        class_attr = f' class="language-{code_lang}"' if code_lang else ""
        out.append(f"<pre><code{class_attr}>{code_html}</code></pre>")
        buffer = []

    flush_paragraph()
    flush_list()
    return "\n".join(out)


def apply_heading_ids(html_text: str, headings: list[dict]) -> str:
    iterator = iter(headings)

    def repl(match: re.Match) -> str:
        heading_item = next(iterator, None)
        if not heading_item:
            return match.group(0)
        level = match.group(1)
        return f'<h{level} id="{heading_item["id"]}">{match.group(2)}</h{level}>'

    return re.sub(r"<h([1-6])>(.*?)</h\1>", repl, html_text, flags=re.DOTALL)


def render_markdown(text: str, headings: list[dict]) -> str:
    if md_lib:
        try:
            html_text = md_lib.markdown(text, extensions=["fenced_code", "tables"])
            return apply_heading_ids(html_text, headings)
        except Exception:
            traceback.print_exc()
            pass
    return basic_markdown_to_html(text, headings)


def build_toc(headings: list[dict]) -> str:
    items = []
    for heading in headings:
        if heading["level"] < 2 or heading["level"] > 3:
            continue
        level_class = f"level-{heading['level']}"
        items.append(
            f'<li class="{level_class}"><a href="#{heading["id"]}">{html.escape(heading["title"])}</a></li>'
        )
    if not items:
        return ""
    return f'<ul class="toc-list">{"".join(items)}</ul>'


def wrap_sections(body: str) -> str:
    body = re.sub(r"<h1[^>]*>.*?</h1>", "", body, count=1, flags=re.DOTALL)
    parts = re.split(r"(<h2[^>]*>.*?</h2>)", body, flags=re.DOTALL)
    if len(parts) <= 1:
        return body
    intro = parts[0].strip()
    blocks = []
    if intro:
        blocks.append(f'<section class="content-card">{intro}</section>')
    for i in range(1, len(parts), 2):
        h2 = parts[i]
        content = parts[i + 1] if i + 1 < len(parts) else ""
        blocks.append(f'<section class="content-card">{h2}{content}</section>')
    return "".join(blocks)


def wrap_html(body: str, title: str, toc_html: str, footer_time: str, cover_style: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f2f4f7;
      --card: #ffffff;
      --text: #0f172a;
      --muted: #6b7280;
      --accent: #2563eb;
      --border: #e5e7eb;
      --code-bg: #0f172a;
      --code-text: #e5e7eb;
      --sidebar-bg: #ffffff;
      --sidebar-text: #6b7280;
      --sidebar-border: #e5e7eb;
      --sidebar-muted: #9ca3af;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.75;
    }}
    .page {{
      max-width: 1200px;
      margin: 32px auto 48px;
      padding: 0 24px;
    }}
    .layout {{
      display: flex;
      gap: 24px;
      align-items: flex-start;
    }}
    .sidebar {{
      width: 260px;
      background: var(--sidebar-bg);
      color: var(--sidebar-text);
      border-radius: 16px;
      padding: 20px 16px;
      position: sticky;
      top: 24px;
      max-height: calc(100vh - 48px);
      overflow-y: auto;
      transition: width 0.2s ease, padding 0.2s ease;
      border: 1px solid var(--sidebar-border);
      box-shadow: 0 6px 16px rgba(15, 23, 42, 0.06);
    }}
    .sidebar.collapsed {{
      width: 56px;
      padding: 16px 10px;
      overflow: hidden;
    }}
    .toc-title {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--sidebar-muted);
      margin-bottom: 12px;
    }}
    .toc-toggle {{
      background: #ffffff;
      border: 1px solid transparent;
      color: #9ca3af;
      padding: 2px 4px;
      border-radius: 8px;
      cursor: pointer;
      font-size: 12px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .toc-toggle:hover {{
      background: #f9fafb;
      border-color: var(--sidebar-border);
      color: #6b7280;
    }}
    .toc-toggle svg {{
      width: 16px;
      height: 16px;
      stroke: currentColor;
    }}
    .sidebar.collapsed .toc-title span {{
      display: none;
    }}
    .sidebar.collapsed .toc-toggle {{
      margin: 0 auto;
    }}
    .sidebar.collapsed .toc-list {{
      display: none;
    }}
    .toc-list {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}
    .toc-list li {{
      margin: 8px 0;
      font-size: 14px;
    }}
    .toc-list li.level-3 {{
      margin-left: 12px;
      font-size: 13px;
      color: #9ca3af;
    }}
    .toc-list a {{
      color: inherit;
      text-decoration: none;
    }}
    .toc-list a:hover {{
      text-decoration: underline;
    }}
    .content {{
      flex: 1;
      min-width: 0;
    }}
    .cover-row {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 20px;
    }}
    .cover {{
      border-radius: 18px;
      padding: 44px 46px;
      color: #f8fafc;
      box-shadow: 0 16px 40px rgba(15, 23, 42, 0.2);
      flex: 1;
      min-height: 150px;
    }}
    .cover-title {{
      font-size: 34px;
      margin: 0 0 8px 0;
    }}
    .cover-action {{
      width: 32px;
      height: 32px;
      border-radius: 10px;
      border: 1px solid #e5e7eb;
      background: #ffffff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      flex-shrink: 0;
      box-shadow: 0 6px 16px rgba(15, 23, 42, 0.08);
    }}
    .cover-action svg {{
      width: 16px;
      height: 16px;
      stroke: #64748b;
    }}
    .content-body {{
      background: var(--card);
      border-radius: 18px;
      padding: 28px 30px 40px;
      box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
    }}
    .content-card {{
      background: #f8fafc;
      border-radius: 14px;
      padding: 20px 22px;
      margin-bottom: 16px;
      border: 1px solid #eef2f7;
    }}
    h1, h2, h3, h4, h5, h6 {{
      margin: 1.2em 0 0.6em;
      line-height: 1.35;
    }}
    h1 {{ font-size: 30px; }}
    h2 {{ font-size: 24px; }}
    h3 {{ font-size: 20px; }}
    h4 {{ font-size: 18px; }}
    h5 {{ font-size: 16px; }}
    h6 {{ font-size: 14px; color: var(--muted); }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    hr {{
      border: none;
      border-top: 1px solid var(--border);
      margin: 24px 0;
    }}
    blockquote {{
      border-left: 4px solid var(--accent);
      margin: 16px 0;
      padding: 8px 16px;
      color: var(--muted);
      background: #f9fafb;
      border-radius: 8px;
    }}
    code {{
      background: #f3f4f6;
      padding: 2px 6px;
      border-radius: 6px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 0.9em;
    }}
    pre {{
      background: var(--code-bg);
      color: var(--code-text);
      padding: 16px;
      border-radius: 12px;
      overflow-x: auto;
    }}
    pre code {{
      background: transparent;
      color: inherit;
      padding: 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0;
      font-size: 14px;
    }}
    th, td {{
      border: 1px solid var(--border);
      padding: 10px 12px;
      text-align: left;
    }}
    th {{
      background: #f3f4f6;
      color: #111827;
    }}
    ul, ol {{
      padding-left: 24px;
      margin: 12px 0;
    }}
    .footer-time {{
      margin-top: 18px;
      font-size: 12px;
      color: var(--muted);
      text-align: center;
    }}
    .sidebar-toggle-fixed {{
      display: none;
    }}
    @media (max-width: 1024px) {{
      .layout {{
        flex-direction: column;
      }}
      .sidebar {{
        width: 100%;
        position: static;
        max-height: none;
      }}
      .sidebar.collapsed {{
        transform: none;
        opacity: 1;
        pointer-events: auto;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="layout">
      <aside class="sidebar" id="sidebar">
        <div class="toc-title">
          <span>目录</span>
          <button class="toc-toggle" id="tocToggle" type="button" aria-label="切换目录">
            <svg viewBox="0 0 24 24" fill="none" stroke-width="1.8">
              <path d="M7 6h10M7 12h10M7 18h10" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
        </div>
        {toc_html}
      </aside>
      <main class="content">
        <div class="cover-row">
          <div class="cover" style="{cover_style}">
            <h1 class="cover-title">{html.escape(title)}</h1>
          </div>
        </div>
        <div class="content-body">
          {body}
        </div>
      </main>
    </div>
    <div class="footer-time">{footer_time}</div>
  </div>
  <script>
    const sidebar = document.getElementById("sidebar");
    const tocToggle = document.getElementById("tocToggle");
    const toggleSidebar = () => {{
      const collapsed = sidebar.classList.toggle("collapsed");
      if (tocToggle) {{
        tocToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      }}
    }};
    if (sidebar && tocToggle) {{
      tocToggle.addEventListener("click", toggleSidebar);
    }}
  </script>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Markdown to a polished HTML report")
    parser.add_argument("input", help="Markdown input file")
    parser.add_argument("--out", default=None, help="Output HTML file")
    parser.add_argument("--title", default=None, help="HTML title")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"错误: 找不到输入文件 {input_path}", file=sys.stderr)
        sys.exit(1)

    text = input_path.read_text(encoding="utf-8")
    headings = extract_headings(text)
    title = args.title or (headings[0]["title"] if headings else "报告")
    body = render_markdown(text, headings)
    body = wrap_sections(body)
    toc_html = build_toc(headings)
    footer_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    gradient_choices = [
        ("#0f172a", "#1d4ed8"),
        ("#111827", "#2563eb"),
        ("#1f2937", "#0ea5e9"),
        ("#0b1220", "#1e3a8a"),
        ("#0f172a", "#14b8a6"),
        ("#111827", "#9333ea"),
        ("#0f172a", "#3b82f6"),
        ("#111827", "#0ea5e9"),
    ]
    start, end = random.choice(gradient_choices)
    cover_style = f"background: linear-gradient(135deg, {start}, {end});"
    html_text = wrap_html(body, title, toc_html, footer_time, cover_style)

    out_path = Path(args.out).expanduser().resolve() if args.out else input_path.with_suffix(".html")
    out_path.write_text(html_text, encoding="utf-8")
    print(f"✓ HTML已生成: {out_path}")


if __name__ == "__main__":
    main()
