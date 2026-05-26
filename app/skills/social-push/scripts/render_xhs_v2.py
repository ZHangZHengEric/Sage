#!/usr/bin/env python3
"""
小红书卡片渲染脚本 V2 - 智能分页版
将 Markdown 文件渲染为小红书风格的图片卡片

新特性：
1. 智能分页：自动检测内容高度，超出时自动拆分到多张卡片
2. 多种样式：支持多种预设样式主题
3. 字数预估：基于字数预分配内容，减少渲染次数

使用方法:
    python render_xhs_v2.py <markdown_file> [options]

依赖安装:
    pip install markdown pyyaml playwright
    playwright install chromium
"""

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from typing import List

try:
    import markdown
    import yaml
    from playwright.async_api import async_playwright, Page  # pyright: ignore[reportMissingImports]
except ImportError as e:
    print(f"缺少依赖: {e}")
    print(
        "请运行: pip install markdown pyyaml playwright && playwright install chromium"
    )
    sys.exit(1)


# 获取脚本所在目录
SCRIPT_DIR = Path(__file__).parent.parent
ASSETS_DIR = SCRIPT_DIR / "assets"

# 卡片尺寸配置 (3:4 比例)
CARD_WIDTH = 1080
CARD_HEIGHT = 1440

# 内容区域安全高度（考虑 padding 和 margin）
# card-inner padding: 60px * 2 = 120px
# card-container padding: 50px * 2 = 100px
# 页码区域: ~80px
# 安全边距: ~40px
SAFE_HEIGHT = CARD_HEIGHT - 120 - 100 - 80 - 40  # ~1100px

# 样式配置
STYLES = {
    "purple": {
        "name": "紫韵",
        "cover_bg": "linear-gradient(180deg, #3450E4 0%, #D266DA 100%)",
        "card_bg": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
        "accent_color": "#6366f1",
    },
    "xiaohongshu": {
        "name": "小红书红",
        "cover_bg": "linear-gradient(180deg, #FF2442 0%, #FF6B81 100%)",
        "card_bg": "linear-gradient(135deg, #FF2442 0%, #FF6B81 100%)",
        "accent_color": "#FF2442",
    },
    "mint": {
        "name": "清新薄荷",
        "cover_bg": "linear-gradient(180deg, #43e97b 0%, #38f9d7 100%)",
        "card_bg": "linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)",
        "accent_color": "#43e97b",
    },
    "sunset": {
        "name": "日落橙",
        "cover_bg": "linear-gradient(180deg, #fa709a 0%, #fee140 100%)",
        "card_bg": "linear-gradient(135deg, #fa709a 0%, #fee140 100%)",
        "accent_color": "#fa709a",
    },
    "ocean": {
        "name": "深海蓝",
        "cover_bg": "linear-gradient(180deg, #4facfe 0%, #00f2fe 100%)",
        "card_bg": "linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)",
        "accent_color": "#4facfe",
    },
    "elegant": {
        "name": "优雅白",
        "cover_bg": "linear-gradient(180deg, #f5f5f5 0%, #e0e0e0 100%)",
        "card_bg": "linear-gradient(135deg, #f5f5f5 0%, #e8e8e8 100%)",
        "accent_color": "#333333",
        "text_light": "#555555",
    },
    "dark": {
        "name": "暗黑模式",
        "cover_bg": "linear-gradient(180deg, #1a1a2e 0%, #16213e 100%)",
        "card_bg": "linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)",
        "accent_color": "#e94560",
    },
}


