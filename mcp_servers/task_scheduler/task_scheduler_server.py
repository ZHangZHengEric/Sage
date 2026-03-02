import os
import json
import time
import threading
import logging
import httpx
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from croniter import croniter

from mcp.server.fastmcp import FastMCP
from sagents.tool.mcp_tool_base import sage_mcp_tool

from .db import TaskSchedulerDB

# Initialize FastMCP server
mcp = FastMCP("Task Scheduler Service")

# Constants
logger = logging.getLogger("TaskScheduler")

# Base storage path - use SAGE_ROOT if available, otherwise use current directory
SAGE_ROOT = os.getenv("SAGE_ROOT", os.getcwd())
DB_PATH = Path(SAGE_ROOT) / "sage.db"

# Ensure directory exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
logger.info(f"Task scheduler database: {DB_PATH}")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TaskScheduler")

# Task ID prefixes
ONCE_TASK_PREFIX = "once_"
RECURRING_TASK_PREFIX = "rec_"


def _get_api_base_url() -> str:
    """
    Get the API base URL for the Sage server.
    Since this MCP server runs in the same container as the main server,
    we use localhost with the port from environment or default.
    """
    # Try to get port from environment variable or use default 8080 (desktop app port)
    port = os.getenv("SAGE_PORT", "8080")
    return f"http://localhost:{port}"


# Initialize DB
db = TaskSchedulerDB(DB_PATH)

# Track processing sessions to ensure sequential execution
_processing_sessions: Dict[str, threading.Lock] = {}
_session_lock = threading.Lock()


def _get_session_lock(session_id: str) -> threading.Lock:
    """Get or create a lock for a specific session"""
    with _session_lock:
        if session_id not in _processing_sessions:
            _processing_sessions[session_id] = threading.Lock()
        return _processing_sessions[session_id]


def _encode_task_id(task_id: int, is_recurring: bool = False) -> str:
    """Encode task ID with prefix"""
    prefix = RECURRING_TASK_PREFIX if is_recurring else ONCE_TASK_PREFIX
    return f"{prefix}{task_id}"


def _decode_task_id(encoded_id: str) -> tuple[int, bool]:
    """Decode task ID, returns (task_id, is_recurring)"""
    if encoded_id.startswith(RECURRING_TASK_PREFIX):
        return int(encoded_id[len(RECURRING_TASK_PREFIX):]), True
    elif encoded_id.startswith(ONCE_TASK_PREFIX):
        return int(encoded_id[len(ONCE_TASK_PREFIX):]), False
    else:
        # Fallback: treat as once task without prefix
        return int(encoded_id), False


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
    session_id = task.get('session_id')
    name = task['name']
    description = task['description']

    # Generate a random session_id if not provided (for tasks from other channels)
    if not session_id:
        session_id = f"task_{uuid.uuid4().hex[:12]}"
        logger.info(f"Task {task_id} has no session_id, generated random one: {session_id}")

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
        
        # Mark as completed
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


def _execute_task_with_session_lock(task: Dict[str, Any]) -> None:
    """
    Execute a task with session-level locking to ensure sequential execution
    for tasks in the same session.
    """
    session_id = task.get('session_id')
    task_id = task['id']

    # Generate a random session_id if not provided (for tasks from other channels)
    if not session_id:
        session_id = f"task_{uuid.uuid4().hex[:12]}"
        logger.info(f"Task {task_id} has no session_id for locking, generated random one: {session_id}")

    # Get the lock for this session
    lock = _get_session_lock(session_id)
    
    # Try to claim the task first (atomic operation)
    if not db.claim_task(task_id):
        logger.info(f"Task {task_id} already being processed or not pending. Skipping.")
        return
    
    # Acquire the session lock to ensure sequential execution
    logger.info(f"Acquiring session lock for {session_id} to execute task {task_id}")
    with lock:
        logger.info(f"Session lock acquired for {session_id}, executing task {task_id}")
        _execute_task_sync(task)
        logger.info(f"Task {task_id} execution completed, releasing session lock")


