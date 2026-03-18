"""
Migration script: Global IM Configuration → Per-Agent Configuration.

This script migrates existing global IM channel configurations from the database
to the new per-Agent JSON file structure.

Migration Process:
1. Read existing configurations from SQLite database (im_user_configs table)
2. Convert to new AgentIMConfig format
3. Save to ~/.sage/agents/{agent_id}/config/im_channels.json
4. Optionally backup/disable old database entries

Usage:
    # Run migration for default agent
    python -m mcp_servers.im_server.migration
    
    # Run with specific agent
    python -m mcp_servers.im_server.migration --agent-id default
    
    # Dry run (preview only, no changes)
    python -m mcp_servers.im_server.migration --dry-run

Safety:
- Backs up existing configuration files before overwriting
- Idempotent: Can be run multiple times safely
- Validates configuration before saving
"""

import argparse
import json
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mcp_servers.im_server.db import get_im_db
from mcp_servers.im_server.agent_config import (
    get_agent_im_config,
    AgentIMConfig,
    DEFAULT_AGENT_ID,
    validate_provider_config
)


def backup_existing_config(agent_id: str) -> Optional[Path]:
    """
    Backup existing agent configuration file before migration.
    
    Args:
        agent_id: Agent identifier
        
    Returns:
        Path to backup file, or None if no existing config
    """
    config_path = Path.home() / ".sage" / "agents" / agent_id / "config" / "im_channels.json"
    
    if not config_path.exists():
        return None
    
    # Create backup with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = config_path.with_suffix(f'.json.backup_{timestamp}')
    
    try:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(config_path.read_text())
        print(f"  📦 Backed up existing config to: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"  ⚠️  Failed to backup config: {e}")
        return None


def migrate_global_config(agent_id: str = DEFAULT_AGENT_ID, dry_run: bool = False) -> Dict[str, Any]:
    """
    Migrate global IM configurations to Agent-level configuration.
    
    Args:
        agent_id: Target Agent ID (default: DEFAULT_AGENT_ID)
        dry_run: If True, only preview changes without applying
        
    Returns:
        Migration result statistics
    """
    print(f"\n{'='*60}")
    print(f"IM Configuration Migration")
    print(f"Target Agent: {agent_id}")
    print(f"Mode: {'DRY RUN (preview only)' if dry_run else 'LIVE (will apply changes)'}")
    print(f"{'='*60}\n")
    
    result = {
        "success": True,
        "migrated": [],
        "skipped": [],
        "failed": [],
        "total": 0
    }
    
    # Step 1: Read existing configurations from database
    print("📖 Step 1: Reading existing configurations from database...")
    
    try:
        db = get_im_db()
        # Get all configurations for the default user
        # For migration, we focus on desktop_default_user configs
        from mcp_servers.im_server.im_server import DEFAULT_SAGE_USER_ID
        configs = db.list_user_configs(DEFAULT_SAGE_USER_ID)
        print(f"   Found {len(configs)} configuration(s) for user '{DEFAULT_SAGE_USER_ID}'\n")
    except Exception as e:
        print(f"❌ Failed to read database: {e}")
        return {"success": False, "error": str(e)}
    
    if not configs:
        print("ℹ️  No configurations found in database. Nothing to migrate.")
        return result
    
    # Step 2: Group configurations by user
    configs_by_user: Dict[str, List[Dict]] = {}
    for config in configs:
        user_id = config.get("sage_user_id", "unknown")
        if user_id not in configs_by_user:
            configs_by_user[user_id] = []
        configs_by_user[user_id].append(config)
    
    print(f"📊 Step 2: Configurations grouped by {len(configs_by_user)} user(s)")
    for user_id, user_configs in configs_by_user.items():
        print(f"   - {user_id}: {len(user_configs)} config(s)")
    print()
    
    # Step 3: Prepare migration (for default agent, migrate all configs)
    print(f"🔄 Step 3: Preparing migration to agent '{agent_id}'...")
    
    # For now, we migrate to default agent. In the future, could map users to agents
    configs_to_migrate = []
    
    for user_id, user_configs in configs_by_user.items():
        for config in user_configs:
            result["total"] += 1
            
            provider = config.get("provider")
            enabled = config.get("enabled", False)
            provider_config = config.get("config", {})
            
            print(f"\n   Processing: {user_id} / {provider}")
            print(f"   - Enabled: {enabled}")
            print(f"   - Config keys: {list(provider_config.keys()) if provider_config else 'None'}")
            
            # Validate (especially for iMessage)
            try:
                validate_provider_config(agent_id, provider, provider_config)
                configs_to_migrate.append({
                    "provider": provider,
                    "enabled": enabled,
                    "config": provider_config
                })
                result["migrated"].append(f"{user_id}/{provider}")
                print(f"   ✅ Validated and queued for migration")
            except ValueError as e:
                result["skipped"].append(f"{user_id}/{provider}")
                print(f"   ⚠️  Skipped: {e}")
    
    print(f"\n   Summary: {len(configs_to_migrate)} config(s) ready for migration")
    
    # Step 4: Apply migration (if not dry run)
    if dry_run:
        print("\n🏁 DRY RUN completed. No changes were made.")
        print(f"   Would migrate {len(configs_to_migrate)} configuration(s)")
        return result
    
    print(f"\n💾 Step 4: Applying migration...")
    
    try:
        # Backup existing config
        backup_path = backup_existing_config(agent_id)
        
        # Get or create Agent config
        agent_config = get_agent_im_config(agent_id)
        
        # Apply each configuration
        for item in configs_to_migrate:
            provider = item["provider"]
            enabled = item["enabled"]
            config = item["config"]
            
            try:
                success = agent_config.set_provider_config(provider, enabled, config)
                if success:
                    print(f"   ✅ Migrated: {provider}")
                else:
                    print(f"   ❌ Failed to save: {provider}")
                    result["failed"].append(provider)
            except Exception as e:
                print(f"   ❌ Error saving {provider}: {e}")
                result["failed"].append(provider)
        
        # Verify migration
        print(f"\n✅ Step 5: Verifying migration...")
        all_channels = agent_config.get_all_channels()
        print(f"   Agent '{agent_id}' now has {len(all_channels)} channel(s):")
        for provider, channel in all_channels.items():
            status = "enabled" if channel.get("enabled") else "disabled"
            print(f"   - {provider}: {status}")
        
        print(f"\n{'='*60}")
        print(f"✅ Migration completed successfully!")
        print(f"   Migrated: {len(result['migrated'])}")
        print(f"   Skipped: {len(result['skipped'])}")
        print(f"   Failed: {len(result['failed'])}")
        if backup_path:
            print(f"   Backup: {backup_path}")
        print(f"{'='*60}\n")
        
        return result
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            **result
        }


def main():
    """CLI entry point for migration script."""
    parser = argparse.ArgumentParser(
        description="Migrate global IM configurations to per-Agent configuration"
    )
    parser.add_argument(
        "--agent-id",
        default=DEFAULT_AGENT_ID,
        help=f"Target Agent ID (default: {DEFAULT_AGENT_ID})"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them"
    )
    parser.add_argument(
        "--disable-legacy",
        action="store_true",
        help="[Future] Disable legacy database configurations after migration"
    )
    
    args = parser.parse_args()
    
    # Run migration
    result = migrate_global_config(
        agent_id=args.agent_id,
        dry_run=args.dry_run
    )
    
    # Exit with appropriate code
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
