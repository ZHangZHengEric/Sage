"""IM Server MCP - Unified bidirectional messaging for all IM platforms.

Supported Platforms:
- Feishu (飞书): WebSocket mode
- DingTalk (钉钉): Stream mode
- WeChat Work (企业微信): Webhook mode
- iMessage (macOS only): Database polling mode

Architecture:
1. All providers use unified SessionManager for state management
2. Single tool 'send_message_through_im' for all operations
3. Persistent session bindings stored in SQLite database
4. Automatic message routing based on session bindings
5. Multi-tenant: Each Sage user can have their own IM configurations
"""

import os
import logging
from typing import Optional, Dict, Any

from mcp.server.fastmcp import FastMCP
from sagents.tool.mcp_tool_base import sage_mcp_tool

from .im_providers import get_im_provider
from .db import get_im_db
from .session_manager import get_session_manager
from .agent_client import get_agent_client
from .service_manager import get_service_manager
from .agent_config import get_agent_im_config, AgentIMConfig, get_default_agent_id

# Constants
logger = logging.getLogger("IMServer")

# ============================================================================
# Automatic Configuration Migration
# ============================================================================

_migration_done: bool = False

async def ensure_config_migrated() -> bool:
    """
    Automatically migrate legacy database configurations to Agent-level JSON files.
    
    This function runs once at startup to ensure smooth transition from old
    global configuration to new per-Agent configuration system.
    
    Migration triggers when:
    1. Default agent has no channel configurations
    2. Legacy database has configurations for DEFAULT_SAGE_USER_ID
    
    Returns:
        True if migration was performed or not needed, False on error
    """
    global _migration_done
    
    if _migration_done:
        return True
    
    try:
        # Check if default agent already has configurations
        default_agent_id = get_default_agent_id()
        agent_config = get_agent_im_config(default_agent_id)
        existing_channels = agent_config.get_all_channels()
        
        if existing_channels:
            logger.info(f"[IM Migration] Default agent already has {len(existing_channels)} channel(s), skipping migration")
            _migration_done = True
            return True
        
        # Check legacy database for configurations
        logger.info("[IM Migration] Checking for legacy configurations...")
        db = get_im_db()
        legacy_configs = db.list_user_configs(DEFAULT_SAGE_USER_ID)
        
        if not legacy_configs:
            logger.info("[IM Migration] No legacy configurations found, starting with empty config")
            _migration_done = True
            return True
        
        logger.info(f"[IM Migration] Found {len(legacy_configs)} legacy configuration(s), migrating...")
        
        # Perform migration
        migrated_count = 0
        skipped_count = 0
        
        for config in legacy_configs:
            provider = config.get("provider")
            enabled = config.get("enabled", False)
            provider_config = config.get("config", {})
            
            # Validate (especially for iMessage)
            # Skip iMessage migration - it should only be on default agent
            if provider == "imessage":
                logger.warning(f"[IM Migration] Skipping iMessage for migration - configure it manually on default agent")
                skipped_count += 1
                continue
                skipped_count += 1
                continue
            
            # Save to new format
            try:
                success = agent_config.set_provider_config(provider, enabled, provider_config)
                if success:
                    logger.info(f"[IM Migration] ✓ Migrated: {provider} (enabled={enabled})")
                    migrated_count += 1
                else:
                    logger.error(f"[IM Migration] ✗ Failed to migrate: {provider}")
            except Exception as e:
                logger.error(f"[IM Migration] ✗ Error migrating {provider}: {e}")
                skipped_count += 1
        
        logger.info(f"[IM Migration] Complete: {migrated_count} migrated, {skipped_count} skipped")
        _migration_done = True
        return True
        
    except Exception as e:
        logger.error(f"[IM Migration] Migration failed: {e}", exc_info=True)
        # Don't block startup on migration failure
        return True


# Run migration on module load (for immediate config availability)
import asyncio

# Try to run migration synchronously first
# (will run again async if this fails)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Initialize FastMCP server
mcp = FastMCP("IM Service")

# Default Sage user ID for desktop app
DEFAULT_SAGE_USER_ID = "desktop_default_user"


# ============================================================================
# File Tools Implementation
# ============================================================================

