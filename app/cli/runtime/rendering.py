import json
import re
import sys
from typing import Any, Dict, List, Optional


TOOL_NAME_TAG_PATTERN = re.compile(r"<tool_name>\s*([A-Za-z0-9_.-]+)\s*</tool_name>")
TOOL_CALL_FUNCTION_PATTERN = re.compile(r"<call\s+function=\"([A-Za-z0-9_.-]+)\"")
TOOL_RESULT_NAME_PATTERN = re.compile(r"<function_result\s+name=\"([A-Za-z0-9_.-]+)\"")
DSML_INVOKE_NAME_PATTERN = re.compile(r"<｜DSML｜invoke\s+name=\"([A-Za-z0-9_.-]+)\"")
DSML_FILE_PATH_PATTERN = re.compile(
    r"<｜DSML｜parameter\s+name=\"file_path\"\s+string=\"true\">(.*?)</｜DSML｜parameter>",
    re.DOTALL,
)
SKILL_TAG_PATTERN = re.compile(r"<skill>\s*([A-Za-z0-9_.-]+)\s*</skill>", re.DOTALL)
SKILL_INPUT_TAG_PATTERN = re.compile(r"<skill_input>", re.DOTALL)
SKILL_RESULT_TAG_PATTERN = re.compile(r"<skill_result>", re.DOTALL)
RAW_ASSISTANT_BLOCK_PATTERNS = (
    re.compile(r"(^|\n)\s*<skill>\s*.*?</skill>", re.DOTALL),
    re.compile(r"(^|\n)\s*<skill_input>.*?</skill_input>", re.DOTALL),
    re.compile(r"(^|\n)\s*<skill_result>.*?</skill_result>", re.DOTALL),
    re.compile(r"(^|\n)\s*<call\s+function=\"[A-Za-z0-9_.-]+\".*?</call>", re.DOTALL),
    re.compile(r"(^|\n)\s*<function_result\s+name=\"[A-Za-z0-9_.-]+\".*?</function_result>", re.DOTALL),
    re.compile(r"(^|\n)\s*<function_results>.*?</function_results>", re.DOTALL),
    re.compile(r"(^|\n)\s*<tool_name>\s*.*?</tool_name>", re.DOTALL),
    re.compile(r"(^|\n)\s*<｜DSML｜tool_calls>.*?</｜DSML｜tool_calls>", re.DOTALL),
    re.compile(r"(^|\n)\s*<｜DSML｜invoke\b.*?</｜DSML｜invoke>", re.DOTALL),
)
RAW_ASSISTANT_START_PATTERNS = (
    re.compile(r"(^|\n)\s*<skill>"),
    re.compile(r"(^|\n)\s*<skill_input>"),
    re.compile(r"(^|\n)\s*<skill_result>"),
    re.compile(r"(^|\n)\s*<call\s+function=\""),
    re.compile(r"(^|\n)\s*<function_result\b"),
    re.compile(r"(^|\n)\s*<function_results>"),
    re.compile(r"(^|\n)\s*<tool_name>"),
    re.compile(r"(^|\n)\s*<｜DSML｜"),
)


def _empty_render_state() -> Dict[str, Any]:
    return {
        "assistant_buffer": "",
        "assistant_emitted": "",
        "tool_tag_buffer": "",
        "announced_tools": set(),
        "announced_file_paths": set(),
        "last_tool_name": None,
        "last_visible_phase": None,
    }


def _split_visible_assistant_content(buffer: str) -> tuple[str, str]:
    working = buffer
    previous = None
    while working != previous:
        previous = working
        for pattern in RAW_ASSISTANT_BLOCK_PATTERNS:
            working = pattern.sub("", working)

    start_positions = []
    for pattern in RAW_ASSISTANT_START_PATTERNS:
        match = pattern.search(working)
        if match:
            start_positions.append(match.start())

    if not start_positions:
        return working, ""

    split_at = min(start_positions)
    return working[:split_at], working[split_at:]


def _render_assistant_content_delta(render_state: Dict[str, Any], content: str) -> str:
    buffer = (render_state.get("assistant_buffer") or "") + content
    visible, pending = _split_visible_assistant_content(buffer)
    render_state["assistant_buffer"] = visible + pending

    emitted = render_state.get("assistant_emitted") or ""
    if visible.startswith(emitted):
        delta = visible[len(emitted) :]
    else:
        delta = visible
    render_state["assistant_emitted"] = visible
    return delta


def _collect_event_tool_names(event: Dict[str, Any], *, content_buffer: str = "") -> List[str]:
    tool_names: List[str] = []

    tool_calls = event.get("tool_calls") or []
    for tool_call in tool_calls:
        function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
        name = function.get("name")
        if name:
            tool_names.append(name)

    metadata = event.get("metadata") or {}
    metadata_tool_name = metadata.get("tool_name")
    if isinstance(metadata_tool_name, str) and metadata_tool_name:
        tool_names.append(metadata_tool_name)

    event_tool_name = event.get("tool_name")
    if isinstance(event_tool_name, str) and event_tool_name:
        tool_names.append(event_tool_name)

    combined_content = content_buffer
    content = event.get("content")
    if isinstance(content, str) and content:
        combined_content += content
    if combined_content:
        for match in TOOL_NAME_TAG_PATTERN.findall(combined_content):
            if match:
                tool_names.append(match.strip())
        for match in TOOL_CALL_FUNCTION_PATTERN.findall(combined_content):
            if match:
                tool_names.append(match.strip())
        for match in TOOL_RESULT_NAME_PATTERN.findall(combined_content):
            if match:
                tool_names.append(match.strip())
        for match in DSML_INVOKE_NAME_PATTERN.findall(combined_content):
            if match:
                tool_names.append(match.strip())
        for match in SKILL_TAG_PATTERN.findall(combined_content):
            if match:
                tool_names.append(match.strip())

    return sorted(set(tool_names))


