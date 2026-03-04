#!/usr/bin/env python3
"""生成 macOS icns 图标文件"""

import os
import struct
from PIL import Image


def create_icns_png_section(png_data, icon_type):
    """创建 icns 中的 PNG 段"""
    # icns 段格式: 4字节类型 + 4字节长度 + 数据
    length = 8 + len(png_data)
    return struct.pack('>4sI', icon_type.encode('ascii'), length) + png_data


def create_icns(icons_dir, output_path):
    """从 PNG 文件创建 icns 文件"""

    # 定义 icns 图标类型和尺寸映射
    icon_types = {
        16: 'icp4',    # 16x16
        32: 'icp5',    # 32x32
        64: 'icp6',    # 64x64 (32@2x)
        128: 'ic07',   # 128x128
        256: 'ic08',   # 256x256
        512: 'ic09',   # 512x512
        1024: 'ic10',  # 1024x1024 (512@2x)
    }

    sections = []

    # 读取各个尺寸的图标
    icon_files = {
        16: '32x32.png',      # 16x16 通常用 32x32 缩小
        32: '32x32.png',
        64: '32x32@2x.png',
        128: '128x128.png',
        256: '128x128@2x.png',
        512: 'icon.png',
    }

    for size, filename in icon_files.items():
        filepath = os.path.join(icons_dir, filename)
        if os.path.exists(filepath) and size in icon_types:
            with open(filepath, 'rb') as f:
                png_data = f.read()
            sections.append(create_icns_png_section(png_data, icon_types[size]))
            print(f"Added: {icon_types[size]} ({size}x{size})")

    if not sections:
        print("Error: No icon files found")
        return False

    # 创建 icns 文件
    # icns 文件头: 4字节魔数 'icns' + 4字节总长度
    total_length = 8 + sum(len(s) for s in sections)
    header = struct.pack('>4sI', b'icns', total_length)

    with open(output_path, 'wb') as f:
        f.write(header)
        for section in sections:
            f.write(section)

    print(f"\nCreated: {output_path}")
    return True


if __name__ == "__main__":
    icons_dir = "/Users/zhangzheng/zavixai/Sage/app/desktop/tauri/icons"
    output_path = os.path.join(icons_dir, "icon.icns")

    if create_icns(icons_dir, output_path):
        print("ICNS file generated successfully!")
    else:
        print("Failed to generate ICNS file")
