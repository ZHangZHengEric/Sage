import os
import json
import time
import threading
import logging
import httpx
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

# Initialize logger first (before any imports that might use it)
logger = logging.getLogger("TaskScheduler")

# Configure logging if not already configured
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("TaskScheduler logger initialized")

# Try to import croniter, fallback to simple implementation if not available
try:
    from croniter import croniter
    CRONITER_AVAILABLE = True
except ImportError:
    CRONITER_AVAILABLE = False
    logger.warning("croniter not available, using simple cron validation")
    
    class SimpleCroniter:
        """Simple cron parser fallback"""
        @staticmethod
        def is_valid(cron_string: str) -> bool:
            """Basic cron validation (5 fields: min hour day month dow)"""
            parts = cron_string.split()
            if len(parts) != 5:
                return False
            return True
        
        def __init__(self, cron_string: str, start_time=None):
            self.cron_string = cron_string
            self.start_time = start_time or datetime.now().astimezone().replace(tzinfo=None)
        
        def get_next(self, ret_type=None):
            """Return next run time (simplified - just returns current time + 1 minute)"""
            return self.start_time + timedelta(minutes=1)
    
    croniter = SimpleCroniter

from mcp.server.fastmcp import FastMCP
from sagents.tool.mcp_tool_base import sage_mcp_tool

from .db import TaskSchedulerDB

# Initialize FastMCP server
mcp = FastMCP("Task Scheduler Service")

# Base storage path - use SAGE_ROOT if available, otherwise use current directory
SAGE_ROOT = os.getenv("SAGE_ROOT", os.getcwd())
DB_PATH = Path(SAGE_ROOT) / "sage.db"

# Ensure directory exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
logger.debug(f"Task scheduler database: {DB_PATH}")

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
    name = task['name']
    description = task['description']

    logger.info(f"[TASK EXECUTION] Starting task {task_id} for agent {agent_id} with task name: {name} and description: {description}")
    logger.debug(f"[TASK EXECUTION] Task name: {name}")
    logger.debug(f"[TASK EXECUTION] Task description: {description}")

    try:
        # Prepare the message content
        content = f"【定时任务】{name}\n\n{description}" if description else f"【定时任务】{name}"

        # Note: session_id is not passed - backend will auto-generate it
        payload = {
            "agent_id": agent_id,
            "messages": [{"role": "user", "content": content}],
            "force_summary": True,
            "user_id": "task_scheduler"
        }

        api_base_url = _get_api_base_url()
        logger.info(f"[TASK EXECUTION] Sending task {task_id} to agent {agent_id}")
        logger.debug(f"[TASK EXECUTION] API URL: {api_base_url}/api/chat")
        logger.debug(f"[TASK EXECUTION] Payload: {json.dumps(payload, ensure_ascii=False)}")

        full_response_text = ""

        # Use synchronous client inside the thread
        with httpx.Client(timeout=300.0) as client:
            logger.debug(f"[TASK EXECUTION] HTTP client created, sending POST request...")
            with client.stream("POST", f"{api_base_url}/api/chat", json=payload, headers={"X-Sage-Internal-UserId": "task_scheduler"}) as response:
                logger.debug(f"[TASK EXECUTION] Response received, status: {response.status_code}")
                response.raise_for_status()
                full_response_text = _parse_stream_response(response)

        logger.info(f"[TASK EXECUTION] Task {task_id} completed successfully. Response length: {len(full_response_text)}")
        logger.debug(f"[TASK EXECUTION] Response preview: {full_response_text[:200]}...")

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


def _execute_task(task: Dict[str, Any]) -> None:
    """
    Execute a task by claiming it first, then running it.
    Tasks are executed concurrently (no session-level locking needed since backend auto-generates session_id).
    """
    task_id = task['id']
    
    logger.debug(f"[TASK EXECUTION] Attempting to claim task {task_id}")
    
    # Try to claim the task first (atomic operation)
    if not db.claim_task(task_id):
        logger.info(f"[TASK EXECUTION] Task {task_id} already being processed or not pending. Skipping.")
        return
    
    # Execute the task
    logger.info(f"[TASK EXECUTION] Task {task_id} claimed successfully, starting execution")
    try:
        _execute_task_sync(task)
        logger.info(f"[TASK EXECUTION] Task {task_id} execution completed successfully")
    except Exception as e:
        logger.error(f"[TASK EXECUTION] Task {task_id} execution failed: {e}", exc_info=True)
        raise


