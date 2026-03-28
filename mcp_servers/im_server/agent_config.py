"""
Agent-level IM Channel Configuration Management.

This module provides per-Agent IM channel configuration storage and management,
replacing the previous global configuration approach.

Features:
- JSON-based configuration storage per Agent
- Hot-reload support (configuration changes take effect immediately)
- Agent-level isolation (each Agent has its own channel configs)
- iMessage restriction (only allowed on default Agent)

Configuration File Structure:
    ~/.sage/agents/{agent_id}/config/im_channels.json
    
    {
        "agent_id": "agent_xxx",
        "channels": {
            "wechat_work": {
                "enabled": true,
                "config": {
                    "bot_id": "...",
                    "secret": "..."
                }
            },
            "dingtalk": {
                "enabled": false,
                "config": {}
            }
        },
        "updated_at": "2026-03-16T12:00:00Z"
    }

Usage:
    config = AgentIMConfig(agent_id="agent_xxx")
    wechat_config = config.get_provider_config("wechat_work")
    if wechat_config:
        # Use the config
        bot_id = wechat_config["bot_id"]
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict
import logging
import threading

logger = logging.getLogger("AgentIMConfig")

# Default Agent ID (fixed identifier for the default agent)
DEFAULT_AGENT_ID = "default"

# iMessage provider identifier
IMESSAGE_PROVIDER = "imessage"

# WeChat Personal (iLink) provider identifier
WECHAT_PERSONAL_PROVIDER = "wechat_personal"


# Cache for default agent ID
_default_agent_id_cache: Optional[str] = None


def get_default_agent_id() -> str:
    """
    Get the default Agent ID.
    
    Returns:
        The agent_id of the default Agent.
    """
    global _default_agent_id_cache
    
    if _default_agent_id_cache is not None:
        return _default_agent_id_cache
    
    try:
        # Try to read from database
        import asyncio
        from app.desktop.core.models.agent import AgentConfigDao
        
        dao = AgentConfigDao()
        
        # Run async query in sync context
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Use run_coroutine_threadsafe for thread-safe execution
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, dao.get_default())
                    agent = future.result(timeout=5)
            else:
                agent = asyncio.run(dao.get_default())
        except RuntimeError:
            agent = asyncio.run(dao.get_default())
        
        if agent:
            _default_agent_id_cache = agent.agent_id
            return _default_agent_id_cache
    except Exception as e:
        logger.warning(f"[AgentIMConfig] Failed to get default agent from DB: {e}")
    
    # Fallback: return the first agent from filesystem or default
    try:
        agents_dir = Path.home() / ".sage" / "agents"
        if agents_dir.exists():
            agent_dirs = [d for d in agents_dir.iterdir() if d.is_dir()]
            if agent_dirs:
                _default_agent_id_cache = agent_dirs[0].name
                return _default_agent_id_cache
    except Exception as e:
        logger.warning(f"[AgentIMConfig] Failed to get agent from filesystem: {e}")
    
    # Ultimate fallback
    _default_agent_id_cache = DEFAULT_AGENT_ID
    return _default_agent_id_cache


def reset_default_agent_cache():
    """Reset the default agent cache."""
    global _default_agent_id_cache
    _default_agent_id_cache = None


@dataclass
class ChannelConfig:
    """
    Configuration for a single IM channel (provider).
    
    Attributes:
        provider: Provider type (wechat_work, dingtalk, feishu, imessage)
        enabled: Whether this channel is active
        config: Provider-specific configuration dict
    """
    provider: str
    enabled: bool = False
    config: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.config is None:
            self.config = {}


class AgentIMConfig:
    """
    Manages IM channel configurations for a specific Agent.
    
    This class handles:
    - Reading/writing configuration from JSON files
    - Hot-reloading when files change
    - Per-Agent configuration isolation
    - Validation (e.g., iMessage only on default Agent)
    
    Thread-safe: Uses file-level locking and atomic writes.
    Hot-reload: Checks file mtime on each read, reloads if changed.
    """
    
    def __init__(self, agent_id: str):
        """
        Initialize configuration manager for an Agent.
        
        Args:
            agent_id: Unique identifier for the Agent (e.g., "agent_859ae28f")
        """
        self.agent_id = agent_id
        self._config_dir = Path.home() / ".sage" / "agents" / agent_id / "config"
        self._config_path = self._config_dir / "im_channels.json"
        
        # Cache and tracking
        self._cache: Optional[Dict] = None
        self._mtime: float = 0
        self._lock = threading.RLock()
        
        # Ensure directory exists
        self._ensure_config_dir()
        
        logger.debug(f"[AgentIMConfig] Initialized for agent={agent_id}, path={self._config_path}")
    
    def _ensure_config_dir(self) -> None:
        """Create configuration directory if it doesn't exist."""
        try:
            self._config_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"[AgentIMConfig] Failed to create config dir: {e}")
    
    def _load_config_from_db(self) -> Optional[Dict]:
        """
        Load configuration from database.
        
        Returns:
            Configuration dict if found in database, None otherwise.
        """
        try:
            import asyncio
            from app.desktop.core.models.agent import AgentConfigDao
            
            dao = AgentConfigDao()
            
            # Run async query in sync context
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, dao.get_by_id(self.agent_id))
                        agent = future.result(timeout=5)
                else:
                    agent = asyncio.run(dao.get_by_id(self.agent_id))
            except RuntimeError:
                agent = asyncio.run(dao.get_by_id(self.agent_id))
            
            if agent and hasattr(agent, 'config') and agent.config:
                import json
                config = agent.config
                if isinstance(config, str):
                    config = json.loads(config)
                im_channels = config.get('im_channels', {})
                if im_channels:
                    logger.debug(f"[AgentIMConfig] Loaded config from database for agent={self.agent_id}")
                    return {
                        "agent_id": self.agent_id,
                        "channels": im_channels,
                        "updated_at": agent.updated_at.isoformat() if hasattr(agent, 'updated_at') and agent.updated_at else datetime.now().isoformat()
                    }
        except Exception as e:
            logger.warning(f"[AgentIMConfig] Failed to load config from database: {e}")
        
        return None
    
    def _load_config(self) -> Dict:
        """
        Load configuration from database or file (fallback).
        
        Returns:
            Configuration dict. Returns empty structure if not found.
        """
        # Try database first (primary source)
        db_config = self._load_config_from_db()
        if db_config:
            return db_config
        
        # Fallback to file system (backward compatibility)
        if not self._config_path.exists():
            logger.debug(f"[AgentIMConfig] Config file not found, returning empty config")
            return {
                "agent_id": self.agent_id,
                "channels": {},
                "updated_at": datetime.now().isoformat()
            }
        
        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content.strip():
                    return {
                        "agent_id": self.agent_id,
                        "channels": {},
                        "updated_at": datetime.now().isoformat()
                    }
                return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"[AgentIMConfig] Invalid JSON in config file: {e}")
            return {
                "agent_id": self.agent_id,
                "channels": {},
                "updated_at": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"[AgentIMConfig] Failed to load config: {e}")
            return {
                "agent_id": self.agent_id,
                "channels": {},
                "updated_at": datetime.now().isoformat()
            }
    
    def _reload_if_changed(self) -> None:
        """
        Check if configuration has changed and reload if necessary.
        
        For database-backed configs, always reload to get latest state.
        For file-backed configs, check mtime.
        """
        with self._lock:
            # Always reload from database on first access or periodically
            if self._cache is None:
                logger.debug(f"[AgentIMConfig] Loading config for first time...")
                self._cache = self._load_config()
                if self._config_path.exists():
                    try:
                        self._mtime = self._config_path.stat().st_mtime
                    except Exception:
                        pass
                return
            
            # For file-based configs, check mtime
            if self._config_path.exists():
                try:
                    current_mtime = self._config_path.stat().st_mtime
                    if current_mtime != self._mtime:
                        logger.debug(f"[AgentIMConfig] Config file changed, reloading...")
                        self._cache = self._load_config()
                        self._mtime = current_mtime
                        logger.info(f"[AgentIMConfig] Configuration reloaded for agent={self.agent_id}")
                except Exception as e:
                    logger.warning(f"[AgentIMConfig] Cannot stat config file: {e}")
    
    def get_provider_config(self, provider: str) -> Optional[Dict[str, Any]]:
        """
        Get configuration for a specific provider.
        
        Args:
            provider: Provider type (wechat_work, dingtalk, feishu, imessage)
            
        Returns:
            Provider configuration dict if enabled, None otherwise.
            
        Example:
            config = agent_config.get_provider_config("wechat_work")
            if config:
                bot_id = config["bot_id"]
                secret = config["secret"]
        """
        self._reload_if_changed()
        
        with self._lock:
            channels = self._cache.get("channels", {})
            channel = channels.get(provider)
            
            if not channel:
                logger.debug(f"[AgentIMConfig] No config found for provider={provider}")
                return None
            
            if not channel.get("enabled", False):
                logger.debug(f"[AgentIMConfig] Provider={provider} is disabled")
                return None
            
            config = channel.get("config", {})
            logger.debug(f"[AgentIMConfig] Got config for provider={provider}")
            return config.copy() if config else None
    
    def get_all_channels(self) -> Dict[str, Dict]:
        """
        Get all channel configurations for this Agent.
        
        Returns:
            Dict mapping provider names to channel configs.
        """
        self._reload_if_changed()
        
        with self._lock:
            return self._cache.get("channels", {}).copy()
    
    def is_provider_enabled(self, provider: str) -> bool:
        """
        Check if a provider is enabled for this Agent.
        
        Args:
            provider: Provider type
            
        Returns:
            True if provider exists and is enabled.
        """
        config = self.get_provider_config(provider)
        return config is not None
    
    def set_provider_config(self, provider: str, enabled: bool, config: Dict[str, Any]) -> bool:
        """
        Set configuration for a provider.
        
        Args:
            provider: Provider type
            enabled: Whether to enable this provider
            config: Provider-specific configuration
            
        Returns:
            True if successful, False otherwise.
            
        Raises:
            ValueError: If trying to configure iMessage on non-default Agent.
        """
        # Validate: iMessage only allowed on default Agent (only when enabled)
        if provider == IMESSAGE_PROVIDER and enabled:
            default_agent_id = get_default_agent_id()
            if self.agent_id != default_agent_id:
                logger.error(f"[AgentIMConfig] iMessage can only be configured on default agent (current={self.agent_id}, default={default_agent_id})")
                raise ValueError(f"iMessage provider can only be configured on default agent (id={default_agent_id})")
        
        with self._lock:
            self._reload_if_changed()
            
            # Ensure channels dict exists
            if "channels" not in self._cache:
                self._cache["channels"] = {}
            
            # Update config
            self._cache["channels"][provider] = {
                "enabled": enabled,
                "config": config
            }
            self._cache["updated_at"] = datetime.now().isoformat()
            
            # Save to file (atomic write)
            return self._save_config()
    
    def remove_provider(self, provider: str) -> bool:
        """
        Remove a provider configuration.
        
        Args:
            provider: Provider type to remove
            
        Returns:
            True if successful, False otherwise.
        """
        with self._lock:
            self._reload_if_changed()
            
            if "channels" in self._cache and provider in self._cache["channels"]:
                del self._cache["channels"][provider]
                self._cache["updated_at"] = datetime.now().isoformat()
                return self._save_config()
            
            return True
    
    def _save_config(self) -> bool:
        """
        Save configuration to file atomically.
        
        Uses write-to-temp + rename pattern for atomicity.
        
        Returns:
            True if successful, False otherwise.
        """
        try:
            # Ensure directory exists
            self._ensure_config_dir()
            
            # Write to temporary file first (atomic write)
            temp_path = self._config_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
            
            # Atomic rename
            temp_path.replace(self._config_path)
            
            # Update mtime cache
            self._mtime = self._config_path.stat().st_mtime
            
            logger.info(f"[AgentIMConfig] Configuration saved for agent={self.agent_id}")
            return True
            
        except Exception as e:
            logger.error(f"[AgentIMConfig] Failed to save config: {e}")
            return False
    
    def get_config_path(self) -> Path:
        """Get the configuration file path."""
        return self._config_path


