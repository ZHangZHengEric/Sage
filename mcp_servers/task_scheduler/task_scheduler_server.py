import os
import json
import time
import threading
import logging
import httpx
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

# Initialize FastMCP server
mcp = FastMCP("Task Scheduler Service")

# Task ID prefixes
ONCE_TASK_PREFIX = "once_"
RECURRING_TASK_PREFIX = "rec_"
SCHEDULER_USER_ID = os.getenv("SAGE_TASK_SCHEDULER_USER_ID", "task_scheduler")


def _get_api_base_url() -> str:
    """
    Get the API base URL for the Sage server.
    Since this MCP server runs in the same container as the main server,
    we use localhost with the port from environment or default.
    """
    # Try to get port from environment variable or use default 8080 (desktop app port)
    port = os.getenv("SAGE_PORT", "8080")
    return f"http://localhost:{port}"


def _internal_headers() -> Dict[str, str]:
    return {"X-Sage-Internal-UserId": SCHEDULER_USER_ID}


def _request_json(
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0,
) -> Any:
    url = f"{_get_api_base_url()}{path}"
    with httpx.Client(timeout=timeout, headers=_internal_headers()) as client:
        response = client.request(method, url, json=json_body, params=params)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()


def _parse_schedule_to_local_str(schedule: str) -> str:
    try:
        dt = datetime.fromisoformat(schedule) if "T" in schedule else datetime.strptime(schedule, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        dt = datetime.fromisoformat(schedule.replace(" ", "T"))
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _fetch_one_time_task(raw_id: int) -> Optional[Dict[str, Any]]:
    try:
        return _request_json("GET", f"/tasks/one-time/{raw_id}")
    except Exception:
        return None


def _fetch_recurring_task(raw_id: int) -> Optional[Dict[str, Any]]:
    try:
        return _request_json("GET", f"/tasks/recurring/{raw_id}")
    except Exception:
        return None


def _fetch_one_time_task_history(raw_id: int, limit: int = 10) -> list[Dict[str, Any]]:
    try:
        data = _request_json("GET", f"/tasks/one-time/{raw_id}/history", params={"limit": limit})
        return data if isinstance(data, list) else []
    except Exception:
        return []

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
    task_id = int(task['id'])
    agent_id = task['agent_id']
    name = task['name']
    description = task['description']

    logger.info(f"[TASK EXECUTION] Starting task {task_id} for agent {agent_id} with task name: {name} and description: {description}")
    logger.debug(f"[TASK EXECUTION] Task name: {name}")
    logger.debug(f"[TASK EXECUTION] Task description: {description}")

    try:
        # Prepare the message content
        content = f"【任务消息】{description} \n 执行过程中严禁添加定时任务" if description else f"【任务消息】{name} \n 执行过程中严禁添加定时任务"

        # Note: session_id is not passed - backend will auto-generate it
        payload = {
            "agent_id": agent_id,
            "messages": [{"role": "user", "content": content}],
            "force_summary": True,
            "user_id": SCHEDULER_USER_ID
        }

        api_base_url = _get_api_base_url()
        logger.info(f"[TASK EXECUTION] Sending task {task_id} to agent {agent_id}")
        logger.debug(f"[TASK EXECUTION] API URL: {api_base_url}/api/chat")
        logger.debug(f"[TASK EXECUTION] Payload: {json.dumps(payload, ensure_ascii=False)}")

        full_response_text = ""

        # Use synchronous client inside the thread
        with httpx.Client(timeout=300.0) as client:
            logger.debug(f"[TASK EXECUTION] HTTP client created, sending POST request...")
            with client.stream("POST", f"{api_base_url}/api/chat", json=payload, headers=_internal_headers()) as response:
                logger.debug(f"[TASK EXECUTION] Response received, status: {response.status_code}")
                response.raise_for_status()
                full_response_text = _parse_stream_response(response)

        logger.info(f"[TASK EXECUTION] Task {task_id} completed successfully. Response length: {len(full_response_text)}")
        logger.debug(f"[TASK EXECUTION] Response preview: {full_response_text[:200]}...")

        _request_json(
            "POST",
            f"/tasks/internal/one-time/{task_id}/complete",
            json_body={"response": full_response_text},
        )

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to execute task {task_id}: {error_msg}")

        _request_json(
            "POST",
            f"/tasks/internal/one-time/{task_id}/fail",
            json_body={"error_message": error_msg},
        )

        retry_count = int(task.get('retry_count', 0)) + 1
        max_retries = int(task.get('max_retries', 3))
        if retry_count <= max_retries:
            logger.info(f"Task {task_id} will be retried ({retry_count}/{max_retries})")
        else:
            logger.info(f"Task {task_id} failed after {max_retries} retries")


def _execute_task(task: Dict[str, Any]) -> None:
    """
    Execute a task by claiming it first, then running it.
    Tasks are executed concurrently (no session-level locking needed since backend auto-generates session_id).
    """
    task_id = int(task['id'])
    
    logger.debug(f"[TASK EXECUTION] Attempting to claim task {task_id}")
    
    # Try to claim the task first (atomic operation)
    claim_result = _request_json("POST", f"/tasks/internal/one-time/{task_id}/claim")
    if not claim_result or not claim_result.get("claimed"):
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
    try:
        result = _request_json("POST", "/tasks/internal/spawn-due")
        spawned_count = len((result or {}).get("items") or [])
        if spawned_count > 0:
            logger.info(f"Spawned {spawned_count} tasks from recurring tasks")
    except Exception as e:
        logger.error(f"Error spawning recurring tasks: {e}")


def scheduler_loop():
    """
    Background loop to check for pending tasks.
    
    Logic:
    1. First, check recurring tasks and spawn one-time instances if needed
    2. Then, process pending tasks grouped by session_id (sequential execution per session)
    """
    logger.info("[SCHEDULER] Task scheduler started.")
    logger.info(f"[SCHEDULER] API Base URL: {_get_api_base_url()}")
    
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
            due_result = _request_json("GET", "/tasks/internal/due", params={"limit": 200})
            pending_tasks = (due_result or {}).get("items") or []
            
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
async def list_tasks(
    task_type: str = "once",
    status: Optional[str] = None,
    scheduled_after: Optional[str] = None,
    scheduled_before: Optional[str] = None,
    limit: int = 50
) -> str:
    """
    List tasks from the task scheduler database with flexible filtering.

    [Effect]
    - Retrieves a list of tasks (one-time tasks and/or recurring task templates).
    - One-time tasks have IDs starting with 'once_'
    - Recurring tasks have IDs starting with 'rec_'

    [When to Use]
    - Use this to check what tasks are scheduled.
    - Use this to monitor task status (pending, processing, completed, failed).
    - Use time range filters to find tasks in a specific period.

    Args:
        task_type: Type of tasks to list. Options:
                   - "once": Only one-time tasks (supports status and time filters)
                   - "recurring": Only recurring task templates (no status/time filters)
                   - "all": Both one-time and recurring tasks
        status: Filter by status ('pending', 'processing', 'completed', 'failed').
                Only applies to one-time tasks. Ignored for recurring tasks.
        scheduled_after: Filter one-time tasks scheduled after this time.
                         Format: "YYYY-MM-DD HH:MM:SS" or ISO 8601.
                         Only applies to one-time tasks.
        scheduled_before: Filter one-time tasks scheduled before this time.
                          Format: "YYYY-MM-DD HH:MM:SS" or ISO 8601.
                          Only applies to one-time tasks.
        limit: Maximum number of tasks to return (default 50).

    Returns:
        JSON string containing list of tasks with task_type field ('once' or 'recurring').

    Examples:
        # List pending one-time tasks
        list_tasks(task_type="once", status="pending")

        # List tasks scheduled for today
        list_tasks(task_type="once", scheduled_after="2024-03-15 00:00:00", scheduled_before="2024-03-15 23:59:59")

        # List recurring task templates
        list_tasks(task_type="recurring")

        # List all tasks (limited to 50)
        list_tasks(task_type="all")
    """
    try:
        result = []

        # Validate task_type
        if task_type not in ("once", "recurring", "all"):
            return f"Error: Invalid task_type '{task_type}'. Must be 'once', 'recurring', or 'all'."

        if task_type in ("once", "all"):
            once_data = _request_json("GET", "/tasks/one-time", params={"page": 1, "page_size": max(limit, 100)})
            once_tasks = (once_data or {}).get("items") or []
            normalized_after = _parse_schedule_to_local_str(scheduled_after) if scheduled_after else None
            normalized_before = _parse_schedule_to_local_str(scheduled_before) if scheduled_before else None
            for task in once_tasks:
                execute_at = str(task.get("execute_at") or "")
                if status and task.get("status") != status:
                    continue
                if normalized_after and execute_at and execute_at < normalized_after:
                    continue
                if normalized_before and execute_at and execute_at > normalized_before:
                    continue
                item = dict(task)
                item['task_id'] = _encode_task_id(item['id'], is_recurring=False)
                item['task_type'] = 'once'
                item.pop('id', None)
                item.pop('description', None)
                result.append(item)

        if task_type in ("recurring", "all"):
            recurring_data = _request_json("GET", "/tasks/recurring", params={"page": 1, "page_size": max(limit, 100)})
            recurring_tasks = (recurring_data or {}).get("items") or []
            for task in recurring_tasks:
                item = dict(task)
                item['task_id'] = _encode_task_id(item['id'], is_recurring=True)
                item['task_type'] = 'recurring'
                item.pop('id', None)
                item.pop('description', None)
                result.append(item)

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
            if not croniter.is_valid(schedule):
                return "Error: Invalid schedule for recurring task. Use standard cron format (e.g., '0 9 * * *')."
            task = _request_json(
                "POST",
                "/tasks/recurring",
                json_body={
                    "name": name,
                    "description": description,
                    "agent_id": agent_id,
                    "cron_expression": schedule,
                    "enabled": True,
                },
            )
            task_id = int(task["id"])
            encoded_id = _encode_task_id(task_id, is_recurring=True)
            return f"Recurring task '{name}' (ID: {encoded_id}) added successfully. Cron: {schedule}"
        else:
            execute_at = _parse_schedule_to_local_str(schedule)
            task = _request_json(
                "POST",
                "/tasks/one-time",
                json_body={
                    "name": name,
                    "description": description,
                    "agent_id": agent_id,
                    "execute_at": execute_at,
                },
            )
            task_id = int(task["id"])
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
            task = _fetch_recurring_task(raw_id)
            if not task:
                return f"Error: Recurring task {task_id} not found."
            _request_json("DELETE", f"/tasks/recurring/{raw_id}")
            return f"Recurring task {task_id} ('{task['name']}') and pending instances deleted successfully."
        else:
            task = _fetch_one_time_task(raw_id)
            if not task:
                return f"Error: Task {task_id} not found."
            _request_json("DELETE", f"/tasks/one-time/{raw_id}")
            return f"Task {task_id} ('{task['name']}') deleted successfully."
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
            task = _fetch_recurring_task(raw_id)
            if not task:
                return f"Error: Recurring task {task_id} not found."
            _request_json("POST", f"/tasks/internal/recurring/{raw_id}/complete")
            return f"Recurring task {task_id} ('{task['name']}') marked as executed."
        else:
            task = _fetch_one_time_task(raw_id)
            if not task:
                return f"Error: Task {task_id} not found."

            if task['status'] == 'completed':
                return f"Task {task_id} is already completed."
            _request_json("POST", f"/tasks/internal/one-time/{raw_id}/complete", json_body={"response": None})
            return f"Task {task_id} ('{task['name']}') marked as completed."
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
        
        task = _fetch_recurring_task(raw_id)
        if not task:
            return f"Error: Recurring task {task_id} not found."
        _request_json("POST", f"/tasks/recurring/{raw_id}/toggle", json_body={"enabled": enabled})
        status = "enabled" if enabled else "disabled"
        return f"Recurring task {task_id} ('{task['name']}') {status} successfully."
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
            task = _fetch_recurring_task(raw_id)
            if not task:
                return f"Error: Recurring task {task_id} not found."

            item = dict(task)
            item['task_id'] = task_id
            item['task_type'] = 'recurring'
            item.pop('id', None)
            return json.dumps(item, indent=2, ensure_ascii=False)
        else:
            task = _fetch_one_time_task(raw_id)
            if not task:
                return f"Error: Task {task_id} not found."

            history = _fetch_one_time_task_history(raw_id, limit=10)

            # Truncate response content to last 1000 characters
            for entry in history:
                if entry.get('response'):
                    response = entry['response']
                    if len(response) > 1000:
                        entry['response'] = "...[truncated]" + response[-1000:]

            task = dict(task)
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
            
            task = _fetch_recurring_task(raw_id)
            if not task:
                return f"Error: Recurring task {task_id} not found."
            _request_json("PUT", f"/tasks/recurring/{raw_id}", json_body=update_kwargs)
            updated_fields = ", ".join(update_kwargs.keys())
            return f"Recurring task {task_id} updated successfully. Fields updated: {updated_fields}."
        else:
            normalized_schedule = None
            if schedule is not None:
                try:
                    normalized_schedule = _parse_schedule_to_local_str(schedule)
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
            
            task = _fetch_one_time_task(raw_id)
            if not task:
                return f"Error: Task {task_id} not found."
            
            # Check if task can be updated (not processing or completed)
            if task['status'] in ['processing', 'completed']:
                return f"Error: Cannot update task {task_id} with status '{task['status']}'. Only pending or failed tasks can be updated."
            
            _request_json("PUT", f"/tasks/one-time/{raw_id}", json_body=update_kwargs)
            updated_fields = ", ".join(update_kwargs.keys())
            return f"Task {task_id} updated successfully. Fields updated: {updated_fields}."
                
    except ValueError as e:
        return f"Error: Invalid value - {str(e)}"
    except Exception as e:
        return f"Error updating task: {str(e)}"


if __name__ == "__main__":
    mcp.run()