async def _send_file_via_provider(
    file_path: str,
    provider: str,
    agent_id: Optional[str] = None,
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    file_type: str = "file"
) -> str:
    """
    Internal function: Send file via specified Provider.
    内部函数：通过指定 Provider 发送文件
    
    Args:
        file_path: Local file path / 本地文件路径
        provider: Platform name (wechat_work, feishu, dingtalk) / 平台名称
        agent_id: Agent ID for configuration lookup / Agent 标识符
        user_id: User ID / 用户 ID
        chat_id: Chat/Group ID / 群聊 ID
        file_type: File type (file/image) / 文件类型
        
    Returns:
        Result message / 结果消息
    """
    # Validate file / 验证文件
    if not os.path.exists(file_path):
        return f"错误: 文件不存在 - {file_path}"
    
    if not os.path.isfile(file_path):
        return f"错误: 路径不是文件 - {file_path}"
    
    # Check file size (WeChat Work limit 20MB) / 检查文件大小
    file_size = os.path.getsize(file_path)
    max_size = 20 * 1024 * 1024  # 20MB
    if file_size > max_size:
        return f"错误: 文件大小 {file_size / 1024 / 1024:.2f}MB 超过限制 (20MB)"
    
    logger.info(f"[_send_file_via_provider] agent={agent_id}, provider={provider}, file={file_path}, size={file_size}")
    
    # Get Provider configuration from Agent config / 从 Agent 配置获取 Provider 配置
    agent_config = get_agent_im_config(agent_id)
    config = agent_config.get_provider_config(provider)
    
    if not config:
        logger.error(f"[_send_file_via_provider] {provider} not enabled or not configured for agent={agent_id}")
        return f"错误: {provider} 未启用或未配置 (agent={agent_id})"
    
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
            # 飞书
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
        elif provider == "dingtalk":
            # 钉钉
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


