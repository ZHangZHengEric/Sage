import os
import json
import time
import sqlite3
import threading
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any, Union

from mcp.server.fastmcp import FastMCP
from sagents.tool.mcp_tool_base import sage_mcp_tool

# Initialize FastMCP server
mcp = FastMCP("Agent Hub Service")

# Base storage path - relative to execution directory
BASE_DIR = Path("./data/mcp/agent_hub")
DB_PATH = BASE_DIR / "agent_hub.db"

# Ensure data directory exists
BASE_DIR.mkdir(parents=True, exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AgentHub")

class AgentHubDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            # Agents table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    description TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Messages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_agent_id TEXT NOT NULL,
                    to_agent_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    msg_type TEXT DEFAULT 'text',
                    options TEXT,
                    status TEXT DEFAULT 'pending',
                    scheduled_at DATETIME,
                    sent_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def register_agent(self, agent_id: str, name: str = "", description: str = ""):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO agents (id, name, description)
                VALUES (?, ?, ?)
            """, (agent_id, name, description))
            conn.commit()

    def list_agents(self) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM agents ORDER BY id")
            return [dict(row) for row in cursor.fetchall()]

    def get_message_history(self, agent_id_1: str, agent_id_2: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM messages 
                WHERE (from_agent_id = ? AND to_agent_id = ?) 
                   OR (from_agent_id = ? AND to_agent_id = ?)
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
            """, (agent_id_1, agent_id_2, agent_id_2, agent_id_1, limit, offset))
            return [dict(row) for row in cursor.fetchall()]

    def add_message(self, from_agent_id: str, to_agent_id: str, content: str, msg_type: str = 'text', options: Optional[List[str]] = None, scheduled_at: Optional[str] = None) -> int:
        # Auto-register agents if they don't exist (simple discovery)
        self.register_agent(from_agent_id)
        # Register the recipient as an "agent" (or user entity) if it doesn't exist
        self.register_agent(to_agent_id)

        options_json = json.dumps(options) if options else None
        
        # Determine status based on scheduled_at
        status = 'pending'
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO messages (from_agent_id, to_agent_id, content, msg_type, options, status, scheduled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (from_agent_id, to_agent_id, content, msg_type, options_json, status, scheduled_at))
            conn.commit()
            return cursor.lastrowid

    def get_pending_messages(self) -> List[Dict[str, Any]]:
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # Select pending messages where scheduled_at is NULL (immediate) or <= now
            cursor.execute("""
                SELECT * FROM messages 
                WHERE status = 'pending' 
                  AND (scheduled_at IS NULL OR scheduled_at <= ?)
            """, (now,))
            return [dict(row) for row in cursor.fetchall()]

    def update_message_status(self, msg_id: int, status: str, sent_at: Optional[str] = None):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if sent_at:
                cursor.execute("UPDATE messages SET status = ?, sent_at = ? WHERE id = ?", (status, sent_at, msg_id))
            else:
                cursor.execute("UPDATE messages SET status = ? WHERE id = ?", (status, msg_id))
            conn.commit()

# Initialize DB
db = AgentHubDB(DB_PATH)

# --- Scheduler for Message Delivery ---

def _deliver_message(message: Dict[str, Any]):
    """
    Placeholder for actual message delivery logic.
    """
    msg_id = message['id']
    to_agent_id = message['to_agent_id']
    content = message['content']
    msg_type = message['msg_type']
    
    logger.info(f"Delivering message {msg_id} to {to_agent_id} (Type: {msg_type}): {content[:50]}...")
    
    # TODO: Implement actual delivery logic here (e.g., HTTP request, WebSocket, etc.)
    # For now, we simulate success.
    
    if "user_" in to_agent_id or to_agent_id == "HUMAN":  # Simple check for user IDs
        logger.info(f"Notification sent to User {to_agent_id}: {content}")
        # In a real scenario, this might trigger a push notification or UI alert.
    else:
        logger.info(f"Message sent to agent {to_agent_id}")

    # Mark as sent
    sent_at = datetime.now().isoformat()
    db.update_message_status(msg_id, 'sent', sent_at)

def scheduler_loop():
    """Background loop to check for pending messages."""
    logger.info("Scheduler started.")
    while True:
        try:
            pending_msgs = db.get_pending_messages()
            for msg in pending_msgs:
                try:
                    _deliver_message(msg)
                except Exception as e:
                    logger.error(f"Failed to deliver message {msg['id']}: {e}")
                    # Optionally update status to 'failed' or retry later
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
        
        time.sleep(5)  # Check every 5 seconds

# Start scheduler in a daemon thread
scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
scheduler_thread.start()

# --- MCP Tools ---

