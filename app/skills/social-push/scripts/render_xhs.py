#!/usr/bin/env python3
"""
小红书卡片渲染脚本 - 增强版
支持多种排版样式和智能分页策略

使用方法:
    python render_xhs.py <markdown_file> [options]

选项:
    --output-dir, -o     输出目录（默认为当前工作目录）
    --theme, -t          排版主题：default, playful-geometric, neo-brutalism, 
                         botanical, professional, retro, terminal, sketch
    --mode, -m           分页模式：
                         - separator  : 按 --- 分隔符手动分页（默认）
                         - auto-fit   : 自动缩放文字以填满固定尺寸
                         - auto-split : 根据内容高度自动切分
                         - dynamic    : 根据内容动态调整图片高度
    --width, -w          图片宽度（默认 1080）
    --height, -h         图片高度（默认 1440，dynamic 模式下为最小高度）
    --max-height         dynamic 模式下的最大高度（默认 4320
    --dpr                设备像素比（默认 2）

依赖安装:
    pip install markdown pyyaml playwright
    playwright install chromium
"""

import argparse
import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import markdown
    import yaml
    from playwright.async_api import async_playwright
except ImportError as e:
    print(f"缺少依赖: {e}")
    print("请运行: pip install markdown pyyaml playwright && playwright install chromium")
    sys.exit(1)


# 获取脚本所在目录
SCRIPT_DIR = Path(__file__).parent.parent
ASSETS_DIR = SCRIPT_DIR / "assets"
THEMES_DIR = ASSETS_DIR / "themes"

# 默认卡片尺寸配置 (3:4 比例)
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1440
MAX_HEIGHT = 4320  # dynamic 模式最大高度

# 可用主题列表
AVAILABLE_THEMES = [
    'default',
    'playful-geometric',
    'neo-brutalism',
    'botanical',
    'professional',
    'retro',
    'terminal',
    'sketch'
]

# 分页模式
PAGING_MODES = ['separator', 'auto-fit', 'auto-split', 'dynamic']


