#!/usr/bin/env python3
"""
PPT 渲染服务 MCP Server
提供 PPT 转图片功能，用于前端预览
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

# 添加 ppt-maker 脚本路径
sys.path.insert(0, "/Users/zhangzheng/zavixai/Sage/app/skills/ppt-maker/scripts")
from ppt_to_images import convert_ppt_to_images

from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel
)
import mcp.types as types


server = Server("ppt_renderer")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available tools for PPT rendering."""
    return [
        Tool(
            name="render_ppt_to_images",
            description="将 PPT 文件渲染为图片列表，用于前端预览。",
            inputSchema={
                "type": "object",
                "properties": {
                    "ppt_path": {
                        "type": "string",
                        "description": "PPT 文件的完整路径"
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "图片输出目录（可选，默认为临时目录）"
                    },
                    "dpi": {
                        "type": "integer",
                        "description": "图片 DPI（可选，默认 150，建议 150-300）"
                    }
                },
                "required": ["ppt_path"]
            }
        ),
        Tool(
            name="get_slide_image",
            description="获取指定幻灯片的图片路径。",
            inputSchema={
                "type": "object",
                "properties": {
                    "ppt_path": {
                        "type": "string",
                        "description": "PPT 文件的完整路径"
                    },
                    "slide_number": {
                        "type": "integer",
                        "description": "幻灯片编号（从 1 开始）"
                    },
                    "dpi": {
                        "type": "integer",
                        "description": "图片 DPI（可选，默认 150）"
                    }
                },
                "required": ["ppt_path", "slide_number"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls for PPT rendering."""
    if arguments is None:
        arguments = {}

    try:
        if name == "render_ppt_to_images":
            ppt_path = arguments.get("ppt_path")
            output_dir = arguments.get("output_dir")
            dpi = arguments.get("dpi", 150)

            if not ppt_path:
                return [TextContent(type="text", text="Error: ppt_path is required")]

            # 使用临时目录作为默认输出目录
            if not output_dir:
                output_dir = tempfile.mkdtemp(prefix="ppt_render_")

            # 转换 PPT 为图片
            images = convert_ppt_to_images(ppt_path, output_dir, dpi)

            if images:
                result = {
                    "success": True,
                    "ppt_path": ppt_path,
                    "output_dir": output_dir,
                    "slide_count": len(images),
                    "images": images
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
            else:
                return [TextContent(type="text", text="Error: Failed to convert PPT to images")]

        elif name == "get_slide_image":
            ppt_path = arguments.get("ppt_path")
            slide_number = arguments.get("slide_number")
            dpi = arguments.get("dpi", 150)

            if not ppt_path or not slide_number:
                return [TextContent(type="text", text="Error: ppt_path and slide_number are required")]

            # 使用临时目录
            output_dir = tempfile.mkdtemp(prefix="ppt_render_")

            # 转换 PPT 为图片
            images = convert_ppt_to_images(ppt_path, output_dir, dpi)

            if images and 1 <= slide_number <= len(images):
                slide_image = images[slide_number - 1]  # 转换为 0-based index
                result = {
                    "success": True,
                    "ppt_path": ppt_path,
                    "slide_number": slide_number,
                    "image_path": slide_image
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
            else:
                return [TextContent(type="text", text=f"Error: Slide {slide_number} not found")]

        else:
            return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    """Main entry point for the PPT renderer server."""
    async with stdio_server(server) as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="ppt_renderer",
                server_version="0.1.0",
                capabilities=server.get_capabilities()
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