def parse_markdown_file(file_path: str) -> dict:
    """解析 Markdown 文件，提取 YAML 头部和正文内容"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 解析 YAML 头部
    yaml_pattern = r"^---\s*\n(.*?)\n---\s*\n"
    yaml_match = re.match(yaml_pattern, content, re.DOTALL)

    metadata = {}
    body = content

    if yaml_match:
        try:
            metadata = yaml.safe_load(yaml_match.group(1)) or {}
        except yaml.YAMLError:
            metadata = {}
        body = content[yaml_match.end() :]

    return {"metadata": metadata, "body": body.strip()}


def split_content_by_separator(body: str) -> list:
    """按照 --- 分隔符拆分正文为多张卡片内容"""
    parts = re.split(r"\n---+\n", body)
    return [part.strip() for part in parts if part.strip()]


def estimate_content_height(content: str) -> int:
    """预估内容高度（基于字数和元素类型）"""
    lines = content.split("\n")
    total_height = 0

    for line in lines:
        line = line.strip()
        if not line:
            total_height += 20  # 空行
            continue

        # 标题
        if line.startswith("# "):
            total_height += 130  # h1: font-size 72 + margin
        elif line.startswith("## "):
            total_height += 110  # h2
        elif line.startswith("### "):
            total_height += 90  # h3
        # 代码块
        elif line.startswith("```"):
            total_height += 80  # 代码块起始/结束
        # 列表
        elif line.startswith(("- ", "* ", "+ ")):
            total_height += 85  # li: line-height ~1.6, font-size 42
        # 引用
        elif line.startswith(">"):
            total_height += 100  # blockquote padding
        # 图片
        elif line.startswith("!["):
            total_height += 300  # 图片高度估计
        # 普通段落
        else:
            # 估算字数
            char_count = len(line)
            # 一行约25-30个中文字，行高1.7，字体42px
            lines_needed = max(1, char_count / 28)
            total_height += int(lines_needed * 42 * 1.7) + 35  # + margin-bottom

    return total_height


def smart_split_content(content: str, max_height: int = SAFE_HEIGHT) -> List[str]:
    """
    智能拆分内容到多张卡片
    基于预估高度进行拆分，尽量保持段落完整
    """
    # 首先尝试识别内容块（以标题或空行分隔）
    blocks = []
    current_block = []

    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # 新标题开始新块（除非是第一个）
        if line.strip().startswith("#") and current_block:
            blocks.append("\n".join(current_block))
            current_block = [line]
        # 分隔线
        elif line.strip() == "---":
            if current_block:
                blocks.append("\n".join(current_block))
                current_block = []
        else:
            current_block.append(line)

        i += 1

    if current_block:
        blocks.append("\n".join(current_block))

    # 如果没有明显的块边界，按段落拆分
    if len(blocks) <= 1:
        blocks = [b for b in content.split("\n\n") if b.strip()]

    # 合并块到卡片，确保每张卡片高度不超过限制
    cards = []
    current_card = []
    current_height = 0

    for block in blocks:
        block_height = estimate_content_height(block)

        # 如果单个块就超过限制，需要进一步拆分
        if block_height > max_height:
            # 如果当前卡片有内容，先保存
            if current_card:
                cards.append("\n\n".join(current_card))
                current_card = []
                current_height = 0

            # 将大块按行拆分
            lines = block.split("\n")
            sub_block = []
            sub_height = 0

            for line in lines:
                line_height = estimate_content_height(line)

                if sub_height + line_height > max_height and sub_block:
                    cards.append("\n".join(sub_block))
                    sub_block = [line]
                    sub_height = line_height
                else:
                    sub_block.append(line)
                    sub_height += line_height

            if sub_block:
                cards.append("\n".join(sub_block))

        # 如果当前卡片加上这个块会超，先保存当前卡片
        elif current_height + block_height > max_height and current_card:
            cards.append("\n\n".join(current_card))
            current_card = [block]
            current_height = block_height

        # 否则加入当前卡片
        else:
            current_card.append(block)
            current_height += block_height

    # 保存最后一个卡片
    if current_card:
        cards.append("\n\n".join(current_card))

    return cards if cards else [content]


def convert_markdown_to_html(md_content: str, style: dict = None) -> str:  # pyright: ignore[reportArgumentType]
    """将 Markdown 转换为 HTML"""
    style = style or STYLES["purple"]

    # 处理 tags（以 # 开头的标签）
    tags_pattern = r"((?:#[\w\u4e00-\u9fa5]+\s*)+)$"
    tags_match = re.search(tags_pattern, md_content, re.MULTILINE)
    tags_html = ""

    if tags_match:
        tags_str = tags_match.group(1)
        md_content = md_content[: tags_match.start()].strip()
        tags = re.findall(r"#([\w\u4e00-\u9fa5]+)", tags_str)
        if tags:
            accent = style.get("accent_color", "#6366f1")
            tags_html = '<div class="tags-container">'
            for tag in tags:
                tags_html += (
                    f'<span class="tag" style="background: {accent};">#{tag}</span>'
                )
            tags_html += "</div>"

    # 转换 Markdown 为 HTML
    html = markdown.markdown(
        md_content, extensions=["extra", "codehilite", "tables", "nl2br"]
    )

    return html + tags_html


def generate_cover_html(metadata: dict, style_key: str = "purple") -> str:
    """生成封面 HTML"""
    style = STYLES.get(style_key, STYLES["purple"])

    emoji = metadata.get("emoji", "📝")
    title = metadata.get("title", "标题")
    subtitle = metadata.get("subtitle", "")

    # 动态调整标题字体大小
    title_len = len(title)
    if title_len <= 6:
        title_size = 150  # 极大 (width * 0.14)
    elif title_len <= 10:
        title_size = 130  # 大 (width * 0.12)
    elif title_len <= 18:
        title_size = 100  # 中 (width * 0.09)
    elif title_len <= 30:
        title_size = 80  # 小 (width * 0.07)
    else:
        title_size = 60  # 极小 (width * 0.055)

    # 暗黑模式特殊处理
    is_dark = style_key == "dark"
    text_color = "#ffffff" if is_dark else "#000000"
    title_gradient = (
        "linear-gradient(180deg, #ffffff 0%, #cccccc 100%)"
        if is_dark
        else "linear-gradient(180deg, #2E67B1 0%, #4C4C4C 100%)"
    )
    inner_bg = "#1a1a2e" if is_dark else "#F3F3F3"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=1080, height=1440">
    <title>小红书封面</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700;900&display=swap');
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Noto Sans SC', 'Source Han Sans CN', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            width: 1080px; height: 1440px; overflow: hidden;
        }}
        .cover-container {{
            width: 1080px; height: 1440px;
            background: {style["cover_bg"]};
            position: relative; overflow: hidden;
        }}
        .cover-inner {{
            position: absolute; width: 950px; height: 1310px;
            left: 65px; top: 65px;
            background: {inner_bg};
            border-radius: 25px;
            display: flex; flex-direction: column;
            padding: 80px 85px;
        }}
        .cover-emoji {{ font-size: 180px; line-height: 1.2; margin-bottom: 50px; }}
        .cover-title {{
            font-weight: 900; font-size: {title_size}px; line-height: 1.4;
            background: {title_gradient};
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            flex: 1;
            display: flex; align-items: flex-start;
            word-break: normal;
            overflow-wrap: break-word;
        }}
        .cover-subtitle {{
            font-weight: 350; font-size: 72px; line-height: 1.4;
            color: {text_color};
            margin-top: auto;
        }}
    </style>
</head>
<body>
    <div class="cover-container">
        <div class="cover-inner">
            <div class="cover-emoji">{emoji}</div>
            <div class="cover-title">{title}</div>
            <div class="cover-subtitle">{subtitle}</div>
        </div>
    </div>
</body>
</html>"""


