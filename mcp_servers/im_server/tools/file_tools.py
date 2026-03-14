"""IM file tools for MCP server.

企业微信文件相关 MCP 工具
"""

import os
import logging
from typing import Optional, Dict, Any

from mcp.server.fastmcp import FastMCP
from sagents.tool.mcp_tool_base import sage_mcp_tool

# Import IM providers
from ..im_providers import get_im_provider

logger = logging.getLogger("IMFileTools")


async def _send_file_via_provider(
    file_path: str,
    provider: str,
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    file_type: str = "file"
) -> str:
    """内部函数：通过指定 Provider 发送文件
    
    Args:
        file_path: 本地文件路径
        provider: 平台名称 (wechat_work, feishu, dingtalk)
        user_id: 用户 ID
        chat_id: 群聊 ID
        file_type: 文件类型 (file/image)
        
    Returns:
        结果消息
    """
    # 验证文件
    if not os.path.exists(file_path):
        return f"错误: 文件不存在 - {file_path}"
    
    if not os.path.isfile(file_path):
        return f"错误: 路径不是文件 - {file_path}"
    
    # 检查文件大小 (企业微信限制 20MB)
    file_size = os.path.getsize(file_path)
    max_size = 20 * 1024 * 1024  # 20MB
    if file_size > max_size:
        return f"错误: 文件大小 {file_size / 1024 / 1024:.2f}MB 超过限制 (20MB)"
    
    logger.info(f"[_send_file_via_provider] {provider}, file={file_path}, size={file_size}")
    
    # 获取 Provider 配置
    from ..db import get_im_db
    db = get_im_db()
    
    # 使用默认用户 ID
    from ..im_server import DEFAULT_SAGE_USER_ID
    config_data = db.get_user_config(DEFAULT_SAGE_USER_ID, provider)
    
    if not config_data or not config_data.get("enabled"):
        return f"错误: {provider} 未启用或未配置"
    
    config = config_data.get("config", {})
    
    try:
        # 获取 Provider 实例
        provider_instance = get_im_provider(provider, config)
        
        # 根据 Provider 类型调用不同方法
        if provider == "wechat_work":
            # 企业微信
            if file_type == "image":
                result = await provider_instance.send_image(
                    image_path=file_path,
                    chat_id=chat_id,
                    user_id=user_id
                )
            else:
                result = await provider_instance.send_file(
                    file_path=file_path,
                    chat_id=chat_id,
                    user_id=user_id
                )
        elif provider == "feishu":
            # 飞书 (暂不支持文件，返回提示)
            return f"飞书文件发送功能开发中，请使用企业微信发送文件"
        elif provider == "dingtalk":
            # 钉钉 (暂不支持文件，返回提示)
            return f"钉钉文件发送功能开发中，请使用企业微信发送文件"
        else:
            return f"错误: 不支持的 Provider - {provider}"
        
        # 处理结果
        if result.get("success"):
            target = f"群聊 {chat_id}" if chat_id else f"用户 {user_id}"
            logger.info(f"[_send_file_via_provider] 文件发送成功: {target}")
            return f"✅ 文件已发送给 {target}"
        else:
            error = result.get("error", "未知错误")
            logger.error(f"[_send_file_via_provider] 发送失败: {error}")
            return f"❌ 发送失败: {error}"
            
    except Exception as e:
        logger.error(f"[_send_file_via_provider] 异常: {e}", exc_info=True)
        return f"错误: {str(e)}"


def register_file_tools(mcp: FastMCP):
    """注册文件相关 MCP 工具
    
    Args:
        mcp: FastMCP 实例
    """
    
    @mcp.tool()
    @sage_mcp_tool(server_name="IM Service")
    async def send_file_through_im(
        file_path: str,
        provider: str,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> str:
        """发送文件给 IM 用户 (支持企业微信)
        
        将本地文件发送给指定用户或群聊。目前仅支持企业微信，其他平台开发中。
        
        参数:
            file_path: 本地文件路径 (如 "/path/to/document.pdf")
            provider: 平台名称 - wechat_work(企业微信)、feishu(飞书)、dingtalk(钉钉)
            user_id: 用户ID（私聊必填）- 企业微信:user_id
            chat_id: 群聊ID（群聊必填）- 企业微信:chat_id
        
        示例:
            send_file_through_im(provider="wechat_work", user_id="userid_xxx", file_path="/tmp/report.pdf")
            send_file_through_im(provider="wechat_work", chat_id="chat_xxx", file_path="/tmp/image.png")
        
        限制:
            - 文件大小不超过 20MB
            - 支持的格式: 文档、图片、音频、视频等
        """
        logger.info(f"[IM Tool] send_file_through_im called: provider={provider}, file={file_path}")
        
        # 验证参数
        if not file_path:
            return "错误: file_path 不能为空"
        
        if not provider:
            return "错误: provider 不能为空"
        
        if not user_id and not chat_id:
            return "错误: user_id 和 chat_id 至少提供一个"
        
        return await _send_file_via_provider(
            file_path=file_path,
            provider=provider,
            user_id=user_id,
            chat_id=chat_id,
            file_type="file"
        )
    
    @mcp.tool()
    @sage_mcp_tool(server_name="IM Service")
    async def send_image_through_im(
        file_path: str,
        provider: str,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> str:
        """发送图片给 IM 用户 (支持企业微信)
        
        将本地图片发送给指定用户或群聊。图片会以图片消息形式显示。
        
        参数:
            file_path: 本地图片路径 (如 "/path/to/image.png")
            provider: 平台名称 - wechat_work(企业微信)
            user_id: 用户ID（私聊必填）
            chat_id: 群聊ID（群聊必填）
        
        示例:
            send_image_through_im(provider="wechat_work", user_id="userid_xxx", file_path="/tmp/photo.jpg")
        
        限制:
            - 图片大小不超过 20MB
            - 支持的格式: JPG, PNG, GIF
        """
        logger.info(f"[IM Tool] send_image_through_im called: provider={provider}, image={file_path}")
        
        # 验证参数
        if not file_path:
            return "错误: file_path 不能为空"
        
        if not provider:
            return "错误: provider 不能为空"
        
        if not user_id and not chat_id:
            return "错误: user_id 和 chat_id 至少提供一个"
        
        # 验证图片格式
        valid_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
        if not file_path.lower().endswith(valid_extensions):
            return f"错误: 不支持的图片格式，请使用: {', '.join(valid_extensions)}"
        
        return await _send_file_via_provider(
            file_path=file_path,
            provider=provider,
            user_id=user_id,
            chat_id=chat_id,
            file_type="image"
        )
    
    logger.info("[IMFileTools] File tools registered successfully")
