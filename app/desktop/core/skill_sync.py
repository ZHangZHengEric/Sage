"""Skill synchronization module for auto-importing IDE skills."""

import os
import shutil
from pathlib import Path
from typing import List, Tuple


# IDE skill folder paths (relative to home directory)
IDE_SKILL_PATHS = [
    # Antigravity
    (".agents/skills", "Antigravity"),
    # Augment
    (".augment/skills", "Augment"),
    # Claude Code
    (".claude/skills", "Claude Code"),
    # OpenClaw
    ("skills", "OpenClaw"),
    # CodeBuddy
    (".codebuddy/skills", "CodeBuddy"),
    # Command Code
    (".commandcode/skills", "Command Code"),
    # Continue
    (".continue/skills", "Continue"),
    # Cortex Code
    (".cortex/skills", "Cortex Code"),
    # Crush
    (".crush/skills", "Crush"),
    # Droid
    (".factory/skills", "Droid"),
    # Goose
    (".goose/skills", "Goose"),
    # Junie
    (".junie/skills", "Junie"),
    # iFlow CLI
    (".iflow/skills", "iFlow CLI"),
    # Kilo Code
    (".kilocode/skills", "Kilo Code"),
    # Kiro CLI
    (".kiro/skills", "Kiro CLI"),
    # Kode
    (".kode/skills", "Kode"),
    # MCPJam
    (".mcpjam/skills", "MCPJam"),
    # Mistral Vibe
    (".vibe/skills", "Mistral Vibe"),
    # Mux
    (".mux/skills", "Mux"),
    # OpenHands
    (".openhands/skills", "OpenHands"),
    # Pi
    (".pi/skills", "Pi"),
    # Qoder
    (".qoder/skills", "Qoder"),
    # Qwen Code
    (".qwen/skills", "Qwen Code"),
    # Roo Code
    (".roo/skills", "Roo Code"),
    # Trae
    (".trae/skills", "Trae"),
    # Trae CN
    (".trae/skills", "Trae CN"),
    # Windsurf
    (".windsurf/skills", "Windsurf"),
    # Zencoder
    (".zencoder/skills", "Zencoder"),
    # Neovate
    (".neovate/skills", "Neovate"),
    # Pochi
    (".pochi/skills", "Pochi"),
    # AdaL
    (".adal/skills", "AdaL"),
]


def get_home_dir() -> Path:
    """Get the user's home directory."""
    return Path.home()


def get_sage_skills_dir() -> Path:
    """Get the Sage skills directory."""
    home = get_home_dir()
    sage_skills = home / ".sage" / "skills"
    sage_skills.mkdir(parents=True, exist_ok=True)
    return sage_skills


def find_ide_skills() -> List[Tuple[Path, str]]:
    """Find all IDE skill folders that exist."""
    home = get_home_dir()
    found_skills = []
    
    for rel_path, ide_name in IDE_SKILL_PATHS:
        skill_path = home / rel_path
        if skill_path.exists() and skill_path.is_dir():
            found_skills.append((skill_path, ide_name))
    
    return found_skills


def sync_skills() -> dict:
    """
    Synchronize IDE skills to Sage skills folder.
    
    Returns:
        dict: Sync results with counts and details
    """
    sage_skills_dir = get_sage_skills_dir()
    ide_skills = find_ide_skills()
    
    results = {
        "total_ide_folders": len(ide_skills),
        "copied": 0,
        "skipped": 0,
        "errors": [],
        "details": []
    }
    
    for ide_skill_path, ide_name in ide_skills:
        try:
            # Iterate through skills in the IDE folder
            for skill_item in ide_skill_path.iterdir():
                if skill_item.is_dir():
                    skill_name = skill_item.name
                    target_path = sage_skills_dir / skill_name
                    
                    # Check if skill already exists in Sage
                    if target_path.exists():
                        results["skipped"] += 1
                        results["details"].append({
                            "skill": skill_name,
                            "source": ide_name,
                            "action": "skipped",
                            "reason": "already exists in Sage"
                        })
                    else:
                        # Copy the skill folder
                        shutil.copytree(skill_item, target_path)
                        results["copied"] += 1
                        results["details"].append({
                            "skill": skill_name,
                            "source": ide_name,
                            "action": "copied",
                            "path": str(target_path)
                        })
                        
        except Exception as e:
            error_msg = f"Error processing {ide_name} ({ide_skill_path}): {e}"
            results["errors"].append(error_msg)
    
    return results


def sync_skills_with_logging():
    """Sync skills and print results."""
    print("=" * 60)
    print("Sage Skill Synchronization")
    print("=" * 60)
    
    results = sync_skills()
    
    print(f"\nFound {results['total_ide_folders']} IDE skill folders")
    print(f"Skills copied: {results['copied']}")
    print(f"Skills skipped (already exist): {results['skipped']}")
    
    if results['details']:
        print("\nDetails:")
        for detail in results['details']:
            action = detail['action']
            skill = detail['skill']
            source = detail['source']
            if action == 'copied':
                print(f"  ✓ [{source}] {skill} -> copied")
            else:
                print(f"  ⊘ [{source}] {skill} -> skipped ({detail.get('reason', '')})")
    
    if results['errors']:
        print("\nErrors:")
        for error in results['errors']:
            print(f"  ✗ {error}")
    
    print("=" * 60)
    
    return results


if __name__ == "__main__":
    sync_skills_with_logging()