# Global cache for AgentIMConfig instances (to avoid recreating)
_agent_config_cache: Dict[str, AgentIMConfig] = {}
_cache_lock = threading.Lock()


def get_agent_im_config(agent_id: str) -> AgentIMConfig:
    """
    Get or create AgentIMConfig instance for an Agent.
    
    Uses global caching to avoid creating multiple instances for the same Agent.
    
    Args:
        agent_id: Agent identifier
        
    Returns:
        AgentIMConfig instance
        
    Example:
        config = get_agent_im_config("agent_859ae28f")
        wechat_config = config.get_provider_config("wechat_work")
    """
    with _cache_lock:
        if agent_id not in _agent_config_cache:
            _agent_config_cache[agent_id] = AgentIMConfig(agent_id)
        return _agent_config_cache[agent_id]


def invalidate_agent_config_cache(agent_id: str) -> None:
    """
    Invalidate cached config for an Agent (force reload on next access).
    
    Args:
        agent_id: Agent identifier to invalidate
    """
    with _cache_lock:
        if agent_id in _agent_config_cache:
            del _agent_config_cache[agent_id]
            logger.debug(f"[AgentIMConfig] Cache invalidated for agent={agent_id}")


def is_default_agent(agent_id: str) -> bool:
    """
    Check if an Agent is the default Agent.
    
    Args:
        agent_id: Agent identifier
        
    Returns:
        True if this is the default Agent.
    """
    return agent_id == get_default_agent_id()


