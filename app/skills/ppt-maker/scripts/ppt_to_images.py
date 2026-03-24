#!/usr/bin/env python3
"""
PPT 转图片工具
使用 LibreOffice 将 PPT 转换为 PDF，然后使用 pdf2image 转换为图片
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def ppt_to_pdf(ppt_path: str, output_dir: str) -> str:
    """使用 LibreOffice 将 PPT 转换为 PDF"""
    ppt_path = Path(ppt_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # LibreOffice 命令
    cmd = [
        "soffice",
        "--headless",
        "--convert-to", "pdf",
        "--outdir", str(output_dir),
        str(ppt_path)
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode != 0:
            print(f"LibreOffice error: {result.stderr}", file=sys.stderr)
            return None

        # 生成的 PDF 文件路径
        pdf_name = ppt_path.stem + ".pdf"
        pdf_path = output_dir / pdf_name

        if pdf_path.exists():
            return str(pdf_path)
        else:
            print(f"PDF file not found: {pdf_path}", file=sys.stderr)
            return None

    except subprocess.TimeoutExpired:
        print("LibreOffice conversion timeout", file=sys.stderr)
        return None
    except FileNotFoundError:
        print("LibreOffice not found. Please install LibreOffice.", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error converting PPT to PDF: {e}", file=sys.stderr)
        return None


def pdf_to_images(pdf_path: str, output_dir: str, dpi: int = 150) -> list:
    """使用 pdf2image 将 PDF 转换为图片"""
    try:
        from pdf2image import convert_from_path

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 转换 PDF 为图片
        images = convert_from_path(
            pdf_path,
            dpi=dpi,
            fmt='png',
            output_folder=str(output_dir),
            paths_only=True
        )

        return images

    except ImportError:
        print("pdf2image not installed. Please install: pip install pdf2image", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Error converting PDF to images: {e}", file=sys.stderr)
        return []


def convert_ppt_to_images(ppt_path: str, output_dir: str, dpi: int = 150) -> list:
    """将 PPT 转换为图片列表"""
    ppt_path = Path(ppt_path)

    if not ppt_path.exists():
        print(f"PPT file not found: {ppt_path}", file=sys.stderr)
        return []

    # 创建临时目录
    with tempfile.TemporaryDirectory() as temp_dir:
        # 第一步：PPT -> PDF
        print(f"Converting PPT to PDF: {ppt_path}")
        pdf_path = ppt_to_pdf(str(ppt_path), temp_dir)

        if not pdf_path:
            return []

        print(f"PDF generated: {pdf_path}")

        # 第二步：PDF -> Images
        print(f"Converting PDF to images (DPI={dpi})")
        images = pdf_to_images(pdf_path, output_dir, dpi)

        if images:
            print(f"Generated {len(images)} images")
            # 重命名图片文件
            renamed_images = []
            for i, img_path in enumerate(sorted(images), 1):
                old_path = Path(img_path)
                new_name = f"slide_{i:03d}.png"
                new_path = Path(output_dir) / new_name
                old_path.rename(new_path)
                renamed_images.append(str(new_path))
            return renamed_images
        else:
            print("No images generated", file=sys.stderr)
            return []


def main():
    parser = argparse.ArgumentParser(description="Convert PPT to images")
    parser.add_argument("ppt_path", help="Path to PPT file")
    parser.add_argument("-o", "--output", default=".", help="Output directory")
    parser.add_argument("--dpi", type=int, default=150, help="DPI for image conversion (default: 150)")

    args = parser.parse_args()

    images = convert_ppt_to_images(args.ppt_path, args.output, args.dpi)

    if images:
        print("\nGenerated images:")
        for img in images:
            print(f"  - {img}")
        return 0
    else:
        print("\nFailed to generate images", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