def _check_and_spawn_recurring_tasks():
    """
    Check recurring tasks and spawn one-time task instances if needed.
    This should be called before processing pending tasks.
    """
    now = datetime.now()
    
    # Get all enabled recurring tasks
    recurring_tasks = db.list_recurring_tasks(enabled_only=True)
    
    spawned_count = 0
    for recurring_task in recurring_tasks:
        try:
            task_id = recurring_task['id']
            cron_expr = recurring_task['cron_expression']
            last_executed = recurring_task.get('last_executed_at')
            
            # Parse cron expression
            if not croniter.is_valid(cron_expr):
                logger.warning(f"Invalid cron expression for recurring task {task_id}: {cron_expr}")
                continue
            
            # Check if task should run now
            itr = croniter(cron_expr, last_executed or datetime.min)
            next_run = itr.get_next(datetime)
            
            # If next run time is in the past or very close (within last minute), spawn a task
            if next_run <= now:
                # Check if we already have a pending task for this recurring task
                existing_tasks = db.list_tasks(
                    session_id=recurring_task['session_id'],
                    status='pending',
                    limit=100
                )
                
                # Check if there's already a pending instance of this recurring task
                has_pending_instance = any(
                    t.get('recurring_task_id') == task_id for t in existing_tasks
                )
                
                if not has_pending_instance:
                    # Create a one-time task instance
                    execute_at = now.isoformat()
                    new_task_id = db.add_task(
                        name=recurring_task['name'],
                        description=recurring_task['description'],
                        agent_id=recurring_task['agent_id'],
                        session_id=recurring_task['session_id'],
                        execute_at=execute_at,
                        recurring_task_id=task_id
                    )
                    logger.info(f"Spawned one-time task {new_task_id} from recurring task {task_id}")
                    spawned_count += 1
                
                # Update last_executed_at
                db.update_recurring_task_last_executed(task_id)
                
        except Exception as e:
            logger.error(f"Error processing recurring task {recurring_task.get('id')}: {e}")
    
    if spawned_count > 0:
        logger.info(f"Spawned {spawned_count} tasks from recurring tasks")