def validate_provider_config(agent_id: str, provider: str, config: Dict[str, Any], enabled: bool = False) -> None:
    """
    Validate provider configuration before saving.
    
    Args:
        agent_id: Agent identifier
        provider: Provider type
        config: Configuration to validate
        enabled: Whether this provider is enabled
        
    Raises:
        ValueError: If validation fails (e.g., iMessage on non-default Agent)
    """
    # iMessage restriction (only check if enabled)
    if provider == IMESSAGE_PROVIDER and enabled:
        default_agent_id = get_default_agent_id()
        if agent_id != default_agent_id:
            raise ValueError(
                f"iMessage provider can only be configured on the default agent. "
                f"Current agent={agent_id}, default={default_agent_id}"
            )
    
    # iMessage allowed_senders validation
    if provider == IMESSAGE_PROVIDER and enabled:
        allowed_senders = config.get('allowed_senders', []) if config else []
        if not allowed_senders or len(allowed_senders) == 0:
            raise ValueError(
                "iMessage must have at least one allowed sender configured. "
                "Please add phone numbers to the '监听发送者' field."
            )
    
    logger.debug(f"[AgentIMConfig] Config validated for agent={agent_id}, provider={provider}")


def list_all_agents() -> List[str]:
    """
    List all Agents that have IM channel configuration.
    
    Checks both filesystem and database for agents with IM config.
    
    Returns:
        List of agent IDs with IM config.
    """
    agents = set()
    
    # 1. Check filesystem
    try:
        agents_dir = Path.home() / ".sage" / "agents"
        if agents_dir.exists():
            for agent_dir in agents_dir.iterdir():
                if agent_dir.is_dir():
                    config_file = agent_dir / "config" / "im_channels.json"
                    if config_file.exists():
                        agents.add(agent_dir.name)
    except Exception as e:
        logger.warning(f"[AgentIMConfig] Failed to list agents from filesystem: {e}")
    
    # 2. Check database (primary source)
    try:
        import asyncio
        from app.desktop.core.models.agent import AgentConfigDao
        
        dao = AgentConfigDao()
        
        # Run async query in sync context
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, dao.get_list())
                    all_agents = future.result(timeout=5)
            else:
                all_agents = asyncio.run(dao.get_list())
        except RuntimeError:
            all_agents = asyncio.run(dao.get_list())
        
        # Filter agents with IM channels config
        for agent in all_agents:
            if agent and agent.agent_id:
                # Check if this agent has im_channels in config
                try:
                    config = agent.config if hasattr(agent, 'config') else {}
                    if isinstance(config, str):
                        import json
                        config = json.loads(config)
                    im_channels = config.get('im_channels') if config else None
                    if im_channels and len(im_channels) > 0:
                        agents.add(agent.agent_id)
                except Exception:
                    pass
        
    except Exception as e:
        logger.warning(f"[AgentIMConfig] Failed to list agents from database: {e}")
    
    agents_list = list(agents)
    logger.info(f"[AgentIMConfig] Found {len(agents_list)} agents with IM config: {agents_list}")
    return agents_list


