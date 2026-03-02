"""Configuration management for IM Server.

TODO: This module will fetch IM configurations from backend API.
For now, it uses environment variables and local cache.
"""

import os
import json
from typing import Optional, Dict, Any

# TODO: Uncomment when implementing backend API integration
# import httpx

# TODO: Replace with actual backend API endpoint when available
# BACKEND_API_BASE = os.getenv("SAGE_BACKEND_API", "http://localhost:8080/api")

# Cache for IM configurations
_config_cache: Dict[str, Dict[str, Any]] = {}


def _get_api_base_url() -> str:
    """Get the API base URL for the Sage server."""
    port = os.getenv("SAGE_PORT", "8080")
    return f"http://localhost:{port}"


async def fetch_im_config_from_backend(provider: str) -> Optional[Dict[str, Any]]:
    """
    Fetch IM configuration from backend API.

    TODO: Implement this when backend API is ready.
    Expected API response format:
    {
        "provider": "feishu",
        "app_id": "cli_xxx",
        "app_secret": "xxx",
        "webhook_url": "https://open.feishu.cn/xxx",  # Optional
        "access_token": "xxx",  # Optional
        "extra_config": {}  # Optional
    }

    For Feishu/DingTalk WebSocket mode:
    - app_id: App ID / Client ID
    - app_secret: App Secret / Client Secret

    For Webhook mode (any platform):
    - webhook_url: The webhook URL to send messages
    - app_secret: For signature verification (optional)

    Args:
        provider: IM provider name (feishu, dingtalk, wechat_work)

    Returns:
        Configuration dict or None if not found
    """
    # TODO: Uncomment and implement when backend API is ready
    # api_base_url = _get_api_base_url()
    # try:
    #     async with httpx.AsyncClient(timeout=10.0) as client:
    #         resp = await client.get(
    #             f"{api_base_url}/api/v1/im/config/{provider}",
    #             headers={"Authorization": f"Bearer {get_auth_token()}"}
    #         )
    #         if resp.status_code == 200:
    #             return resp.json()
    # except Exception as e:
    #     logger.error(f"Failed to fetch IM config from backend: {e}")

    # Fallback: Try environment variables
    env_prefix = f"IM_{provider.upper()}_"
    config = {}

    app_id = os.getenv(f"{env_prefix}APP_ID")
    app_secret = os.getenv(f"{env_prefix}APP_SECRET")
    webhook_url = os.getenv(f"{env_prefix}WEBHOOK_URL")
    access_token = os.getenv(f"{env_prefix}ACCESS_TOKEN")

    if app_id:
        config["app_id"] = app_id
    if app_secret:
        config["app_secret"] = app_secret
    if webhook_url:
        config["webhook_url"] = webhook_url
    if access_token:
        config["access_token"] = access_token

    # Parse extra config from env if present
    extra_config = os.getenv(f"{env_prefix}EXTRA_CONFIG")
    if extra_config:
        try:
            config["extra_config"] = json.loads(extra_config)
        except json.JSONDecodeError:
            pass

    return config if config else None


def get_im_config(provider: str) -> Optional[Dict[str, Any]]:
    """Get IM configuration for a provider (from cache or fetch)."""
    # TODO: This is a sync wrapper, consider making it async
    # when backend API is implemented
    return _config_cache.get(provider)


async def load_im_config(provider: str) -> Optional[Dict[str, Any]]:
    """Load and cache IM configuration for a provider."""
    config = await fetch_im_config_from_backend(provider)
    if config:
        _config_cache[provider] = config
    return config


def clear_config_cache():
    """Clear the configuration cache."""
    _config_cache.clear()


def get_cached_providers() -> list:
    """Get list of providers with cached configurations."""
    return list(_config_cache.keys())