def scheduler_loop():
    """
    Background loop to check for pending tasks.
    
    Logic:
    1. First, check recurring tasks and spawn one-time instances if needed
    2. Then, process pending tasks grouped by session_id (sequential execution per session)
    """
    logger.info("Task scheduler started.")
    logger.info(f"API Base URL: {_get_api_base_url()}")
    
    while True:
        try:
            # Step 1: Check recurring tasks and spawn instances
            _check_and_spawn_recurring_tasks()
            
            # Step 2: Get all pending tasks that are due
            pending_tasks = db.get_pending_tasks()
            
            if pending_tasks:
                logger.info(f"Found {len(pending_tasks)} pending tasks to execute")
                
                # Group tasks by session_id
                tasks_by_session: Dict[str, List[Dict]] = {}
                for task in pending_tasks:
                    session_id = task['session_id']
                    if session_id not in tasks_by_session:
                        tasks_by_session[session_id] = []
                    tasks_by_session[session_id].append(task)
                
                # Process tasks for each session
                for session_id, tasks in tasks_by_session.items():
                    logger.info(f"Processing {len(tasks)} tasks for session {session_id}")
                    
                    # For each session, only the first task will be executed immediately
                    # (acquiring the lock), others will wait for the lock
                    for task in tasks:
                        try:
                            # Start task in separate thread with session lock
                            task_thread = threading.Thread(
                                target=_execute_task_with_session_lock,
                                args=(task,),
                                daemon=True,
                                name=f"TaskExecutor-{task['id']}"
                            )
                            task_thread.start()
                            logger.info(f"Task {task['id']} started in thread {task_thread.name}")
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
async def list_tasks(agent_id: Optional[str] = None, status: Optional[str] = None, include_recurring: bool = True, limit: int = 50) -> str:
    """
    List tasks (both one-time and recurring) for a specific agent or all tasks.

    [Effect]
    - Retrieves a list of tasks from the task scheduler database.
    - Can be filtered by agent_id and/or status.
    - Returns task details including name, description, execution time, and status.
    - One-time tasks have IDs starting with 'once_'
    - Recurring tasks have IDs starting with 'rec_'

    [When to Use]
    - Use this to check what tasks are scheduled for an agent.
    - Use this to monitor task status (pending, processing, completed, failed).

    Args:
        agent_id: Optional filter by agent ID. If not provided, returns tasks for all agents.
        status: Optional filter by status ('pending', 'processing', 'completed', 'failed'). Only applies to one-time tasks.
        include_recurring: Whether to include recurring task templates. Default True.
        limit: Maximum number of tasks to return (default 50).

    Returns:
        JSON string containing list of tasks with task_type field ('once' or 'recurring').
    """
    try:
        result = []
        
        # Get one-time tasks
        once_tasks = db.list_tasks(agent_id=agent_id, status=status, limit=limit)
        for task in once_tasks:
            task['task_id'] = _encode_task_id(task['id'], is_recurring=False)
            task['task_type'] = 'once'
            task.pop('id', None)  # Remove raw id
            task.pop('description', None)  # Keep response concise
            result.append(task)
        
        # Get recurring tasks if requested
        if include_recurring:
            recurring_tasks = db.list_recurring_tasks(agent_id=agent_id)
            for task in recurring_tasks:
                task['task_id'] = _encode_task_id(task['id'], is_recurring=True)
                task['task_type'] = 'recurring'
                task.pop('id', None)  # Remove raw id
                task.pop('description', None)  # Keep response concise
                result.append(task)
        
        return json.dumps(result[:limit], indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error listing tasks: {str(e)}"


@mcp.tool()
@sage_mcp_tool(server_name="task_scheduler")
async def add_task(
    name: str,
    description: str,
    agent_id: str,
    session_id: str,
    schedule: str,
    is_recurring: bool = False
) -> str:
    """
    Add a new task to the scheduler.

    [Effect]
    - Creates a new task in the database with the specified parameters.
    - For one-time tasks: schedule is execute time in ISO format
    - For recurring tasks: schedule is a cron expression

    [When to Use]
    - Use this to schedule a one-time task for an agent (set is_recurring=False).
    - Use this to set up recurring tasks like daily reports (set is_recurring=True).

    Args:
        name: The name/title of the task.
        description: Detailed description of what the task should do.
        agent_id: The ID of the agent that will execute this task.
        session_id: The session ID to use when sending the task to the agent.
        schedule: For one-time: execution time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
                 For recurring: cron expression (e.g., "0 9 * * *" for daily at 9 AM).
        is_recurring: Whether this is a recurring task. Default False.

    Returns:
        Confirmation message with Task ID (prefixed with 'once_' or 'rec_').
    """
    try:

        if is_recurring:
            # Validate cron expression
            if not croniter.is_valid(schedule):
                return "Error: Invalid schedule for recurring task. Use standard cron format (e.g., '0 9 * * *')."

            task_id = db.add_recurring_task(
                name=name,
                description=description,
                agent_id=agent_id,
                session_id=session_id,
                cron_expression=schedule
            )
            encoded_id = _encode_task_id(task_id, is_recurring=True)
            return f"Recurring task '{name}' (ID: {encoded_id}) added successfully. Cron: {schedule}"
        else:
            # Validate timestamp format
            datetime.fromisoformat(schedule)

            task_id = db.add_task(
                name=name,
                description=description,
                agent_id=agent_id,
                session_id=session_id,
                execute_at=schedule
            )
            encoded_id = _encode_task_id(task_id, is_recurring=False)
            return f"Task '{name}' (ID: {encoded_id}) added successfully. Execute at: {schedule}"

    except ValueError:
        return "Error: Invalid schedule format. For one-time tasks use ISO 8601 (YYYY-MM-DDTHH:MM:SS)."
    except Exception as e:
        return f"Error adding task: {str(e)}"


@mcp.tool()
@sage_mcp_tool(server_name="task_scheduler")
async def delete_task(task_id: str) -> str:
    """
    Delete a task from the scheduler.

    [Effect]
    - For one-time tasks (once_*): Permanently removes the task and its execution history.
    - For recurring tasks (rec_*): Removes the template and all pending instances.
    - This action cannot be undone.

    [When to Use]
    - Use this to cancel a scheduled task.
    - Use this to remove completed or failed tasks that are no longer needed.

    Args:
        task_id: The ID of the task to delete (e.g., 'once_123' or 'rec_456').

    Returns:
        Confirmation message.
    """
    try:
        raw_id, is_recurring = _decode_task_id(task_id)
        
        if is_recurring:
            task = db.get_recurring_task(raw_id)
            if not task:
                return f"Error: Recurring task {task_id} not found."

            if db.delete_recurring_task(raw_id):
                return f"Recurring task {task_id} ('{task['name']}') and pending instances deleted successfully."
            else:
                return f"Error: Failed to delete recurring task {task_id}."
        else:
            task = db.get_task(raw_id)
            if not task:
                return f"Error: Task {task_id} not found."

            if db.delete_task(raw_id):
                return f"Task {task_id} ('{task['name']}') deleted successfully."
            else:
                return f"Error: Failed to delete task {task_id}."
    except Exception as e:
        return f"Error deleting task: {str(e)}"


@mcp.tool()
@sage_mcp_tool(server_name="task_scheduler")
async def complete_task(task_id: str) -> str:
    """
    Mark a task as completed manually.

    [Effect]
    - For one-time tasks (once_*): Updates status to 'completed' and sets completed_at timestamp.
    - For recurring tasks (rec_*): Updates the last_executed_at timestamp.

    [When to Use]
    - Use this to manually complete a pending task without executing it.
    - Use this to mark a task as done if it was handled outside the scheduler.

    Args:
        task_id: The ID of the task to complete (e.g., 'once_123' or 'rec_456').

    Returns:
        Confirmation message.
    """
    try:
        raw_id, is_recurring = _decode_task_id(task_id)
        
        if is_recurring:
            task = db.get_recurring_task(raw_id)
            if not task:
                return f"Error: Recurring task {task_id} not found."

            db.update_recurring_task_last_executed(raw_id)
            return f"Recurring task {task_id} ('{task['name']}') marked as executed."
        else:
            task = db.get_task(raw_id)
            if not task:
                return f"Error: Task {task_id} not found."

            if task['status'] == 'completed':
                return f"Task {task_id} is already completed."

            if db.complete_task(raw_id):
                db.add_task_history(raw_id, 'completed_manually')
                return f"Task {task_id} ('{task['name']}') marked as completed."
            else:
                return f"Error: Failed to complete task {task_id}."
    except Exception as e:
        return f"Error completing task: {str(e)}"


@mcp.tool()
@sage_mcp_tool(server_name="task_scheduler")
async def enable_task(task_id: str, enabled: bool = True) -> str:
    """
    Enable or disable a recurring task.

    [Effect]
    - Only applies to recurring tasks (rec_*).
    - Enables or disables the recurring task template.
    - Disabled recurring tasks will not spawn new one-time task instances.

    [When to Use]
    - Use this to temporarily pause a recurring task.
    - Use this to resume a paused recurring task.

    Args:
        task_id: The ID of the recurring task (e.g., 'rec_456').
        enabled: True to enable, False to disable.

    Returns:
        Confirmation message.
    """
    try:
        raw_id, is_recurring = _decode_task_id(task_id)
        
        if not is_recurring:
            return f"Error: Task {task_id} is not a recurring task. Only recurring tasks can be enabled/disabled."
        
        task = db.get_recurring_task(raw_id)
        if not task:
            return f"Error: Recurring task {task_id} not found."

        if db.enable_recurring_task(raw_id, enabled):
            status = "enabled" if enabled else "disabled"
            return f"Recurring task {task_id} ('{task['name']}') {status} successfully."
        else:
            return f"Error: Failed to update recurring task {task_id}."
    except Exception as e:
        return f"Error updating recurring task: {str(e)}"


@mcp.tool()
@sage_mcp_tool(server_name="task_scheduler")
async def get_task_details(task_id: str) -> str:
    """
    Get detailed information about a specific task.

    [Effect]
    - For one-time tasks (once_*): Retrieves task details and execution history.
    - For recurring tasks (rec_*): Retrieves recurring task template details.
    - For execution history, only returns the last 1000 characters of response content.

    [When to Use]
    - Use this to check the full details of a specific task.
    - Use this to review execution history and responses.

    Args:
        task_id: The ID of the task to retrieve (e.g., 'once_123' or 'rec_456').

    Returns:
        JSON string containing task details and history.
    """
    try:
        raw_id, is_recurring = _decode_task_id(task_id)
        
        if is_recurring:
            task = db.get_recurring_task(raw_id)
            if not task:
                return f"Error: Recurring task {task_id} not found."

            task['task_id'] = task_id
            task['task_type'] = 'recurring'
            task.pop('id', None)
            return json.dumps(task, indent=2, ensure_ascii=False)
        else:
            task = db.get_task(raw_id)
            if not task:
                return f"Error: Task {task_id} not found."

            # Get execution history
            history = db.get_task_history(raw_id, limit=10)

            # Truncate response content to last 1000 characters
            for entry in history:
                if entry.get('response'):
                    response = entry['response']
                    if len(response) > 1000:
                        entry['response'] = "...[truncated]" + response[-1000:]

            task['task_id'] = task_id
            task['task_type'] = 'once'
            task.pop('id', None)
            
            result = {
                "task": task,
                "history": history
            }

            return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error getting task details: {str(e)}"


if __name__ == "__main__":
    mcp.run()