@mcp.tool()
@sage_mcp_tool(server_name="agent_hub")
async def list_agents() -> str:
    """
    List all known agents in the system.
    
    [Effect]
    - Returns a JSON list of all agents that have ever sent or received messages.
    
    [When to Use]
    - Use this tool to discover available agent IDs when you need to choose a recipient for a task or message.
    - Useful for initialization or when the agent network is dynamic.

    Returns:
        JSON string containing list of agents.
    """
    agents = db.list_agents()
    return json.dumps(agents, indent=2, ensure_ascii=False)

@mcp.tool()
@sage_mcp_tool(server_name="agent_hub")
async def get_message_history(current_agent_id: str, target_agent_id: str, limit: int = 50) -> str:
    """
    Get message history between two agents.
    
    [Effect]
    - Retrieves a chronological list (newest first) of messages exchanged between two specific entities.
    - Includes message status, content, and scheduling info.

    [When to Use]
    - Use this to check the status of a delegated task.
    - Use this to recall previous context or instructions before continuing a conversation.
    - Use this to check if a human user has replied to an approval request.
    
    Args:
        current_agent_id: The ID of the current agent requesting history.
        target_agent_id: The ID of the other agent (or 'HUMAN').
        limit: Max number of messages to return (default 50).
        
    Returns:
        JSON string containing list of messages.
    """
    messages = db.get_message_history(current_agent_id, target_agent_id, limit)
    return json.dumps(messages, indent=2, ensure_ascii=False)

@mcp.tool()
@sage_mcp_tool(server_name="agent_hub")
async def send_message(from_agent_id: str, to_agent_id: str, content: str, scheduled_at: Optional[str] = None) -> str:
    """
    Send a message to another agent.
    
    [Effect]
    - Enqueues a message for delivery.
    - If `scheduled_at` is NOT provided, the message is marked for immediate delivery.
    - If `scheduled_at` IS provided, the message stays 'pending' until that time.
    - The background scheduler checks every 5 seconds and delivers pending messages that are due.
    
    [When to Use]
    - Use this to assign tasks to other agents ("WorkerAgent, please process this file").
    - Use this to report results back to a manager ("Task completed, here is the summary").
    - Use `scheduled_at` to set up reminders or delayed tasks ("Remind me to check status in 1 hour").

    Args:
        from_agent_id: The ID of the sender agent.
        to_agent_id: The ID of the recipient agent.
        content: The message content.
        scheduled_at: Optional ISO 8601 timestamp (YYYY-MM-DDTHH:MM:SS) to schedule the message. 
                      If None, sends immediately.
                      
    Returns:
        Confirmation message with Message ID.
    """
    try:
        if scheduled_at:
            # Validate timestamp format
            datetime.fromisoformat(scheduled_at)
            
        msg_id = db.add_message(from_agent_id, to_agent_id, content, msg_type='text', scheduled_at=scheduled_at)
        
        status_msg = "scheduled" if scheduled_at else "queued for immediate delivery"
        return f"Message {msg_id} {status_msg}."
    except ValueError:
        return "Error: Invalid scheduled_at format. Use ISO 8601 (YYYY-MM-DDTHH:MM:SS)."
    except Exception as e:
        return f"Error sending message: {str(e)}"

@mcp.tool()
@sage_mcp_tool(server_name="agent_hub")
async def send_human_message(from_agent_id: str, to_user_id: str, content: str, type: str = "notification", options: Optional[List[str]] = None, context: Optional[str] = None) -> str:
    """
    Send a message to a human user (e.g., for approval or notification).
    
    [Effect]
    - Enqueues a message specifically for a human user.
    - Supports interactive options (e.g., Approve/Reject) which the UI can render.
    
    [When to Use]
    - Use `type='notification'` to inform the user of completed tasks or errors.
    - Use `type='approval'` when a critical decision requires human intervention (e.g., "Deploy to production?").
    - ALWAYS provide `context` for approvals so the user knows *why* they are deciding.

    Args:
        from_agent_id: The ID of the sender agent.
        to_user_id: The ID of the human user.
        content: The main message content.
        type: The type of message. 'notification' (default) or 'approval'.
        options: List of options for 'approval' type (e.g., ["Approve", "Reject"]). 
                 Ignored for notifications.
        context: Additional context information to help the agent/user recall the background 
                 when a reply is received. Highly recommended for approvals.
                 
    Returns:
        Confirmation message with Message ID.
    """
    if type not in ['notification', 'approval']:
        return "Error: Type must be 'notification' or 'approval'."
        
    if type == 'approval' and not options:
        options = ["Approve", "Reject"]
    
    final_content = content
    if context:
        final_content = f"{content}\n\n[Context]\n{context}"
        
    msg_id = db.add_message(from_agent_id, to_user_id, final_content, msg_type=type, options=options)
    return f"Message {msg_id} sent to user {to_user_id} (Type: {type})."

if __name__ == "__main__":
    mcp.run()