@mcp.tool()
@sage_mcp_tool(server_name="IM Service")
async def send_file_through_im(
    file_path: str,
    provider: str,
    agent_id: str,
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> str:
    """
    Send file to IM user. Supports WeChat Work, DingTalk, Feishu.
    发送文件给 IM 用户 (支持企业微信、钉钉、飞书)
    
    Send local files to specified user or group chat.
    将本地文件发送给指定用户或群聊。
    
    **重要**: agent_id 是必填参数，必须使用当前对话关联的 Agent ID。
    系统提示中已提供正确的 agent_id，请直接使用，不要省略或使用其他值。
    
    Args:
        file_path: Local file path (e.g., "/path/to/document.pdf") / 本地文件路径
        provider: Platform name - wechat_work, feishu, dingtalk / 
                 平台名称 - wechat_work(企业微信)、feishu(飞书)、dingtalk(钉钉)
        agent_id: **必填** Agent ID for configuration lookup. Must use the current agent ID from system prompt. / 
                 **必填** Agent 标识符，必须使用系统提示中提供的当前 Agent ID。
        user_id: User ID for private chat (optional, either user_id or chat_id required) / 
                用户ID（私聊选填，user_id 和 chat_id 至少提供一个）
        chat_id: Chat/Group ID for group chat (optional, either user_id or chat_id required) / 
                群聊ID（群聊选填，user_id 和 chat_id 至少提供一个）
    
    Examples:
        >>> send_file_through_im(
        ...     file_path="/tmp/report.pdf",
        ...     provider="dingtalk",
        ...     agent_id="agent_5e6b9f59",  # 使用系统提示中的 agent_id
        ...     user_id="userid_xxx"
        ... )
        "✅ 文件已发送给 user userid_xxx"
    
    Limits:
        - File size max 20MB
        - Supported formats: documents, images, audio, video, etc.
    """
    # Validate agent_id is provided
    if not agent_id:
        logger.error("[IM Tool] send_file_through_im: agent_id is required but not provided")
        return "错误: agent_id 是必填参数，请使用系统提示中提供的 agent_id"
    
    logger.info(f"[IM Tool] send_file_through_im called: agent={agent_id}, provider={provider}, file={file_path}")
    
    # Validate parameters
    if not file_path:
        return "错误: file_path 不能为空"
    
    if not provider:
        return "错误: provider 不能为空"
    
    if not user_id and not chat_id:
        return "错误: user_id 和 chat_id 至少提供一个"
    
    return await _send_file_via_provider(
        file_path=file_path,
        provider=provider,
        agent_id=agent_id,
        user_id=user_id,
        chat_id=chat_id,
        file_type="file"
    )


@mcp.tool()
@sage_mcp_tool(server_name="IM Service")
async def send_image_through_im(
    file_path: str,
    provider: str,
    agent_id: str,
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> str:
    """
    Send image to IM user. Supports WeChat Work, DingTalk, Feishu.
    发送图片给 IM 用户 (支持企业微信、钉钉、飞书)
    
    Send local image to specified user or group. Images display as image messages.
    将本地图片发送给指定用户或群聊。图片会以图片消息形式显示。
    
    **重要**: agent_id 是必填参数，必须使用当前对话关联的 Agent ID。
    系统提示中已提供正确的 agent_id，请直接使用，不要省略或使用其他值。
    
    Args:
        file_path: Local image path (e.g., "/path/to/image.png") / 本地图片路径
        provider: Platform name - wechat_work, dingtalk, feishu / 
                 平台名称 - wechat_work(企业微信)、dingtalk(钉钉)、feishu(飞书)
        agent_id: **必填** Agent ID for configuration lookup. Must use the current agent ID from system prompt. / 
                 **必填** Agent 标识符，必须使用系统提示中提供的当前 Agent ID。
        user_id: User ID for private chat (optional, either user_id or chat_id required) / 
                用户ID（私聊选填，user_id 和 chat_id 至少提供一个）
        chat_id: Chat/Group ID for group chat (optional, either user_id or chat_id required) / 
                群聊ID（群聊选填，user_id 和 chat_id 至少提供一个）
    
    Examples:
        >>> send_image_through_im(
        ...     file_path="/tmp/photo.jpg",
        ...     provider="dingtalk",
        ...     agent_id="agent_5e6b9f59",  # 使用系统提示中的 agent_id
        ...     user_id="userid_xxx"
        ... )
    
    Limits:
        - Image size max 20MB
        - Supported formats: JPG, PNG, GIF, BMP, WebP
    """
    # Validate agent_id is provided
    if not agent_id:
        logger.error("[IM Tool] send_image_through_im: agent_id is required but not provided")
        return "错误: agent_id 是必填参数，请使用系统提示中提供的 agent_id"
    
    logger.info(f"[IM Tool] send_image_through_im called: agent={agent_id}, provider={provider}, image={file_path}")
    
    # Validate parameters
    if not file_path:
        return "错误: file_path 不能为空"
    
    if not provider:
        return "错误: provider 不能为空"
    
    if not user_id and not chat_id:
        return "错误: user_id 和 chat_id 至少提供一个"
    
    # Validate image format
    valid_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
    if not file_path.lower().endswith(valid_extensions):
        return f"错误: 不支持的图片格式，请使用: {', '.join(valid_extensions)}"
    
    return await _send_file_via_provider(
        file_path=file_path,
        provider=provider,
        agent_id=agent_id,
        user_id=user_id,
        chat_id=chat_id,
        file_type="image"
    )


logger.info("[IM Server] File tools registered")


def is_provider_enabled(provider: str, agent_id: Optional[str] = None) -> bool:
    """
    Check if a provider is enabled for an Agent.
    
    Args:
        provider: Provider type (wechat_work, dingtalk, etc.)
        agent_id: Agent identifier (default: uses database default agent)
        
    Returns:
        True if provider is enabled for this Agent.
    """
    if not agent_id:
        agent_id = get_default_agent_id()
    config = get_agent_im_config(agent_id)
    enabled = config.is_provider_enabled(provider)
    logger.info(f"[IM Tool] Checking provider {provider} for agent={agent_id}: enabled={enabled}")
    return enabled


def get_provider_config(provider: str, agent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get provider configuration for an Agent.
    
    Args:
        provider: Provider type (wechat_work, dingtalk, etc.)
        agent_id: Agent identifier (default: uses database default agent)
        
    Returns:
        Provider configuration dict, or None if not configured/disabled.
    """
    if not agent_id:
        agent_id = get_default_agent_id()
    config = get_agent_im_config(agent_id)
    provider_config = config.get_provider_config(provider)
    if provider_config:
        logger.info(f"[IM Tool] Got config for provider={provider}, agent={agent_id}")
    else:
        logger.warning(f"[IM Tool] No config found for provider={provider}, agent={agent_id}")
    return provider_config


async def _send_message_to_agent(
    session_id: str,
    agent_id: str,
    content: str,
    user_id: str = "im_user",
    provider: str = "unknown",
    user_name: Optional[str] = None,
    file_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Send a message to agent and get response."""
    client = get_agent_client()
    return await client.send_message(
        session_id=session_id,
        agent_id=agent_id,
        content=content,
        user_id=user_id,
        user_name=user_name,
        provider=provider,
        file_info=file_info
    )


@mcp.tool()
@sage_mcp_tool(server_name="IM Service")
async def send_message_through_im(
    content: str,
    provider: str,
    agent_id: str,
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> str:
    """
    Send message to IM user. Supports Feishu, DingTalk, WeChat Work, iMessage.
    
    向 IM 用户发送消息。支持飞书、钉钉、企业微信、iMessage。

    **重要**: agent_id 是必填参数，必须使用当前对话关联的 Agent ID。
    系统提示中已提供正确的 agent_id，请直接使用，不要省略或使用其他值。

    Args:
        content: Message content / 消息内容
        provider: Platform name - feishu, dingtalk, wechat_work, imessage / 
                 平台名称 - feishu(飞书)、dingtalk(钉钉)、wechat_work(企业微信)、imessage
        agent_id: **必填** Agent ID for configuration lookup. Must use the current agent ID from system prompt. / 
                 **必填** Agent 标识符，必须使用系统提示中提供的当前 Agent ID。
        user_id: User ID for private chat (optional, either user_id or chat_id required) / 
                用户ID（私聊选填，user_id 和 chat_id 至少提供一个）
        chat_id: Chat/Group ID for group messages (optional, either user_id or chat_id required) / 
                群聊ID（群聊选填，user_id 和 chat_id 至少提供一个）

    Returns:
        Success message or error description / 成功消息或错误描述

    Examples:
        >>> send_message_through_im(
        ...     content="Hello",
        ...     provider="dingtalk",
        ...     agent_id="agent_5e6b9f59",  # 使用系统提示中的 agent_id
        ...     user_id="userid_xxx"
        ... )
        "Message sent via dingtalk to user userid_xxx"
    """
    # Validate agent_id is provided
    if not agent_id:
        logger.error("[IM Tool] send_message_through_im: agent_id is required but not provided")
        return "错误: agent_id 是必填参数，请使用系统提示中提供的 agent_id"
    
    logger.info(f"[IM Tool] send_message_through_im called: agent={agent_id}, provider={provider}, "
                f"user_id={user_id}, chat_id={chat_id}, content_length={len(content) if content else 0}")

    # Validate required parameters
    if not content:
        logger.warning("[IM Tool] Error: content is required")
        return "Error: content is required"

    if not provider:
        logger.warning("[IM Tool] Error: provider is required")
        return "Error: provider is required"

    if not user_id and not chat_id:
        logger.warning("[IM Tool] Error: either user_id or chat_id is required")
        return "Error: either user_id or chat_id is required"

    # Use provided parameters directly
    provider_name = provider
    target_user_id = user_id
    target_chat_id = chat_id

    # If chat_id not provided, try to find it from session manager
    if not target_chat_id and target_user_id:
        try:
            session_mgr = get_session_manager()
            # Try to find session by user
            session_id = session_mgr.find_session_by_user(provider_name, target_user_id)
            if session_id:
                binding = session_mgr.get_binding(session_id)
                if binding:
                    target_chat_id = binding.get('chat_id')
                    logger.info(f"[IM Tool] Found chat_id from session: {target_chat_id}")
        except Exception as e:
            logger.warning(f"[IM Tool] Failed to find chat_id from session: {e}")

    logger.info(f"[IM Tool] Processing message: agent={agent_id}, provider={provider_name}, "
                f"user_id={target_user_id}, chat_id={target_chat_id}")

    # Check if provider is enabled for this agent
    logger.info(f"[IM Tool] Checking if provider {provider_name} is enabled for agent={agent_id}...")
    if not is_provider_enabled(provider_name, agent_id):
        logger.error(f"[IM Tool] Provider '{provider_name}' is not enabled for agent={agent_id}")
        return f"Error: Provider '{provider_name}' is not enabled for this agent"

    logger.info(f"[IM Tool] Provider {provider_name} is enabled, getting config...")

    # Get provider config and instance
    try:
        config = get_provider_config(provider_name, agent_id)
        logger.info(f"[IM Tool] Got provider config for agent={agent_id}: {config}")
        if not config:
            logger.error(f"[IM Tool] No configuration found for provider '{provider_name}' and agent '{agent_id}'")
            return f"Error: No configuration found for provider '{provider_name}'"

        logger.info(f"[IM Tool] Creating provider instance for {provider_name}...")
        provider_instance = get_im_provider(provider_name, config)
        logger.info("[IM Tool] Provider instance created, sending message...")

        # WeChat Work aibot_send_msg only supports markdown, others support text
        msg_type = "markdown" if provider_name == "wechat_work" else "text"
        result = await provider_instance.send_message(
            content=content,
            chat_id=target_chat_id,
            user_id=target_user_id,
            msg_type=msg_type
        )

        logger.info(f"[IM Tool] send_message result: {result}")

        if result.get("success"):
            target = f"group {target_chat_id}" if target_chat_id else f"user {target_user_id}"
            logger.info(f"[IM Tool] Message sent successfully to {target}")
            return f"Message sent via {provider_name} to {target}"
        else:
            error = result.get('error', 'Unknown error')
            logger.error(f"[IM Tool] Failed to send message: {error}")
            return f"Error: {error}"

    except Exception as e:
        logger.error(f"[IM Tool] Exception sending message: {e}", exc_info=True)
        return f"Error sending message: {str(e)}"


# --- Default Agent Resolution ---

# Note: get_default_agent_id() is imported from agent_config module
# which queries the database directly for is_default=True
# No caching needed - database is the single source of truth


# --- Incoming Message Handlers ---


async def handle_incoming_message(
    provider: str,
    user_id: str,
    content: str,
    chat_id: Optional[str] = None,
    user_name: Optional[str] = None,
    default_agent_id: Optional[str] = None,
    session_webhook: Optional[str] = None,
    sender_staff_id: Optional[str] = None,
    session_webhook_expired_time: Optional[int] = None,
    file_info: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Handle incoming message from any IM provider.

    This function should be called by ServiceManager when messages are received.

    Args:
        provider: IM provider name
        user_id: User ID in the IM platform
        content: Message content
        chat_id: Chat/Group ID (optional)
        user_name: Display name (optional)
        default_agent_id: Default agent to route to (optional, auto-detected if not provided)
        session_webhook: DingTalk session webhook (optional)
        sender_staff_id: DingTalk sender staff ID (optional)
        session_webhook_expired_time: DingTalk webhook expiry (optional)
        file_info: File information dict (optional) - {name, size, mime_type, local_path}

    Returns:
        Dict with success status and session_id
    """
    # Get default agent ID if not provided
    if default_agent_id is None:
        default_agent_id = await get_default_agent_id()

    session_mgr = get_session_manager()

    # Find or create session
    session_id = session_mgr.find_or_create_session(
        provider=provider,
        user_id=user_id,
        agent_id=default_agent_id,
        chat_id=chat_id,
        user_name=user_name
    )

    # Send to agent
    result = await _send_message_to_agent(
        session_id=session_id,
        agent_id=default_agent_id,
        content=content,
        user_id=user_id,
        provider=provider,
        user_name=user_name,
        file_info=file_info
    )

    if result.get("success"):
        # Send response back via IM
        response = result.get("response", "")
        has_im_tool = result.get("has_im_tool", False)

        logger.info(f"[IM] Agent response: success=True, has_im_tool={has_im_tool}, response_length={len(response) if response else 0}")
        logger.info(f"[IM] Response content preview: {response[:200] if response else 'EMPTY'}...")

        if has_im_tool:
            logger.info("[IM] Agent used send_message_through_im tool, skipping automatic response")
        elif response:
            try:
                binding = session_mgr.get_binding(session_id)
                logger.info(f"[IM] Sending response back to {provider}: chat_id={chat_id}, user_id={user_id}")

                if binding:
                    # 首先尝试从 service_manager 获取正在运行的 provider（复用现有连接）
                    from .service_manager import get_service_manager
                    sm = get_service_manager()
                    
                    # 通过 agent_id + provider 查找正在运行的 provider (新架构)
                    logger.info(f"[IM] Looking for provider instance: agent={default_agent_id}, provider={provider}")
                    provider_instance = sm.find_provider_by_agent(default_agent_id, provider)
                    
                    if provider_instance:
                        logger.info(f"[IM] Reusing existing provider connection for agent={default_agent_id}, provider={provider}")
                    else:
                        # 如果没有运行的 provider，创建新实例
                        logger.warning(f"[IM] No running provider for agent={default_agent_id}, provider={provider}, creating new instance")
                        config = get_provider_config(provider, default_agent_id)
                        logger.info(f"[IM] Provider config for agent={default_agent_id}: {config}")
                        if config:
                            provider_instance = get_im_provider(provider, config)
                            logger.info(f"[IM] Created new provider instance: {provider_instance}")
                        else:
                            logger.error(f"[IM] No config found for agent={default_agent_id}, provider: {provider}")
                            return {"success": True, "session_id": session_id}

                    logger.info(f"[IM] Calling {provider}.send_message with content length: {len(response)}, chat_id={chat_id}, user_id={user_id}")

                    # Prepare send parameters
                    send_params = {
                        "content": response,
                        "chat_id": chat_id,
                        "user_id": user_id,
                    }

                    # Add session_webhook for DingTalk (if available)
                    if provider == "dingtalk":
                        # Default to text for DingTalk (markdown may cause display issues)
                        send_params["msg_type"] = "text"
                        if session_webhook:
                            send_params["session_webhook"] = session_webhook
                        if sender_staff_id:
                            send_params["sender_staff_id"] = sender_staff_id
                        if session_webhook_expired_time:
                            send_params["session_webhook_expired_time"] = session_webhook_expired_time
                    elif provider == "wechat_work":
                        # WeChat Work aibot_send_msg only supports markdown/template_card
                        send_params["msg_type"] = "markdown"
                    else:
                        # Other providers use text by default
                        send_params["msg_type"] = "text"

                    send_result = await provider_instance.send_message(**send_params)
                    logger.info(f"[IM] send_message result: {send_result}")
                else:
                    logger.error(f"[IM] No binding found for session: {session_id}")
            except Exception as e:
                logger.error(f"[IM] Failed to send response back: {e}", exc_info=True)
        else:
            logger.warning("[IM] Agent returned empty response")

        return {"success": True, "session_id": session_id}
    else:
        return {"success": False, "error": result.get("error")}


# --- Server Initialization ---


async def initialize_im_server():
    """Initialize IM server and start Service Manager."""
    logger.info("=" * 50)
    logger.info("[IM Server] ========== Initializing IM Server ==========")
    logger.info("=" * 50)
    
    # Step 1: Migrate legacy configurations (if needed)
    logger.info("[IM Server] Checking configuration migration...")
    migration_success = await ensure_config_migrated()
    if not migration_success:
        logger.warning("[IM Server] Configuration migration had issues, continuing with startup")
    
    # Step 2: Start service manager for multi-tenant IM management
    logger.info("[IM Server] Starting Service Manager...")
    service_manager = get_service_manager()
    await service_manager.start()
    logger.info("[IM Server] Service Manager started")

    logger.info("[IM Server] ========== IM Server Initialized ==========")
    logger.info("=" * 50)


async def reload_im_server():
    """Reload IM server configuration and restart if needed.

    This function is called when configuration is updated via API.
    """
    logger.info("[IM Server] ========== Reloading IM Server ==========")

    # Stop service manager
    service_manager = get_service_manager()
    await service_manager.stop()
    logger.info("[IM Server] Service Manager stopped")

    # Re-initialize
    await initialize_im_server()

    logger.info("[IM Server] ========== IM Server Reloaded ==========")


# Note: This module is imported by ToolManager, not run directly
# The initialize_im_server() should be called by the main application
# when it starts up, not here.

# Example usage in main application:
# from mcp_servers.im_server.im_server import initialize_im_server
# asyncio.create_task(initialize_im_server())