def generate_card_html(
    content: str, page_number: int = 1, total_pages: int = 1, style_key: str = "purple"
) -> str:
    """生成正文卡片 HTML"""
    style = STYLES.get(style_key, STYLES["purple"])
    html_content = convert_markdown_to_html(content, style)
    page_text = f"{page_number}/{total_pages}" if total_pages > 1 else ""

    # 暗黑模式特殊处理
    is_dark = style_key == "dark"
    card_bg = "rgba(30, 30, 46, 0.95)" if is_dark else "rgba(255, 255, 255, 0.95)"
    text_color = "#e0e0e0" if is_dark else "#475569"
    heading_color = "#ffffff" if is_dark else "#1e293b"
    h2_color = "#e0e0e0" if is_dark else "#334155"
    h3_color = "#c0c0c0" if is_dark else "#475569"
    pre_bg = "#0f0f23" if is_dark else "#1e293b"
    blockquote_bg = "#252540" if is_dark else "#f1f5f9"
    blockquote_border = style["accent_color"]
    blockquote_color = "#a0a0a0" if is_dark else "#64748b"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=1080">
    <title>小红书卡片</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700;900&display=swap');
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Noto Sans SC', 'Source Han Sans CN', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            width: 1080px; min-height: 1440px; overflow: hidden; background: transparent;
        }}
        .card-container {{
            width: 1080px; min-height: 1440px;
            background: {style["card_bg"]};
            position: relative; padding: 50px; overflow: hidden;
        }}
        .card-inner {{
            background: {card_bg};
            border-radius: 20px;
            padding: 60px;
            min-height: calc(1440px - 100px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(10px);
        }}
        .card-content {{
            color: {text_color};
            font-size: 42px;
            line-height: 1.7;
        }}
        .card-content h1 {{
            font-size: 72px; font-weight: 700; color: {heading_color};
            margin-bottom: 40px; line-height: 1.3;
        }}
        .card-content h2 {{
            font-size: 56px; font-weight: 600; color: {h2_color};
            margin: 50px 0 25px 0; line-height: 1.4;
        }}
        .card-content h3 {{
            font-size: 48px; font-weight: 600; color: {h3_color};
            margin: 40px 0 20px 0;
        }}
        .card-content p {{ margin-bottom: 35px; }}
        .card-content strong {{ font-weight: 700; color: {heading_color}; }}
        .card-content em {{ font-style: italic; color: {style["accent_color"]}; }}
        .card-content a {{
            color: {style["accent_color"]}; text-decoration: none;
            border-bottom: 2px solid {style["accent_color"]};
        }}
        .card-content ul, .card-content ol {{
            margin: 30px 0; padding-left: 60px;
        }}
        .card-content li {{ margin-bottom: 20px; line-height: 1.6; }}
        .card-content blockquote {{
            border-left: 8px solid {blockquote_border};
            padding-left: 40px;
            background: {blockquote_bg};
            padding-top: 25px; padding-bottom: 25px; padding-right: 30px;
            margin: 35px 0;
            color: {blockquote_color};
            font-style: italic;
            border-radius: 0 12px 12px 0;
        }}
        .card-content blockquote p {{ margin: 0; }}
        .card-content code {{
            background: {"#252540" if is_dark else "#f1f5f9"};
            padding: 6px 16px; border-radius: 8px;
            font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
            font-size: 38px;
            color: {style["accent_color"]};
        }}
        .card-content pre {{
            background: {pre_bg};
            color: {"#e0e0e0" if is_dark else "#e2e8f0"};
            padding: 40px; border-radius: 16px;
            margin: 35px 0;
            overflow-x: visible;
            overflow-wrap: break-word;
            word-wrap: break-word;
            word-break: normal;
            overflow-wrap: break-word;
            white-space: pre-wrap;
            font-size: 36px; line-height: 1.5;
        }}
        .card-content pre code {{
            background: transparent; color: inherit; padding: 0; font-size: inherit;
        }}
        .card-content img {{
            max-width: 100%; height: auto; border-radius: 16px;
            margin: 35px auto; display: block;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
        }}
        .card-content hr {{
            border: none; height: 2px;
            background: {"#333355" if is_dark else "#e2e8f0"};
            margin: 50px 0;
        }}
        .tags-container {{
            margin-top: 50px; padding-top: 30px;
            border-top: 2px solid {"#333355" if is_dark else "#e2e8f0"};
        }}
        .tag {{
            display: inline-block;
            background: {style["accent_color"]};
            color: white;
            padding: 12px 28px; border-radius: 30px;
            font-size: 34px;
            margin: 10px 15px 10px 0;
            font-weight: 500;
        }}
        .page-number {{
            position: absolute;
            bottom: 80px; right: 80px;
            font-size: 36px;
            color: rgba(255, 255, 255, 0.8);
            font-weight: 500;
        }}
    </style>
</head>
<body>
    <div class="card-container">
        <div class="card-inner">
            <div class="card-content">
                {html_content}
            </div>
        </div>
        <div class="page-number">{page_text}</div>
    </div>
</body>
</html>"""


async def measure_content_height(page: Page, html_content: str) -> int:
    """使用 Playwright 测量实际内容高度"""
    await page.set_content(html_content, wait_until="networkidle")
    await page.wait_for_timeout(300)  # 等待字体渲染

    height = await page.evaluate("""() => {
        const inner = document.querySelector('.card-inner');
        if (inner) {
            return inner.scrollHeight;
        }
        const container = document.querySelector('.card-container');
        return container ? container.scrollHeight : document.body.scrollHeight;
    }""")

    return height


async def render_html_to_image(
    html_content: str,
    output_path: str,
    width: int = CARD_WIDTH,
    height: int = CARD_HEIGHT,
):
    """使用 Playwright 将 HTML 渲染为图片"""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": width, "height": height})

        try:
            await page.set_content(html_content, wait_until="networkidle")
            await page.wait_for_timeout(300)

            # 截图固定尺寸
            await page.screenshot(
                path=output_path,
                clip={"x": 0, "y": 0, "width": width, "height": height},
                type="png",
            )

            print(f"  ✅ 已生成: {output_path}")

        finally:
            await browser.close()


async def process_and_render_cards(
    card_contents: List[str], output_dir: str, style_key: str
) -> List[str]:
    """
    处理卡片内容，检测高度并自动分页，然后渲染
    返回最终生成的所有卡片文件路径
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport={"width": CARD_WIDTH, "height": CARD_HEIGHT}
        )

        all_cards = []

        try:
            for content in card_contents:
                # 预估内容高度
                estimated_height = estimate_content_height(content)

                # 如果预估高度超过安全高度，尝试拆分
                if estimated_height > SAFE_HEIGHT:
                    split_contents = smart_split_content(content, SAFE_HEIGHT)
                else:
                    split_contents = [content]

                # 验证每个拆分后的内容
                for split_content in split_contents:
                    # 生成临时 HTML 测量
                    temp_html = generate_card_html(split_content, 1, 1, style_key)
                    actual_height = await measure_content_height(page, temp_html)

                    # 如果仍然超出，进一步按行拆分
                    if actual_height > CARD_HEIGHT - 100:
                        lines = split_content.split("\n")
                        sub_contents = []
                        sub_lines = []

                        for line in lines:
                            test_lines = sub_lines + [line]
                            test_html = generate_card_html(
                                "\n".join(test_lines), 1, 1, style_key
                            )
                            test_height = await measure_content_height(page, test_html)

                            if test_height > CARD_HEIGHT - 100 and sub_lines:
                                sub_contents.append("\n".join(sub_lines))
                                sub_lines = [line]
                            else:
                                sub_lines = test_lines

                        if sub_lines:
                            sub_contents.append("\n".join(sub_lines))

                        all_cards.extend(sub_contents)
                    else:
                        all_cards.append(split_content)

        finally:
            await browser.close()

    return all_cards