def _collect_event_file_paths(event: Dict[str, Any], *, content_buffer: str = "") -> List[str]:
    file_paths: List[str] = []

    tool_calls = event.get("tool_calls") or []
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function", {}) or {}
        name = function.get("name")
        arguments = function.get("arguments")
        if name not in {"FileWrite", "WriteFile", "file_write"}:
            continue
        if isinstance(arguments, str) and arguments.strip():
            try:
                parsed = json.loads(arguments)
            except Exception:  # noqa: BLE001
                parsed = None
            if isinstance(parsed, dict):
                path = parsed.get("file_path") or parsed.get("path")
                if isinstance(path, str) and path.strip():
                    file_paths.append(path.strip())

    metadata = event.get("metadata") or {}
    metadata_path = metadata.get("file_path") or metadata.get("path")
    if isinstance(metadata_path, str) and metadata_path.strip():
        file_paths.append(metadata_path.strip())

    combined_content = content_buffer
    content = event.get("content")
    if isinstance(content, str) and content:
        combined_content += content
    if combined_content:
        for match in DSML_FILE_PATH_PATTERN.findall(combined_content):
            path = (match or "").strip()
            if path:
                file_paths.append(path)

    return sorted(set(file_paths))


def _buffer_has_skill_io_markup(buffer: str) -> bool:
    return bool(SKILL_INPUT_TAG_PATTERN.search(buffer) or SKILL_RESULT_TAG_PATTERN.search(buffer))


def _print_plain_event(event: Dict[str, Any], render_state: Dict[str, Any]) -> None:
    event_type = event.get("type")
    if event_type == "stream_end":
        if not sys.stdout.isatty():
            return
        sys.stdout.write("\n")
        sys.stdout.flush()
        return

    content = event.get("content")
    if isinstance(content, str) and content:
        tool_tag_buffer = (render_state.get("tool_tag_buffer") or "") + content
        render_state["tool_tag_buffer"] = tool_tag_buffer[-2048:]

    names = _collect_event_tool_names(event, content_buffer=render_state.get("tool_tag_buffer") or "")
    if names:
        announced_tools = render_state.setdefault("announced_tools", set())
        unseen_names = [name for name in names if name not in announced_tools]
        if unseen_names:
            announced_tools.update(unseen_names)
            render_state["last_tool_name"] = unseen_names[-1]
            render_state["last_visible_phase"] = "tool"
            sys.stderr.write(f"\n[tool] {', '.join(unseen_names)}\n")
            sys.stderr.flush()

    file_paths = _collect_event_file_paths(event, content_buffer=render_state.get("tool_tag_buffer") or "")
    if file_paths:
        announced_file_paths = render_state.setdefault("announced_file_paths", set())
        unseen_paths = [path for path in file_paths if path not in announced_file_paths]
        if unseen_paths:
            announced_file_paths.update(unseen_paths)
            for path in unseen_paths:
                sys.stderr.write(f"[file] wrote to: {path}\n")
            sys.stderr.flush()

    role = event.get("role")
    if role == "assistant" and isinstance(content, str) and content:
        visible_delta = _render_assistant_content_delta(render_state, content)
        if visible_delta:
            render_state["last_visible_phase"] = "assistant_text"
            render_state["last_tool_name"] = None
            sys.stdout.write(visible_delta)
            sys.stdout.flush()
        return

    if event_type == "error":
        sys.stderr.write(f"\n[error] {event.get('content', 'Unknown error')}\n")
        sys.stderr.flush()


def _emit_stream_idle_notice(idle_seconds: float) -> None:
    sys.stderr.write(f"\n{_build_stream_idle_notice(idle_seconds)}\n")
    sys.stderr.flush()


def _build_stream_idle_notice(idle_seconds: float) -> str:
    return f"[working] still running ({idle_seconds:.1f}s since last event)"


def _emit_stream_idle_notice_for_state(render_state: Dict[str, Any], idle_seconds: float) -> None:
    message = _build_stream_idle_notice_for_state(render_state, idle_seconds)
    if not message:
        return

    sys.stderr.write(f"\n{message}\n")
    sys.stderr.flush()


def _build_stream_idle_notice_for_state(
    render_state: Dict[str, Any], idle_seconds: float
) -> Optional[str]:
    last_tool_name = render_state.get("last_tool_name")
    last_visible_phase = render_state.get("last_visible_phase")
    has_visible_output = bool(render_state.get("assistant_emitted")) or bool(
        render_state.get("announced_tools")
    )

    if last_tool_name:
        return f"[working] waiting for {last_tool_name} ({idle_seconds:.1f}s since last event)"
    elif last_visible_phase == "assistant_text" and not has_visible_output:
        return f"[working] generating response ({idle_seconds:.1f}s since last event)"
    elif last_visible_phase == "assistant_text":
        return None
    elif has_visible_output:
        return None
    else:
        return _build_stream_idle_notice(idle_seconds)


def _emit_chat_exit_summary(session_id: Optional[str], *, json_output: bool) -> None:
    if json_output or not session_id:
        return

    sys.stderr.write(
        "\n"
        f"session_id: {session_id}\n"
        f"resume: sage resume {session_id}\n"
        "history: sage sessions\n"
    )
    sys.stderr.flush()


def _read_chat_prompt(prompt_text: str) -> Optional[str]:
    sys.stdout.write(prompt_text)
    sys.stdout.flush()
    line = sys.stdin.readline()
    if line == "":
        return None
    return line.rstrip("\r\n")
