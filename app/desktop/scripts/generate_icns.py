#!/usr/bin/env python3
"""生成 macOS icns 图标文件 - 使用 iconutil"""

import os
import shutil
import subprocess
from PIL import Image

def generate_iconset(source_path, iconset_dir):
    """从源图像生成 .iconset 目录"""
    if not os.path.exists(source_path):
        print(f"Error: Source image not found at {source_path}")
        return False
        
    if not os.path.exists(iconset_dir):
        os.makedirs(iconset_dir)
        
    print(f"Generating iconset from {source_path}...")
    
    try:
        with Image.open(source_path) as img:
            # Convert to RGBA if not already
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
                
            # Define required sizes and filenames for iconutil
            # iconutil requires specific filenames: icon_<size>x<size>[@2x].png
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
                # High-quality resize
                resized_img = img.resize((size, size), Image.Resampling.LANCZOS)
                
                for filename in filenames:
                    output_path = os.path.join(iconset_dir, filename)
                    resized_img.save(output_path, 'PNG')
                    print(f"Generated: {filename} ({size}x{size})")
                
            return True
    except Exception as e:
        print(f"Error generating iconset: {e}")
        return False


def create_icns_with_iconutil(iconset_dir, output_path):
    """使用 iconutil 创建 icns 文件"""
    print(f"Running iconutil to create {output_path}...")
    try:
        # iconutil -c icns <iconset_dir> -o <output_path>
        result = subprocess.run(
            ['iconutil', '-c', 'icns', iconset_dir, '-o', output_path],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"Successfully created: {output_path}")
            return True
        else:
            print(f"Error running iconutil: {result.stderr}")
            return False
    except Exception as e:
        print(f"Exception running iconutil: {e}")
        return False


if __name__ == "__main__":
    # Get the directory where the script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Source image path (sage_logo.png)
    # script_dir is .../app/desktop/scripts
    # source is .../app/desktop/ui/public/sage_logo.png
    source_image = os.path.join(os.path.dirname(script_dir), "ui", "public", "sage_logo.png")
    
    # Icons directory
    icons_dir = os.path.join(os.path.dirname(script_dir), "tauri", "icons")
    
    # Temporary iconset directory
    iconset_dir = os.path.join(icons_dir, "icon.iconset")
    
    # Output path
    output_path = os.path.join(icons_dir, "icon.icns")
    
    print(f"Source image: {source_image}")
    print(f"Iconset directory: {iconset_dir}")
    print(f"Output path: {output_path}")

    # 1. Generate .iconset directory with PNGs
    if generate_iconset(source_image, iconset_dir):
        # 2. Use iconutil to pack into .icns
        if create_icns_with_iconutil(iconset_dir, output_path):
            print("ICNS file generated successfully!")
            
            # 3. Clean up iconset directory
            try:
                shutil.rmtree(iconset_dir)
                print("Cleaned up iconset directory.")
            except Exception as e:
                print(f"Warning: Failed to clean up iconset directory: {e}")
                
            # 4. Generate other standalone PNGs needed by Tauri (e.g. for Windows/Linux or other uses)
            # Tauri often expects: 32x32.png, 128x128.png, 128x128@2x.png, icon.png
            print("\nGenerating standalone PNGs for Tauri configuration...")
            try:
                with Image.open(source_image) as img:
                     if img.mode != 'RGBA':
                        img = img.convert('RGBA')
                        
                     standalone_sizes = {
                        32: '32x32.png',
                        64: '32x32@2x.png',
                        128: '128x128.png',
                        256: '128x128@2x.png',
                        512: 'icon.png'
                     }
                     
                     for size, filename in standalone_sizes.items():
                         out_p = os.path.join(icons_dir, filename)
                         img.resize((size, size), Image.Resampling.LANCZOS).save(out_p, 'PNG')
                         print(f"Generated standalone: {filename}")
            except Exception as e:
                print(f"Error generating standalone PNGs: {e}")

        else:
            print("Failed to generate ICNS file using iconutil")
    else:
        print("Failed to generate iconset")