async def render_markdown_to_cards(
    md_file: str, output_dir: str, style_key: str = "purple"
):
    """主渲染函数：将 Markdown 文件渲染为多张卡片图片"""
    print(f"\n🎨 开始渲染: {md_file}")
    print(f"🎨 使用样式: {STYLES[style_key]['name']}")

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    # 解析 Markdown 文件
    data = parse_markdown_file(md_file)
    metadata = data["metadata"]
    body = data["body"]

    # 分割正文内容（基于用户手动分隔符）
    card_contents = split_content_by_separator(body)
    print(f"  📄 检测到 {len(card_contents)} 个内容块")

    # 处理内容，智能分页
    print("  🔍 分析内容高度并智能分页...")
    processed_cards = await process_and_render_cards(
        card_contents, output_dir, style_key
    )
    total_cards = len(processed_cards)
    print(f"  📄 将生成 {total_cards} 张卡片")

    # 生成封面
    if metadata.get("emoji") or metadata.get("title"):
        print("  📷 生成封面...")
        cover_html = generate_cover_html(metadata, style_key)
        cover_path = os.path.join(output_dir, "cover.png")
        await render_html_to_image(cover_html, cover_path)

    # 生成正文卡片
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport={"width": CARD_WIDTH, "height": CARD_HEIGHT}
        )

        try:
            for i, content in enumerate(processed_cards, 1):
                print(f"  📷 生成卡片 {i}/{total_cards}...")
                card_html = generate_card_html(content, i, total_cards, style_key)
                card_path = os.path.join(output_dir, f"card_{i}.png")

                await page.set_content(card_html, wait_until="networkidle")
                await page.wait_for_timeout(300)

                await page.screenshot(
                    path=card_path,
                    clip={"x": 0, "y": 0, "width": CARD_WIDTH, "height": CARD_HEIGHT},
                    type="png",
                )
                print(f"  ✅ 已生成: {card_path}")

        finally:
            await browser.close()

    print(f"\n✨ 渲染完成！共生成 {total_cards} 张卡片，保存到: {output_dir}")
    return total_cards


