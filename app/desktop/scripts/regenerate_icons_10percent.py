#!/usr/bin/env python3
"""重新生成所有需要的图标 - 使用 10% 边距（标准）"""

import os
import subprocess
import shutil
from PIL import Image

base_dir = "/Users/zhangzheng/workspace/Sage/app/desktop"
icons_dir = os.path.join(base_dir, "tauri", "icons")
backup_dir = os.path.join(icons_dir, "backup")
source_icon = os.path.join(backup_dir, "icon.png")

print(f"Source: {source_icon}")

with Image.open(source_icon) as img:
    img = img.convert('RGBA')
    
    # 生成 PNG 图标 (10% 边距 - 标准)
    png_sizes = {
        '32x32.png': 32,
        '128x128.png': 128,
        '128x128@2x.png': 256,
    }
    for filename, size in png_sizes.items():
        padding = int(size * 0.10)  # 10% 边距
        content_size = size - (padding * 2)
        img_resized = img.resize((content_size, content_size), Image.Resampling.LANCZOS)
        new_img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        new_img.paste(img_resized, (padding, padding))
        new_img.save(os.path.join(icons_dir, filename), 'PNG')
        print(f'Generated: {filename}')
    
    # 生成 icon.png (512)
    padding = int(512 * 0.10)
    content_size = 512 - (padding * 2)
    img_resized = img.resize((content_size, content_size), Image.Resampling.LANCZOS)
    new_img = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
    new_img.paste(img_resized, (padding, padding))
    new_img.save(os.path.join(icons_dir, 'icon.png'), 'PNG')
    print('Generated: icon.png')

# 生成 icon.icns
iconset_dir = os.path.join(icons_dir, 'icon.iconset')
if os.path.exists(iconset_dir):
    shutil.rmtree(iconset_dir)
os.makedirs(iconset_dir)

with Image.open(source_icon) as img:
    img = img.convert('RGBA')
    sizes = {
        16: ['icon_16x16.png'],
        32: ['icon_16x16@2x.png', 'icon_32x32.png'],
        64: ['icon_32x32@2x.png'],
        128: ['icon_128x128.png'],
        256: ['icon_128x128@2x.png', 'icon_256x256.png'],
        512: ['icon_256x256@2x.png', 'icon_512x512.png'],
        1024: ['icon_512x512@2x.png']
    }
    
    for size, filenames in sizes.items():
        padding = int(size * 0.10)  # 10% 边距
        content_size = size - (padding * 2)
        img_resized = img.resize((content_size, content_size), Image.Resampling.LANCZOS)
        new_img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        new_img.paste(img_resized, (padding, padding))
        for filename in filenames:
            new_img.save(os.path.join(iconset_dir, filename), 'PNG')

result = subprocess.run(['iconutil', '-c', 'icns', iconset_dir, '-o', os.path.join(icons_dir, 'icon.icns')], capture_output=True, text=True)
if result.returncode == 0:
    print('Generated: icon.icns')
else:
    print(f'Error: {result.stderr}')

shutil.rmtree(iconset_dir)
print('Done! Icons regenerated with 10% padding (standard)')
