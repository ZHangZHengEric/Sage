import os
import json
import sqlite3
import time
import threading
import logging
import httpx
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from mcp.server.fastmcp import FastMCP
from sagents.tool.mcp_tool_base import sage_mcp_tool

from .db import TaskSchedulerDB, TaskType

# Initialize FastMCP server
mcp = FastMCP("Task Scheduler Service")

# Constants
logger = logging.getLogger("TaskScheduler")

# Base storage path - relative to execution directory
BASE_DIR = Path("./data/mcp/task_scheduler")
DB_PATH = BASE_DIR / "tasks.db"

# Ensure data directory exists
BASE_DIR.mkdir(parents=True, exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TaskScheduler")


def _get_api_base_url() -> str:
    """
    Get the API base URL for the Sage server.
    Since this MCP server runs in the same container as the main server,
    we use localhost with the port from environment or default.
    """
    # Try to get port from environment variable or use default 8001
    port = os.getenv("SAGE_PORT", "8001")
    return f"http://localhost:{port}"


# Initialize DB
db = TaskSchedulerDB(DB_PATH)


# --- Scheduler for Task Execution ---

def _parse_stream_response(response: httpx.Response) -> str:
    """
    Parse the streaming response from Sage API.
    Handles both simple NDJSON lines and chunked JSON protocol.
    """
    buffer = {}
    full_content = []

    for line in response.iter_lines():
        if not line:
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = data.get("type")

        if msg_type == "chunk_start":
            total_chunks = data.get("total_chunks", 0)
            if total_chunks > 0:
                buffer[data["message_id"]] = [""] * total_chunks
            continue

        elif msg_type == "json_chunk":
            msg_id = data.get("message_id")
            idx = data.get("chunk_index")
            if msg_id in buffer and idx is not None:
                if idx < len(buffer[msg_id]):
                    buffer[msg_id][idx] = data.get("chunk_data", "")
            continue

        elif msg_type == "chunk_end":
            msg_id = data.get("message_id")
            if msg_id in buffer:
                full_json_str = "".join(buffer[msg_id])
                del buffer[msg_id]
                try:
                    obj = json.loads(full_json_str)
                    if obj.get("role") == "assistant" and obj.get("content"):
                        content = obj.get("content")
                        if isinstance(content, str):
                            full_content.append(content)
                except json.JSONDecodeError:
                    pass
            continue

        role = data.get("role")
        content = data.get("content")
        if role == "assistant" and content and isinstance(content, str):
            full_content.append(content)

    return "".join(full_content)


def _execute_task_sync(task: Dict[str, Any]) -> None:
    """
    Synchronously execute a task by sending it to the specified agent.
    This function runs in a separate thread.
    """
    task_id = task['id']
    agent_id = task['agent_id']
    session_id = task['session_id']
    name = task['name']
    description = task['description']

    logger.info(f"Executing task {task_id} for agent {agent_id} (Session: {session_id})")

    try:
        # Prepare the message content
        content = f"【定时任务】{name}\n\n{description}" if description else f"【定时任务】{name}"

        payload = {
            "agent_id": agent_id,
            "messages": [{"role": "user", "content": content}],
            "session_id": session_id,
            "force_summary": True,
            "user_id": "task_scheduler"
        }

        api_base_url = _get_api_base_url()
        logger.info(f"Sending task {task_id} to agent {agent_id} via API at {api_base_url}...")

        full_response_text = ""

        # Use synchronous client inside the thread
        with httpx.Client(timeout=300.0) as client:
            with client.stream("POST", f"{api_base_url}/api/chat", json=payload) as response:
                response.raise_for_status()
                full_response_text = _parse_stream_response(response)

        logger.info(f"Task {task_id} completed. Response length: {len(full_response_text)}")

        # Add to history
        db.add_task_history(task_id, 'completed', full_response_text)

        # Handle recurring tasks
        task_type = task.get('task_type', 'once')
        if task_type != TaskType.ONCE:
            db.reschedule_recurring_task(task_id, task_type)
            logger.info(f"Task {task_id} rescheduled for next {task_type} execution")
        else:
            # Mark as completed for one-time tasks
            db.complete_task(task_id)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to execute task {task_id}: {error_msg}")

        # Add to history
        db.add_task_history(task_id, 'failed', error_message=error_msg)

        # Check retry count
        retry_count = task.get('retry_count', 0)
        max_retries = task.get('max_retries', 3)

        if retry_count < max_retries:
            db.update_task_status(task_id, 'pending', error_message=error_msg)
            logger.info(f"Task {task_id} will be retried ({retry_count + 1}/{max_retries})")
        else:
            db.update_task_status(task_id, 'failed', error_message=error_msg)
            logger.info(f"Task {task_id} failed after {max_retries} retries")


def _execute_task(task: Dict[str, Any]) -> bool:
    """
    Execute a task by starting it in a separate thread.
    Returns True if task was claimed and started successfully.
    """
    task_id = task['id']

    # Try to claim the task (change status from pending to processing)
    if not db.claim_task(task_id):
        logger.info(f"Task {task_id} already being processed or not pending. Skipping.")
        return False

    # Start task execution in a separate thread
    task_thread = threading.Thread(
        target=_execute_task_sync,
        args=(task,),
        daemon=True,
        name=f"TaskExecutor-{task_id}"
    )
    task_thread.start()
    logger.info(f"Task {task_id} started in thread {task_thread.name}")
    return True


def scheduler_loop():
    """Background loop to check for pending tasks."""
    logger.info("Task scheduler started.")
    logger.info(f"API Base URL: {_get_api_base_url()}")
    while True:
        try:
            pending_tasks = db.get_pending_tasks()
            for task in pending_tasks:
                try:
                    # Start task in separate thread, don't wait for completion
                    _execute_task(task)
                except Exception as e:
                    logger.error(f"Failed to start task {task['id']}: {e}")
        except Exception as e:
            logger.error(f"Scheduler error: {e}")

        time.sleep(5)  # Check every 5 seconds


# Start scheduler in a daemon thread
scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
scheduler_thread.start()


# --- MCP Tools ---

@mcp.tool()
@sage_mcp_tool(server_name="task_scheduler")
async def list_tasks(agent_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50) -> str:
    """
    List tasks for a specific agent or all tasks.

    [Effect]
    - Retrieves a list of tasks from the task scheduler database.
    - Can be filtered by agent_id and/or status.
    - Returns task details including name, description, execution time, and status.
    - Does NOT include full execution content to keep response concise.

    [When to Use]
    - Use this to check what tasks are scheduled for an agent.
    - Use this to monitor task status (pending, processing, completed, failed).

    Args:
        agent_id: Optional filter by agent ID. If not provided, returns tasks for all agents.
        status: Optional filter by status ('pending', 'processing', 'completed', 'failed').
        limit: Maximum number of tasks to return (default 50).

    Returns:
        JSON string containing list of tasks (without full execution content).
    """
    try:
        tasks = db.list_tasks(agent_id=agent_id, status=status, limit=limit)
        # Remove description field to keep response concise
        for task in tasks:
            task.pop('description', None)
        return json.dumps(tasks, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error listing tasks: {str(e)}"


@mcp.tool()
@sage_mcp_tool(server_name="task_scheduler")
async def add_task(
    name: str,
    description: str,
    agent_id: str,
    session_id: str,
    execute_at: str,
    task_type: str = "once"
) -> str:
    """
    Add a new task to the scheduler.

    [Effect]
    - Creates a new task in the database with the specified parameters.
    - The task will be executed at the specified time.
    - Supports recurring tasks (daily, weekly, monthly).

    [When to Use]
    - Use this to schedule a one-time task for an agent.
    - Use this to set up recurring tasks (e.g., daily reports, weekly summaries).

    Args:
        name: The name/title of the task.
        description: Detailed description of what the task should do.
        agent_id: The ID of the agent that will execute this task.
        session_id: The session ID to use when sending the task to the agent.
        execute_at: Execution time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
        task_type: Type of task - 'once' (default), 'daily', 'weekly', or 'monthly'.

    Returns:
        Confirmation message with Task ID.
    """
    try:
        # Validate timestamp format
        datetime.fromisoformat(execute_at)

        # Validate task type
        if task_type not in [t.value for t in TaskType]:
            return "Error: Invalid task_type. Must be one of: once, daily, weekly, monthly"

        task_id = db.add_task(
            name=name,
            description=description,
            agent_id=agent_id,
            session_id=session_id,
            execute_at=execute_at,
            task_type=task_type
        )

        task_type_desc = "recurring" if task_type != "once" else "one-time"
        return f"Task '{name}' (ID: {task_id}) added successfully. Type: {task_type_desc}, Execute at: {execute_at}"

    except ValueError:
        return "Error: Invalid execute_at format. Use ISO 8601 (YYYY-MM-DDTHH:MM:SS)."
    except Exception as e:
        return f"Error adding task: {str(e)}"


@mcp.tool()
@sage_mcp_tool(server_name="task_scheduler")
async def delete_task(task_id: int) -> str:
    """
    Delete a task from the scheduler.

    [Effect]
    - Permanently removes the task and its execution history from the database.
    - This action cannot be undone.

    [When to Use]
    - Use this to cancel a scheduled task.
    - Use this to remove completed or failed tasks that are no longer needed.

    Args:
        task_id: The ID of the task to delete.

    Returns:
        Confirmation message.
    """
    try:
        task = db.get_task(task_id)
        if not task:
            return f"Error: Task {task_id} not found."

        if db.delete_task(task_id):
            return f"Task {task_id} ('{task['name']}') deleted successfully."
        else:
            return f"Error: Failed to delete task {task_id}."
    except Exception as e:
        return f"Error deleting task: {str(e)}"


@mcp.tool()
@sage_mcp_tool(server_name="task_scheduler")
async def complete_task(task_id: int) -> str:
    """
    Mark a task as completed manually.

    [Effect]
    - Updates the task status to 'completed'.
    - Sets the completed_at timestamp.
    - For recurring tasks, this does NOT reschedule them.

    [When to Use]
    - Use this to manually complete a pending task without executing it.
    - Use this to mark a task as done if it was handled outside the scheduler.

    Args:
        task_id: The ID of the task to complete.

    Returns:
        Confirmation message.
    """
    try:
        task = db.get_task(task_id)
        if not task:
            return f"Error: Task {task_id} not found."

        if task['status'] == 'completed':
            return f"Task {task_id} is already completed."

        if db.complete_task(task_id):
            db.add_task_history(task_id, 'completed_manually')
            return f"Task {task_id} ('{task['name']}') marked as completed."
        else:
            return f"Error: Failed to complete task {task_id}."
    except Exception as e:
        return f"Error completing task: {str(e)}"


@mcp.tool()
@sage_mcp_tool(server_name="task_scheduler")
async def get_task_details(task_id: int) -> str:
    """
    Get detailed information about a specific task including execution history.

    [Effect]
    - Retrieves task details and execution history from the database.
    - For execution history, only returns the last 1000 characters of response content.

    [When to Use]
    - Use this to check the full details of a specific task.
    - Use this to review execution history and responses.

    Args:
        task_id: The ID of the task to retrieve.

    Returns:
        JSON string containing task details and history (with truncated response content).
    """
    try:
        task = db.get_task(task_id)
        if not task:
            return f"Error: Task {task_id} not found."

        # Get execution history
        with db._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM task_history WHERE task_id = ? ORDER BY executed_at DESC",
                (task_id,)
            )
            history = [dict(row) for row in cursor.fetchall()]

        # Truncate response content to last 1000 characters
        for entry in history:
            if entry.get('response'):
                response = entry['response']
                if len(response) > 1000:
                    entry['response'] = "...[truncated]" + response[-1000:]

        result = {
            "task": task,
            "history": history
        }

        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error getting task details: {str(e)}"


if __name__ == "__main__":
    mcp.run()