def find_agent_by_provider_id(provider: str, id_value: str, exclude_agent_id: str = None) -> Optional[str]:
    """
    Find which Agent is using a specific provider ID (bot_id/client_id/app_id).
    
    Args:
        provider: Provider type (wechat_work/dingtalk/feishu)
        id_value: The ID value to search for (bot_id/client_id/app_id)
        exclude_agent_id: Optional agent_id to exclude from search (for update scenarios)
        
    Returns:
        Agent ID that is using this provider ID, or None if not found
    """
    if not id_value:
        return None
    
    # Map provider to the config field name
    id_field_map = {
        "wechat_work": "bot_id",
        "dingtalk": "client_id",
        "feishu": "app_id"
    }
    
    id_field = id_field_map.get(provider)
    if not id_field:
        return None
    
    try:
        agents = list_all_agents()
        for agent_id in agents:
            if agent_id == exclude_agent_id:
                continue
            
            try:
                agent_config = get_agent_im_config(agent_id)
                provider_config = agent_config.get_provider_config(provider)
                
                if provider_config:
                    existing_id = provider_config.get(id_field)
                    if existing_id and existing_id == id_value:
                        logger.warning(f"[AgentIMConfig] Found duplicate {provider} {id_field}='{id_value}' "
                                     f"between agents: {agent_id} and {exclude_agent_id or 'new'}")
                        return agent_id
            except Exception as e:
                logger.debug(f"[AgentIMConfig] Failed to check agent {agent_id}: {e}")
                continue
        
        return None
    except Exception as e:
        logger.warning(f"[AgentIMConfig] Failed to search for provider ID: {e}")
        return None