def parse_markdown_file(file_path: str) -> dict:
    """解析 Markdown 文件，提取 YAML 头部和正文内容"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 解析 YAML 头部
    yaml_pattern = r'^---\s*\n(.*?)\n---\s*\n'
    yaml_match = re.match(yaml_pattern, content, re.DOTALL)
    
    metadata = {}
    body = content
    
    if yaml_match:
        try:
            metadata = yaml.safe_load(yaml_match.group(1)) or {}
        except yaml.YAMLError:
            metadata = {}
        body = content[yaml_match.end():]
    
    return {
        'metadata': metadata,
        'body': body.strip()
    }


def split_content_by_separator(body: str) -> List[str]:
    """按照 --- 分隔符拆分正文为多张卡片内容"""
    parts = re.split(r'\n---+\n', body)
    return [part.strip() for part in parts if part.strip()]


def convert_markdown_to_html(md_content: str) -> str:
    """将 Markdown 转换为 HTML"""
    # 处理 tags（以 # 开头的标签）
    tags_pattern = r'((?:#[\w\u4e00-\u9fa5]+\s*)+)$'
    tags_match = re.search(tags_pattern, md_content, re.MULTILINE)
    tags_html = ""
    
    if tags_match:
        tags_str = tags_match.group(1)
        md_content = md_content[:tags_match.start()].strip()
        tags = re.findall(r'#([\w\u4e00-\u9fa5]+)', tags_str)
        if tags:
            tags_html = '<div class="tags-container">'
            for tag in tags:
                tags_html += f'<span class="tag">#{tag}</span>'
            tags_html += '</div>'
    
    # 转换 Markdown 为 HTML
    html = markdown.markdown(
        md_content,
        extensions=['extra', 'codehilite', 'tables', 'nl2br']
    )
    
    return html + tags_html


def load_theme_css(theme: str) -> str:
    """加载主题 CSS 样式"""
    theme_file = THEMES_DIR / f"{theme}.css"
    if theme_file.exists():
        with open(theme_file, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        # 如果主题不存在，使用默认主题
        default_file = THEMES_DIR / "default.css"
        if default_file.exists():
            with open(default_file, 'r', encoding='utf-8') as f:
                return f.read()
        return ""


def generate_cover_html(metadata: dict, theme: str, width: int, height: int) -> str:
    """生成封面 HTML"""
    emoji = metadata.get('emoji', '📝')
    title = metadata.get('title', '标题')
    subtitle = metadata.get('subtitle', '')
    
    
    # 动态调整标题字体大小
    title_len = len(title)
    if title_len <= 6:
        title_size = int(width * 0.14)  # 极大
    elif title_len <= 10:
        title_size = int(width * 0.12)  # 大
    elif title_len <= 18:
        title_size = int(width * 0.09)  # 中
    elif title_len <= 30:
        title_size = int(width * 0.07)  # 小
    else:
        title_size = int(width * 0.055) # 极小

    # 获取主题背景色
    theme_backgrounds = {
        'default': 'linear-gradient(180deg, #f3f3f3 0%, #f9f9f9 100%)',
        'playful-geometric': 'linear-gradient(180deg, #8B5CF6 0%, #F472B6 100%)',
        'neo-brutalism': 'linear-gradient(180deg, #FF4757 0%, #FECA57 100%)',
        'botanical': 'linear-gradient(180deg, #4A7C59 0%, #8FBC8F 100%)',
        'professional': 'linear-gradient(180deg, #2563EB 0%, #3B82F6 100%)',
        'retro': 'linear-gradient(180deg, #D35400 0%, #F39C12 100%)',
        'terminal': 'linear-gradient(180deg, #0D1117 0%, #21262D 100%)',
        'sketch': 'linear-gradient(180deg, #555555 0%, #999999 100%)'
    }
    bg = theme_backgrounds.get(theme, theme_backgrounds['default'])

    # 封面标题文字渐变随主题变化
    title_gradients = {
        'default': 'linear-gradient(180deg, #111827 0%, #4B5563 100%)',
        'playful-geometric': 'linear-gradient(180deg, #7C3AED 0%, #F472B6 100%)',
        'neo-brutalism': 'linear-gradient(180deg, #000000 0%, #FF4757 100%)',
        'botanical': 'linear-gradient(180deg, #1F2937 0%, #4A7C59 100%)',
        'professional': 'linear-gradient(180deg, #1E3A8A 0%, #2563EB 100%)',
        'retro': 'linear-gradient(180deg, #8B4513 0%, #D35400 100%)',
        'terminal': 'linear-gradient(180deg, #39D353 0%, #58A6FF 100%)',
        'sketch': 'linear-gradient(180deg, #111827 0%, #6B7280 100%)',
    }
    title_bg = title_gradients.get(theme, title_gradients['default'])
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width={width}, height={height}">
    <title>小红书封面</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700;900&display=swap');
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Noto Sans SC', 'Source Han Sans CN', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            width: {width}px;
            height: {height}px;
            overflow: hidden;
        }}
        
        .cover-container {{
            width: {width}px;
            height: {height}px;
            background: {bg};
            position: relative;
            overflow: hidden;
        }}
        
        .cover-inner {{
            position: absolute;
            width: {int(width * 0.88)}px;
            height: {int(height * 0.91)}px;
            left: {int(width * 0.06)}px;
            top: {int(height * 0.045)}px;
            background: #F3F3F3;
            border-radius: 25px;
            display: flex;
            flex-direction: column;
            padding: {int(width * 0.074)}px {int(width * 0.079)}px;
        }}
        
        .cover-emoji {{
            font-size: {int(width * 0.167)}px;
            line-height: 1.2;
            margin-bottom: {int(height * 0.035)}px;
        }}
        
        .cover-title {{
            font-weight: 900;
            font-size: {title_size}px;
            line-height: 1.4;
            background: {title_bg};
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            flex: 1;
            display: flex;
            align-items: flex-start;
            word-break: break-all;
        }}
        
        .cover-subtitle {{
            font-weight: 350;
            font-size: {int(width * 0.067)}px;
            line-height: 1.4;
            color: #000000;
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
</html>'''
    return html


def generate_card_html(content: str, theme: str, page_number: int = 1, 
                       total_pages: int = 1, width: int = DEFAULT_WIDTH, 
                       height: int = DEFAULT_HEIGHT, mode: str = 'separator') -> str:
    """生成正文卡片 HTML"""
    
    html_content = convert_markdown_to_html(content)
    theme_css = load_theme_css(theme)
    
    page_text = f"{page_number}/{total_pages}" if total_pages > 1 else ""
    
    # 获取主题背景色
    theme_backgrounds = {
        'default': 'linear-gradient(180deg, #f3f3f3 0%, #f9f9f9 100%)',
        'playful-geometric': 'linear-gradient(135deg, #8B5CF6 0%, #F472B6 100%)',
        'neo-brutalism': 'linear-gradient(135deg, #FF4757 0%, #FECA57 100%)',
        'botanical': 'linear-gradient(135deg, #4A7C59 0%, #8FBC8F 100%)',
        'professional': 'linear-gradient(135deg, #2563EB 0%, #3B82F6 100%)',
        'retro': 'linear-gradient(135deg, #D35400 0%, #F39C12 100%)',
        'terminal': 'linear-gradient(135deg, #0D1117 0%, #161B22 100%)',
        'sketch': 'linear-gradient(135deg, #555555 0%, #888888 100%)'
    }
    bg = theme_backgrounds.get(theme, theme_backgrounds['default'])
    
    # 根据模式设置不同的容器样式
    if mode == 'auto-fit':
        container_style = f'''
            width: {width}px;
            height: {height}px;
            background: {bg};
            position: relative;
            padding: 50px;
            overflow: hidden;
        '''
        inner_style = f'''
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 60px;
            height: calc({height}px - 100px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(10px);
            overflow: hidden;
            display: flex;
            flex-direction: column;
        '''
        content_style = '''
            flex: 1;
            overflow: hidden;
        '''
    elif mode == 'dynamic':
        container_style = f'''
            width: {width}px;
            min-height: {height}px;
            background: {bg};
            position: relative;
            padding: 50px;
        '''
        inner_style = '''
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 60px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(10px);
        '''
        content_style = ''
    else:  # separator 和 auto-split
        container_style = f'''
            width: {width}px;
            min-height: {height}px;
            background: {bg};
            position: relative;
            padding: 50px;
            overflow: hidden;
        '''
        inner_style = f'''
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 60px;
            min-height: calc({height}px - 100px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(10px);
        '''
        content_style = ''
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width={width}">
    <title>小红书卡片</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700;900&display=swap');
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Noto Sans SC', 'Source Han Sans CN', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            width: {width}px;
            overflow: hidden;
            background: transparent;
        }}
        
        .card-container {{
            {container_style}
        }}
        
        .card-inner {{
            {inner_style}
        }}
        
        .card-content {{
            line-height: 1.7;
            {content_style}
        }}

        /* auto-fit 用：对整个内容块做 transform 缩放 */
        .card-content-scale {{
            transform-origin: top left;
            will-change: transform;
        }}
        
        {theme_css}
        
        .page-number {{
            position: absolute;
            bottom: 80px;
            right: 80px;
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
                <div class="card-content-scale">{html_content}</div>
            </div>
        </div>
        <div class="page-number">{page_text}</div>
    </div>
</body>
</html>'''
    return html


async def render_html_to_image(html_content: str, output_path: str, 
                               width: int = DEFAULT_WIDTH, 
                               height: int = DEFAULT_HEIGHT,
                               mode: str = 'separator',
                               max_height: int = MAX_HEIGHT,
                               dpr: int = 2):
    """使用 Playwright 将 HTML 渲染为图片"""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        
        # 设置视口大小
        viewport_height = height if mode != 'dynamic' else max_height
        page = await browser.new_page(
            viewport={'width': width, 'height': viewport_height},
            device_scale_factor=dpr
        )
        
        # 创建临时 HTML 文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
            f.write(html_content)
            temp_html_path = f.name
        
        try:
            await page.goto(f'file://{temp_html_path}')
            await page.wait_for_load_state('networkidle')
            
            # 等待字体加载
            await page.wait_for_timeout(500)
            
            if mode == 'auto-fit':
                # 自动缩放模式：对整个内容块做 transform 缩放（标题/代码块等固定 px 也会一起缩放）
                await page.evaluate('''() => {
                    const viewportContent = document.querySelector('.card-content');
                    const scaleEl = document.querySelector('.card-content-scale');
                    if (!viewportContent || !scaleEl) return;

                    // 先重置，测量原始尺寸
                    scaleEl.style.transform = 'none';
                    scaleEl.style.width = '';
                    scaleEl.style.height = '';

                    const availableWidth = viewportContent.clientWidth;
                    const availableHeight = viewportContent.clientHeight;

                    // scrollWidth/scrollHeight 反映内容的自然尺寸
                    const contentWidth = Math.max(scaleEl.scrollWidth, scaleEl.getBoundingClientRect().width);
                    const contentHeight = Math.max(scaleEl.scrollHeight, scaleEl.getBoundingClientRect().height);

                    if (!contentWidth || !contentHeight || !availableWidth || !availableHeight) return;

                    // 只缩小不放大，避免“撑太大”
                    const scale = Math.min(1, availableWidth / contentWidth, availableHeight / contentHeight);

                    // 为避免 transform 后布局尺寸不匹配导致裁切，扩大布局盒子
                    scaleEl.style.width = (availableWidth / scale) + 'px';

                    // 顶部对齐更稳；如需居中可计算 offset
                    const offsetX = 0;
                    const offsetY = 0;

                    scaleEl.style.transformOrigin = 'top left';
                    scaleEl.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
                }''')
                await page.wait_for_timeout(100)
                actual_height = height
                
            elif mode == 'dynamic':
                # 动态高度模式：根据内容调整图片高度
                content_height = await page.evaluate('''() => {
                    const container = document.querySelector('.card-container');
                    return container ? container.scrollHeight : document.body.scrollHeight;
                }''')
                # 确保高度在合理范围内
                actual_height = max(height, min(content_height, max_height))
                
            else:  # separator 和 auto-split
                # 获取实际内容高度
                content_height = await page.evaluate('''() => {
                    const container = document.querySelector('.card-container');
                    return container ? container.scrollHeight : document.body.scrollHeight;
                }''')
                actual_height = max(height, content_height)
            
            # 截图
            await page.screenshot(
                path=output_path,
                clip={'x': 0, 'y': 0, 'width': width, 'height': actual_height},
                type='png'
            )
            
            print(f"  ✅ 已生成: {output_path} ({width}x{actual_height})")
            return actual_height
            
        finally:
            os.unlink(temp_html_path)
            await browser.close()


async def auto_split_content(body: str, theme: str, width: int, height: int, 
                             dpr: int = 2) -> List[str]:
    """自动切分内容：根据渲染后的高度自动分页"""
    
    # 将内容按段落分割
    paragraphs = re.split(r'\n\n+', body)
    
    cards = []
    current_content = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport={'width': width, 'height': height * 2},
            device_scale_factor=dpr
        )
        
        try:
            for para in paragraphs:
                # 尝试将当前段落加入
                test_content = current_content + [para]
                test_md = '\n\n'.join(test_content)
                
                html = generate_card_html(test_md, theme, 1, 1, width, height, 'auto-split')
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
                    f.write(html)
                    temp_path = f.name
                
                await page.goto(f'file://{temp_path}')
                await page.wait_for_load_state('networkidle')
                await page.wait_for_timeout(200)
                
                content_height = await page.evaluate('''() => {
                    const content = document.querySelector('.card-content');
                    return content ? content.scrollHeight : 0;
                }''')
                
                os.unlink(temp_path)
                
                # 内容区域的可用高度（去除 padding 等）
                available_height = height - 220  # 50*2 padding + 60*2 inner padding
                
                if content_height > available_height and current_content:
                    # 当前卡片已满，保存并开始新卡片
                    cards.append('\n\n'.join(current_content))
                    current_content = [para]
                else:
                    current_content = test_content
            
            # 保存最后一张卡片
            if current_content:
                cards.append('\n\n'.join(current_content))
                
        finally:
            await browser.close()
    
    return cards


async def render_markdown_to_cards(md_file: str, output_dir: str, 
                                   theme: str = 'default',
                                   mode: str = 'separator',
                                   width: int = DEFAULT_WIDTH,
                                   height: int = DEFAULT_HEIGHT,
                                   max_height: int = MAX_HEIGHT,
                                   dpr: int = 2):
    """主渲染函数：将 Markdown 文件渲染为多张卡片图片"""
    print(f"\n🎨 开始渲染: {md_file}")
    print(f"  📐 主题: {theme}")
    print(f"  📏 模式: {mode}")
    print(f"  📐 尺寸: {width}x{height}")
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 解析 Markdown 文件
    data = parse_markdown_file(md_file)
    metadata = data['metadata']
    body = data['body']
    
    # 根据模式处理内容分割
    if mode == 'auto-split':
        print("  ⏳ 自动分析内容并切分...")
        card_contents = await auto_split_content(body, theme, width, height, dpr)
    else:
        card_contents = split_content_by_separator(body)
    
    total_cards = len(card_contents)
    print(f"  📄 检测到 {total_cards} 张正文卡片")
    
    # 生成封面
    if metadata.get('emoji') or metadata.get('title'):
        print("  📷 生成封面...")
        cover_html = generate_cover_html(metadata, theme, width, height)
        cover_path = os.path.join(output_dir, 'cover.png')
        await render_html_to_image(cover_html, cover_path, width, height, 'separator', max_height, dpr)
    
    # 生成正文卡片
    for i, content in enumerate(card_contents, 1):
        print(f"  📷 生成卡片 {i}/{total_cards}...")
        card_html = generate_card_html(content, theme, i, total_cards, width, height, mode)
        card_path = os.path.join(output_dir, f'card_{i}.png')
        await render_html_to_image(card_html, card_path, width, height, mode, max_height, dpr)
    
    print(f"\n✨ 渲染完成！图片已保存到: {output_dir}")
    return total_cards


def main():
    parser = argparse.ArgumentParser(
        description='将 Markdown 文件渲染为小红书风格的图片卡片（支持多种样式和分页模式）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
可用主题:
  default           - 默认紫色渐变风格
  playful-geometric - 活泼几何风格（Memphis 设计）
  neo-brutalism     - 新粗野主义风格
  botanical         - 植物园自然风格
  professional      - 专业商务风格
  retro             - 复古怀旧风格
  terminal          - 终端/命令行风格
  sketch            - 手绘素描风格

分页模式:
  separator   - 按 --- 分隔符手动分页（默认）
  auto-fit    - 自动缩放文字以填满固定尺寸
  auto-split  - 根据内容高度自动切分
  dynamic     - 根据内容动态调整图片高度
'''
    )
    parser.add_argument(
        'markdown_file',
        help='Markdown 文件路径'
    )
    parser.add_argument(
        '--output-dir', '-o',
        default=os.getcwd(),
        help='输出目录（默认为当前工作目录）'
    )
    parser.add_argument(
        '--theme', '-t',
        choices=AVAILABLE_THEMES,
        default='default',
        help='排版主题（默认: default）'
    )
    parser.add_argument(
        '--mode', '-m',
        choices=PAGING_MODES,
        default='separator',
        help='分页模式（默认: separator）'
    )
    parser.add_argument(
        '--width', '-w',
        type=int,
        default=DEFAULT_WIDTH,
        help=f'图片宽度（默认: {DEFAULT_WIDTH}）'
    )
    parser.add_argument(
        '--height',
        type=int,
        default=DEFAULT_HEIGHT,
        help=f'图片高度（默认: {DEFAULT_HEIGHT}）'
    )
    parser.add_argument(
        '--max-height',
        type=int,
        default=MAX_HEIGHT,
        help=f'dynamic 模式下的最大高度（默认: {MAX_HEIGHT}）'
    )
    parser.add_argument(
        '--dpr',
        type=int,
        default=2,
        help='设备像素比（默认: 2）'
    )
    
    args = parser.parse_args()
    
    if not os.path.exists(args.markdown_file):
        print(f"❌ 错误: 文件不存在 - {args.markdown_file}")
        sys.exit(1)
    
    asyncio.run(render_markdown_to_cards(
        args.markdown_file,
        args.output_dir,
        theme=args.theme,
        mode=args.mode,
        width=args.width,
        height=args.height,
        max_height=args.max_height,
        dpr=args.dpr
    ))


if __name__ == '__main__':
    main()
