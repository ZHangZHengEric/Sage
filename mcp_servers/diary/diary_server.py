
import os
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
from mcp.server.fastmcp import FastMCP
from sagents.tool.mcp_tool_base import sage_mcp_tool

# Initialize FastMCP server
mcp = FastMCP("Diary Service")

# Base storage path - relative to execution directory
BASE_DIR = Path("./data/mcp/diary")

def _get_user_dir(user_id: str) -> Path:
    """Get the directory for a specific user."""
    user_dir = BASE_DIR / user_id
    if not user_dir.exists():
        user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir

def _get_diary_file(user_id: str, date: str) -> Path:
    """Get the file path for a specific diary entry."""
    return _get_user_dir(user_id) / f"{date}.txt"

@mcp.tool()
@sage_mcp_tool()
async def write_diary(user_id: str, date: str, content: str) -> str:
    """
    Write a diary entry for a specific user and date.
    If an entry already exists, it will be overwritten.
    
    Args:
        user_id: The ID of the user.
        date: The date of the diary entry (format: YYYY-MM-DD).
        content: The content of the diary.
        
    Returns:
        str: Success message.
    """
    try:
        # Validate date format
        datetime.strptime(date, "%Y-%m-%d")
        
        file_path = _get_diary_file(user_id, date)
        file_path.write_text(content, encoding="utf-8")
        return f"Diary for {user_id} on {date} saved successfully."
    except ValueError:
        return "Error: Date must be in YYYY-MM-DD format."
    except Exception as e:
        return f"Error saving diary: {str(e)}"

@mcp.tool()
@sage_mcp_tool()
async def update_diary(user_id: str, date: str, content: str, append: bool = False) -> str:
    """
    Update a diary entry. Can overwrite or append to existing content.
    
    Args:
        user_id: The ID of the user.
        date: The date of the diary entry (format: YYYY-MM-DD).
        content: The new content.
        append: If True, appends content to existing diary. If False, overwrites. Default is False.
        
    Returns:
        str: Success message.
    """
    try:
        # Validate date format
        datetime.strptime(date, "%Y-%m-%d")
        
        file_path = _get_diary_file(user_id, date)
        
        if append and file_path.exists():
            current_content = file_path.read_text(encoding="utf-8")
            new_content = current_content + "\n" + content
            file_path.write_text(new_content, encoding="utf-8")
            return f"Diary for {user_id} on {date} updated (appended)."
        else:
            file_path.write_text(content, encoding="utf-8")
            return f"Diary for {user_id} on {date} updated (overwritten)."
            
    except ValueError:
        return "Error: Date must be in YYYY-MM-DD format."
    except Exception as e:
        return f"Error updating diary: {str(e)}"

@mcp.tool()
@sage_mcp_tool()
async def read_diary(user_id: str, date: str) -> str:
    """
    Read a diary entry for a specific user and date.
    
    Args:
        user_id: The ID of the user.
        date: The date of the diary entry (format: YYYY-MM-DD).
        
    Returns:
        str: The content of the diary or a not found message.
    """
    try:
        # Validate date format
        datetime.strptime(date, "%Y-%m-%d")
        
        file_path = _get_diary_file(user_id, date)
        if file_path.exists():
            return file_path.read_text(encoding="utf-8")
        else:
            return f"No diary found for {user_id} on {date}."
    except ValueError:
        return "Error: Date must be in YYYY-MM-DD format."
    except Exception as e:
        return f"Error reading diary: {str(e)}"

@mcp.tool()
@sage_mcp_tool()
async def list_diaries(user_id: str, start_date: str = None, end_date: str = None) -> str:
    """
    List diary entries for a user within a time range.
    
    Args:
        user_id: The ID of the user.
        start_date: Start date (inclusive, YYYY-MM-DD). Optional.
        end_date: End date (inclusive, YYYY-MM-DD). Optional.
        
    Returns:
        str: JSON string of list of diary entries with dates and content previews.
    """
    try:
        user_dir = _get_user_dir(user_id)
        if not user_dir.exists():
            return "[]"
            
        entries = []
        
        # Parse dates if provided
        start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
        end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else None
        
        for file_path in user_dir.glob("*.txt"):
            try:
                date_str = file_path.stem # filename without extension
                entry_date = datetime.strptime(date_str, "%Y-%m-%d")
                
                # Filter by range
                if start and entry_date < start:
                    continue
                if end and entry_date > end:
                    continue
                    
                content = file_path.read_text(encoding="utf-8")
                preview = content[:100] + "..." if len(content) > 100 else content
                entries.append({
                    "date": date_str,
                    "preview": preview
                })
            except ValueError:
                continue # Skip files that don't match date format
                
        # Sort by date
        entries.sort(key=lambda x: x["date"])
        return json.dumps(entries, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return f"Error listing diaries: {str(e)}"

if __name__ == "__main__":
    # Run the MCP server
    mcp.run()
