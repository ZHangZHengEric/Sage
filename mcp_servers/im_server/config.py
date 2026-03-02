"""Configuration management for IM Server.

Fetches complete IM configuration from backend API.
Configuration includes all providers and their settings.
"""

import os
import json
import logging
from typing import Optional, Dict, Any
from pathlib import Path

# TODO: Uncomment when implementing backend API integration
# import httpx

logger = logging.getLogger("IMConfig")

# Cache for complete IM configuration
_im_config: Optional[Dict[str, Any]] = None

# Default config file path (for local development)
DEFAULT_CONFIG_PATH = Path.home() / ".sage" / "im_config.json"


def _get_api_base_url() -> str:
    """Get the API base URL for the Sage server."""
    port = os.getenv("SAGE_PORT", "8080")
    return f"http://localhost:{port}"


async def fetch_im_config_from_backend() -> Optional[Dict[str, Any]]:
    """
    Fetch complete IM configuration from backend API.

    Expected API response format:

        {
            "im_providers": {
                "feishu": {
                    "enabled": true,
                    "app_id": "cli_xxx",
                    "app_secret": "xxx"
                },
                "dingtalk": {
                    "enabled": true,
                    "client_id": "dingxxx",
                    "client_secret": "xxx"
                },
                "imessage": {
                    "enabled": true,
                    "mode": "database_poll",
                    "allowed_senders": ["+86138xxxxxxxx", "18910982928"]
                }
            },
            "settings": {
                "default_timeout": 300,
                "max_message_length": 4096
            }
        }

    Field descriptions:

    - enabled: Whether this provider is active
    - app_id: (Feishu) Application identifier
    - app_secret: (Feishu) Application secret
    - client_id: (DingTalk) Application identifier (same as app_key)
    - client_secret: (DingTalk) Application secret (same as app_secret)
    - mode: (iMessage only) "database_poll" or "notification"
    - allowed_senders: (iMessage only) Whitelist of phone numbers/emails

    Notes:
        - Feishu uses WebSocket mode (no webhook_url needed)
        - DingTalk uses Stream mode (no webhook_url needed)
        - iMessage works locally without any external URL

    Returns:
        Complete IM configuration dict or None if not found
    """
    # TODO: Implement when backend API is ready
    # api_base_url = _get_api_base_url()
    # try:
    #     async with httpx.AsyncClient(timeout=10.0) as client:
    #         resp = await client.get(
    #             f"{api_base_url}/api/v1/im/config",
    #             headers={"Authorization": f"Bearer {get_auth_token()}"}
    #         )
    #         if resp.status_code == 200:
    #             config = resp.json()
    #             _save_local_config(config)  # Cache locally
    #             return config
    # except Exception as e:
    #     logger.error(f"Failed to fetch IM config from backend: {e}")

    # Fallback: Try local config file
    return _load_local_config()


def _load_local_config() -> Optional[Dict[str, Any]]:
    """Load configuration from local file."""
    try:
        if DEFAULT_CONFIG_PATH.exists():
            with open(DEFAULT_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load local config: {e}")
    return None


def _save_local_config(config: Dict[str, Any]):
    """Save configuration to local file."""
    try:
        DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DEFAULT_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Failed to save local config: {e}")


def _load_from_env() -> Dict[str, Any]:
    """Load configuration from environment variables."""
    config = {
        "im_providers": {},
        "settings": {
            "default_timeout": 300,
            "max_message_length": 4096
        }
    }

    providers = ["feishu", "dingtalk", "imessage"]

    for provider in providers:
        env_prefix = f"IM_{provider.upper()}_"
        provider_config = {"enabled": False}

        # Check if enabled
        enabled = os.getenv(f"{env_prefix}ENABLED", "false").lower() == "true"
        if not enabled:
            continue

        provider_config["enabled"] = True

        # Common fields
        app_id = os.getenv(f"{env_prefix}APP_ID")
        app_secret = os.getenv(f"{env_prefix}APP_SECRET")
        webhook_url = os.getenv(f"{env_prefix}WEBHOOK_URL")

        if app_id:
            provider_config["app_id"] = app_id
        if app_secret:
            provider_config["app_secret"] = app_secret
        if webhook_url:
            provider_config["webhook_url"] = webhook_url

        # Provider-specific fields
        if provider == "feishu":
            for key in ["encrypt_key", "verification_token"]:
                value = os.getenv(f"{env_prefix}{key.upper()}")
                if value:
                    provider_config[key] = value

        elif provider == "dingtalk":
            app_key = os.getenv(f"{env_prefix}APP_KEY")
            if app_key:
                provider_config["app_key"] = app_key

        elif provider == "imessage":
            mode = os.getenv(f"{env_prefix}MODE", "database_poll")
            provider_config["mode"] = mode
            
            # Parse allowed_senders from env
            allowed_senders = os.getenv(f"{env_prefix}ALLOWED_SENDERS")
            if allowed_senders:
                try:
                    provider_config["allowed_senders"] = json.loads(allowed_senders)
                except json.JSONDecodeError:
                    pass

        # Parse extra config from env if present
        extra_config = os.getenv(f"{env_prefix}EXTRA_CONFIG")
        if extra_config:
            try:
                provider_config["extra_config"] = json.loads(extra_config)
            except json.JSONDecodeError:
                pass

        config["im_providers"][provider] = provider_config

    return config


async def load_im_config() -> Optional[Dict[str, Any]]:
    """
    Load complete IM configuration.

    Tries in order:
    1. Backend API
    2. Local config file
    3. Environment variables

    Returns:
        Complete IM configuration or None
    """
    global _im_config

    # Try backend API first
    config = await fetch_im_config_from_backend()
    if config:
        _im_config = config
        return config

    # Try environment variables
    config = _load_from_env()
    if config.get("im_providers"):
        _im_config = config
        _save_local_config(config)  # Cache for next time
        return config

    return None


def get_im_config(provider: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get IM configuration.

    Args:
        provider: Provider name (feishu, dingtalk, wechat_work, imessage)
                 If None, returns complete config

    Returns:
        Provider config or complete config
    """
    if _im_config is None:
        return None

    if provider:
        providers = _im_config.get("im_providers", {})
        return providers.get(provider)

    return _im_config


def get_provider_webhook_url(provider: str) -> Optional[str]:
    """
    Get webhook URL for a specific provider.

    Each provider has its own webhook URL configured individually.

    Args:
        provider: Provider name

    Returns:
        Webhook URL or None
    """
    config = get_im_config(provider)
    if config:
        return config.get("webhook_url")
    return None


def is_provider_enabled(provider: str) -> bool:
    """Check if a provider is enabled."""
    config = get_im_config(provider)
    if config:
        return config.get("enabled", False)
    return False


def list_enabled_providers() -> list:
    """List all enabled providers."""
    if _im_config is None:
        return []

    providers = _im_config.get("im_providers", {})
    return [name for name, config in providers.items() if config.get("enabled", False)]


def clear_config_cache():
    """Clear the configuration cache."""
    global _im_config
    _im_config = None
