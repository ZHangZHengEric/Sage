#!/usr/bin/env python3
"""生成带有6%边距的 macOS Dock 图标"""

import os
import sys
from PIL import Image


def create_icon_with_padding(input_path, output_path, size, padding_percent=0.06):
    """
    创建带有边距的图标

    Args:
        input_path: 输入图标路径
        output_path: 输出图标路径
        size: 输出图标尺寸
        padding_percent: 边距百分比（默认6%）
    """
    # 打开原始图标
    with Image.open(input_path) as img:
        # 转换为RGBA模式
        img = img.convert('RGBA')

        # 计算内容区域（去除边距）
        padding = int(size * padding_percent)
        content_size = size - (padding * 2)

        # 调整原始图标大小到内容区域
        img_resized = img.resize((content_size, content_size), Image.Resampling.LANCZOS)

        # 创建新图像（透明背景）
        new_img = Image.new('RGBA', (size, size), (0, 0, 0, 0))

        # 将调整后的图标粘贴到中心
        new_img.paste(img_resized, (padding, padding))

        # 保存
        new_img.save(output_path, 'PNG')
        print(f"Created: {output_path} ({size}x{size})")


def generate_all_icons():
    """生成所有尺寸的图标"""

    # 图标目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up two levels to reach app/desktop
    base_dir = os.path.dirname(os.path.dirname(script_dir))
    
    icons_dir = os.path.join(base_dir, "tauri", "icons")
    backup_dir = os.path.join(icons_dir, "backup")

    # 使用备份的 icon.png 作为源文件
    source_icon = os.path.join(backup_dir, "icon.png")

    if not os.path.exists(source_icon):
        print(f"Error: Source icon not found: {source_icon}")
        return

    # 生成新图标
    sizes = {
        "icon.png": 512,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "32x32.png": 32,
        "32x32@2x.png": 64,
    }

    for filename, size in sizes.items():
        output_path = os.path.join(icons_dir, filename)
        create_icon_with_padding(source_icon, output_path, size, padding_percent=0.06)

    print("\nAll icons generated successfully with 6% padding!")


if __name__ == "__main__":
    try:
        from PIL import Image
    except ImportError:
        print("Error: PIL/Pillow is not installed.")
        print("Install it with: pip install Pillow")
        sys.exit(1)

    generate_all_icons()