def _check_and_spawn_recurring_tasks():
    """
    Check recurring tasks and spawn one-time task instances if needed.
    This should be called before processing pending tasks.
    """
    now = datetime.now().astimezone().replace(tzinfo=None)
    
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
            # All times should be timezone-aware for consistency
            local_tz = datetime.now().astimezone().tzinfo
            
            last_executed_dt = last_executed
            is_new_task = False
            if isinstance(last_executed_dt, str):
                try:
                    # Fix for SQLite default timestamp format (space instead of T)
                    # And user preference for space separated format
                    if "T" not in last_executed_dt:
                        last_executed_dt = datetime.strptime(last_executed_dt, "%Y-%m-%d %H:%M:%S")
                    else:
                        last_executed_dt = datetime.fromisoformat(last_executed_dt)
                except ValueError:
                    # Fallback
                    try:
                        last_executed_dt = datetime.fromisoformat(last_executed_dt.replace(' ', 'T'))
                    except Exception:
                        last_executed_dt = None
            else:
                 last_executed_dt = None
                 is_new_task = True
            
            # We use timezone-aware time for comparison
            now_aware = datetime.now().astimezone()
            
            # If last_executed_dt is None (new task), create an instance immediately
            if is_new_task:
                logger.info(f"Recurring task {task_id}: last_executed_at is null, creating first instance immediately")
                # Create task with current time as execute_at
                execute_at = now_aware.strftime("%Y-%m-%d %H:%M:%S")
                new_task_id = db.add_task(
                    name=recurring_task['name'],
                    description=recurring_task['description'],
                    agent_id=recurring_task['agent_id'],
                    execute_at=execute_at,
                    recurring_task_id=task_id
                )
                logger.info(f"Spawned first one-time task {new_task_id} from recurring task {task_id}, will execute immediately")
                spawned_count += 1
                
                # Update last_executed_at to current time
                db.update_recurring_task_last_executed(task_id, now_aware.strftime("%Y-%m-%d %H:%M:%S"))
                continue

            # Ensure last_executed_dt is timezone-aware (add local timezone if naive)
            if last_executed_dt.tzinfo is None:
                 last_executed_dt = last_executed_dt.replace(tzinfo=local_tz)
            
            # croniter expects naive datetime if we provide naive start_time
            # or aware if we provide aware.
            # We provide aware start_time to get aware next_run
            
            itr = croniter(cron_expr, last_executed_dt)
            next_run = itr.get_next(datetime)
            
            # Skip historical missed runs (system was down for a long time)
            # Find the next run time that is in the future
            while next_run <= now_aware:
                next_run = itr.get_next(datetime)
            
            # Now next_run is in the future
            # Check if we should spawn it (if it's within the next minute)
            # This ensures tasks are spawned just-in-time for execution
            if next_run <= now_aware + timedelta(minutes=1):
                # Check if we already have a pending task for this recurring task
                existing_tasks = db.list_tasks(
                    agent_id=recurring_task['agent_id'],
                    status='pending',
                    limit=100
                )
                
                # Check if there's already a pending instance of this recurring task
                has_pending_instance = any(
                    str(t.get('recurring_task_id')) == str(task_id) for t in existing_tasks
                )
                
                if not has_pending_instance:
                    # Create a one-time task instance
                    # Use current time as execute_at to ensure it runs immediately
                    # (within the next scheduler loop iteration)
                    execute_at = now_aware.strftime("%Y-%m-%d %H:%M:%S")
                    new_task_id = db.add_task(
                        name=recurring_task['name'],
                        description=recurring_task['description'],
                        agent_id=recurring_task['agent_id'],
                        execute_at=execute_at,
                        recurring_task_id=task_id
                    )
                    logger.info(f"Spawned one-time task {new_task_id} from recurring task {task_id}, will execute immediately")
                    spawned_count += 1
                    
                    # Update last_executed_at to the scheduled run time (next_run)
                    # This ensures we don't re-process this scheduled time
                    db.update_recurring_task_last_executed(task_id, next_run.strftime("%Y-%m-%d %H:%M:%S"))
                else:
                    # Already has pending, just update last_executed to avoid re-processing
                    db.update_recurring_task_last_executed(task_id, next_run.strftime("%Y-%m-%d %H:%M:%S"))
            else:
                # Next run is too far in the future, skip for now
                # Don't update last_executed_at, we'll check again in the next loop
                logger.debug(f"Recurring task {task_id}: next run at {next_run} is more than 1 minute away, skipping for now")
                
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
    logger.info("[SCHEDULER] Task scheduler started.")
    logger.info(f"[SCHEDULER] API Base URL: {_get_api_base_url()}")
    logger.info(f"[SCHEDULER] Database path: {db.db_path}")
    
    loop_count = 0
    
    while True:
        loop_count += 1
        try:
            logger.debug(f"[SCHEDULER] === Loop iteration {loop_count} ===")
            
            # Step 1: Check recurring tasks and spawn instances
            logger.debug("[SCHEDULER] Checking recurring tasks...")
            _check_and_spawn_recurring_tasks()
            
            # Step 2: Get all pending tasks that are due
            logger.debug("[SCHEDULER] Getting pending tasks...")
            pending_tasks = db.get_pending_tasks()
            
            if pending_tasks:
                logger.info(f"[SCHEDULER] Found {len(pending_tasks)} pending tasks to execute")
                
                # Process all pending tasks concurrently
                # (no session-level locking needed since backend auto-generates session_id)
                for task in pending_tasks:
                    try:
                        task_id = task['id']
                        logger.info(f"[SCHEDULER] Starting task {task_id} in new thread")
                        
                        # Start task in separate thread
                        task_thread = threading.Thread(
                            target=_execute_task,
                            args=(task,),
                            daemon=True,
                            name=f"TaskExecutor-{task_id}"
                        )
                        task_thread.start()
                        logger.info(f"[SCHEDULER] Task {task_id} started in thread {task_thread.name}")
                    except Exception as e:
                        logger.error(f"[SCHEDULER] Failed to start task {task['id']}: {e}", exc_info=True)
            else:
                logger.debug("[SCHEDULER] No pending tasks found")
                            
        except Exception as e:
            logger.error(f"[SCHEDULER] Scheduler error in loop {loop_count}: {e}", exc_info=True)

        logger.debug(f"[SCHEDULER] Sleeping for 5 seconds...")
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
    schedule: str,
    is_recurring: bool = False
) -> str:
    """
    添加新任务到调度器。

    [功能]
    - 创建一次性任务或循环任务到数据库。
    - 一次性任务：在指定时间执行一次。
    - 循环任务：按照 cron 表达式定期执行。

    [使用场景]
    - 创建一次性任务：设置 is_recurring=False，提供具体的执行时间。
    - 创建循环任务：设置 is_recurring=True，提供 cron 表达式（如每天9点执行）。

    [重要说明]
    - 对于循环任务，description 应该是单次执行的具体任务描述。
    - 不要将循环任务本身的描述（如"每天执行"）写入 description。
    - 例如：循环任务是"每日报告"，description 应该是"生成今日销售数据报告"，而不是"每天生成报告"。

    Args:
        name: 任务名称/标题。
        description: 单次任务的具体描述（说明这次要做什么，不要包含循环信息）。
        agent_id: 执行此任务的 Agent ID。
        schedule: 一次性任务：执行时间，格式 "YYYY-MM-DD HH:MM:SS" 或 ISO 8601。
                 循环任务：cron 表达式（如 "0 9 * * *" 表示每天上午9点）。
        is_recurring: 是否为循环任务。默认 False。

    Returns:
        包含任务 ID 的确认消息（一次性任务前缀为 'once_'，循环任务前缀为 'rec_'）。
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
                cron_expression=schedule
            )
            encoded_id = _encode_task_id(task_id, is_recurring=True)
            return f"Recurring task '{name}' (ID: {encoded_id}) added successfully. Cron: {schedule}"
        else:
            # Validate timestamp format and normalize to local time clean string
            try:
                dt = None
                if "T" in schedule:
                    dt = datetime.fromisoformat(schedule)
                else:
                    dt = datetime.strptime(schedule, "%Y-%m-%d %H:%M:%S")
                
                # If aware, convert to local time first
                if dt.tzinfo is not None:
                    dt = dt.astimezone()
                
                # Format as clean string (YYYY-MM-DD HH:MM:SS) without timezone info
                # The DB expects local time in this format
                execute_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                
            except ValueError:
                 # Try fallback
                 try:
                     dt = datetime.fromisoformat(schedule.replace(" ", "T"))
                     if dt.tzinfo is not None:
                         dt = dt.astimezone()
                     execute_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                 except ValueError:
                     raise ValueError("Invalid format")

            task_id = db.add_task(
                name=name,
                description=description,
                agent_id=agent_id,
                execute_at=execute_at
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


@mcp.tool()
@sage_mcp_tool(server_name="task_scheduler")
async def update_task(
    task_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    agent_id: Optional[str] = None,
    schedule: Optional[str] = None,
    enabled: Optional[bool] = None,
    max_retries: Optional[int] = None
) -> str:
    """
    Update an existing task in the scheduler.

    [Effect]
    - For one-time tasks (once_*): Updates name, description, agent_id, execute_at, or max_retries.
    - For recurring tasks (rec_*): Updates name, description, agent_id, cron_expression, or enabled.
    - Only provided fields will be updated; fields not provided remain unchanged.

    [When to Use]
    - Use this to modify a scheduled task's details.
    - Use this to change the execution time of a one-time task.
    - Use this to change the cron schedule of a recurring task.
    - Use this to enable/disable a recurring task.

    Args:
        task_id: The ID of the task to update (e.g., 'once_123' or 'rec_456').
        name: New task name/title (optional).
        description: New task description (optional).
        agent_id: New agent ID to execute the task (optional).
        schedule: New schedule - ISO 8601 for one-time, cron expression for recurring (optional).
        enabled: Enable/disable recurring task (True/False, only for recurring tasks).
        max_retries: New max retry count (only for one-time tasks).

    Returns:
        Confirmation message with updated fields.
    """
    try:
        raw_id, is_recurring = _decode_task_id(task_id)
        
        if is_recurring:
            # Validate cron expression if provided
            if schedule is not None:
                if not croniter.is_valid(schedule):
                    return f"Error: Invalid cron expression '{schedule}'. Use format like '0 9 * * *'."
            
            # Build update kwargs
            update_kwargs = {}
            if name is not None:
                update_kwargs['name'] = name
            if description is not None:
                update_kwargs['description'] = description
            if agent_id is not None:
                update_kwargs['agent_id'] = agent_id
            if schedule is not None:
                update_kwargs['cron_expression'] = schedule
            if enabled is not None:
                update_kwargs['enabled'] = enabled
            
            if not update_kwargs:
                return "Error: No fields to update."
            
            task = db.get_recurring_task(raw_id)
            if not task:
                return f"Error: Recurring task {task_id} not found."
            
            if db.update_recurring_task(raw_id, **update_kwargs):
                updated_fields = ", ".join(update_kwargs.keys())
                return f"Recurring task {task_id} updated successfully. Fields updated: {updated_fields}."
            else:
                return f"Error: Failed to update recurring task {task_id}."
        else:
            # Validate execute_at timestamp if provided
            normalized_schedule = None
            if schedule is not None:
                try:
                    dt = None
                    if "T" in schedule:
                        dt = datetime.fromisoformat(schedule)
                    else:
                        dt = datetime.strptime(schedule, "%Y-%m-%d %H:%M:%S")
                    
                    # If aware, convert to local time first
                    if dt.tzinfo is not None:
                        dt = dt.astimezone()
                    
                    # Format as clean string
                    normalized_schedule = dt.strftime("%Y-%m-%d %H:%M:%S")
                    
                except ValueError:
                    return f"Error: Invalid schedule format '{schedule}'. Use ISO 8601 (YYYY-MM-DDTHH:MM:SS) or 'YYYY-MM-DD HH:MM:SS'."
            
            # Build update kwargs
            update_kwargs = {}
            if name is not None:
                update_kwargs['name'] = name
            if description is not None:
                update_kwargs['description'] = description
            if agent_id is not None:
                update_kwargs['agent_id'] = agent_id
            if normalized_schedule is not None:
                update_kwargs['execute_at'] = normalized_schedule
            if max_retries is not None:
                update_kwargs['max_retries'] = max_retries
            
            if not update_kwargs:
                return "Error: No fields to update."
            
            task = db.get_task(raw_id)
            if not task:
                return f"Error: Task {task_id} not found."
            
            # Check if task can be updated (not processing or completed)
            if task['status'] in ['processing', 'completed']:
                return f"Error: Cannot update task {task_id} with status '{task['status']}'. Only pending or failed tasks can be updated."
            
            if db.update_task(raw_id, **update_kwargs):
                updated_fields = ", ".join(update_kwargs.keys())
                return f"Task {task_id} updated successfully. Fields updated: {updated_fields}."
            else:
                return f"Error: Failed to update task {task_id}."
                
    except ValueError as e:
        return f"Error: Invalid value - {str(e)}"
    except Exception as e:
        return f"Error updating task: {str(e)}"


if __name__ == "__main__":
    mcp.run()