def list_styles():
    """列出所有可用样式"""
    print("\n📋 可用样式列表：")
    print("-" * 40)
    for key, style in STYLES.items():
        print(f"  {key:12} - {style['name']}")
    print("-" * 40)


def main():
    parser = argparse.ArgumentParser(
        description="将 Markdown 文件渲染为小红书风格的图片卡片（智能分页版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python render_xhs_v2.py note.md
  python render_xhs_v2.py note.md -o ./output --style xiaohongshu
  python render_xhs_v2.py --list-styles
        """,
    )
    parser.add_argument("markdown_file", nargs="?", help="Markdown 文件路径")
    parser.add_argument(
        "--output-dir", "-o", default=os.getcwd(), help="输出目录（默认为当前工作目录）"
    )
    parser.add_argument(
        "--style",
        "-s",
        default="purple",
        choices=list(STYLES.keys()),
        help="样式主题（默认: purple）",
    )
    parser.add_argument("--list-styles", action="store_true", help="列出所有可用样式")

    args = parser.parse_args()

    if args.list_styles:
        list_styles()
        return

    if not args.markdown_file:
        parser.print_help()
        sys.exit(1)

    if not os.path.exists(args.markdown_file):
        print(f"❌ 错误: 文件不存在 - {args.markdown_file}")
        sys.exit(1)

    asyncio.run(
        render_markdown_to_cards(args.markdown_file, args.output_dir, args.style)
    )


if __name__ == "__main__":
    main()
