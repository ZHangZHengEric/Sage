from __future__ import annotations

from typing import Any

from sagents.tool.tool_base import tool

from ..user_context import DEFAULT_DESKTOP_USER_ID
from .browser_bridge import BrowserBridgeHub


class BrowserBridgeTool:
    """Built-in browser tools backed by Chrome extension bridge."""

    TOOL_NAMES = [
        "browser_get_context",
        "browser_navigate",
        "browser_find_text",
        "browser_scroll",
        "browser_send_keys",
        "browser_wait",
        "browser_list_tabs",
        "browser_switch_tab",
        "browser_select_dropdown",
        "browser_upload_file",
        "browser_screenshot",
        "browser_dom_action",
    ]

    def __init__(self, user_id: str = DEFAULT_DESKTOP_USER_ID) -> None:
        self.user_id = user_id
        self.hub = BrowserBridgeHub.get_instance()

    async def _require_online(self) -> tuple[bool, dict[str, Any]]:
        status = await self.hub.get_status(self.user_id)
        return bool(status.get("connected")), status

    async def _dispatch(self, *, action: str, args: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        online, status = await self._require_online()
        if not online:
            return {
                "ok": False,
                "error": "浏览器插件当前离线，请先打开 Sage 浏览器侧边栏。",
                "status": status,
            }

        command = await self.hub.enqueue_command(user_id=self.user_id, action=action, args=args)
        command_id = command.get("command_id", "")
        result = await self.hub.wait_command_result(command_id=command_id, timeout_seconds=timeout_seconds)
        if result is None:
            return {
                "ok": False,
                "error": f"浏览器命令执行超时（>{timeout_seconds}s）",
                "command": command,
            }
        if not result.get("success", False):
            return {
                "ok": False,
                "error": result.get("error") or "浏览器命令执行失败",
                "command": command,
                "result": result,
            }
        return {
            "ok": True,
            "command": command,
            "result": result.get("result"),
        }

    @tool(
        description_i18n={
            "zh": "获取浏览器上下文（结构化页面摘要 + 可操作 DOM 节点 dom_id 列表）。",
            "en": "Get browser context with structured summary and operable DOM nodes (dom_id list).",
        }
    )
    async def browser_get_context(self) -> dict[str, Any]:
        status = await self.hub.get_status(self.user_id)
        return {
            "ok": True,
            "connected": bool(status.get("connected")),
            "active_tab": status.get("active_tab"),
            "page_context": status.get("page_context"),
            "capabilities": status.get("capabilities") or [],
            "last_seen_at": status.get("last_seen_at"),
        }

    @tool(
        description_i18n={
            "zh": "在当前浏览器标签页导航到指定 URL。",
            "en": "Navigate the current browser tab to a target URL.",
        },
        param_description_i18n={
            "url": {"zh": "目标 URL", "en": "Target URL"},
            "timeout_seconds": {"zh": "等待浏览器执行结果的超时时间（秒）", "en": "Timeout in seconds for browser action result"},
        },
    )
    async def browser_navigate(self, url: str, timeout_seconds: float = 30.0) -> dict[str, Any]:
        return await self._dispatch(
            action="navigate",
            args={"url": url},
            timeout_seconds=max(1.0, float(timeout_seconds)),
        )

    @tool(
        description_i18n={
            "zh": "在当前页面查找文本并滚动到匹配位置。",
            "en": "Find text on current page and scroll to a match.",
        },
        param_description_i18n={
            "text": {"zh": "要查找的文本", "en": "Text to search for"},
            "timeout_seconds": {"zh": "超时时间（秒）", "en": "Timeout in seconds"},
        },
    )
    async def browser_find_text(self, text: str, timeout_seconds: float = 30.0) -> dict[str, Any]:
        return await self._dispatch(
            action="find_text",
            args={"text": text},
            timeout_seconds=max(1.0, float(timeout_seconds)),
        )

    @tool(
        description_i18n={
            "zh": "滚动页面。direction 可为 down/up。",
            "en": "Scroll page with direction down/up.",
        },
        param_description_i18n={
            "direction": {"zh": "滚动方向：down 或 up", "en": "Scroll direction: down or up"},
            "pages": {"zh": "滚动页数（可小数）", "en": "How many viewport pages to scroll"},
            "timeout_seconds": {"zh": "超时时间（秒）", "en": "Timeout in seconds"},
        },
    )
    async def browser_scroll(self, direction: str = "down", pages: float = 1.0, timeout_seconds: float = 30.0) -> dict[str, Any]:
        return await self._dispatch(
            action="scroll",
            args={"direction": direction, "pages": float(max(0.25, min(8.0, pages)))},
            timeout_seconds=max(1.0, float(timeout_seconds)),
        )

    @tool(
        description_i18n={
            "zh": "向当前焦点元素或指定 selector 发送按键/文本。",
            "en": "Send keys/text to focused element or an optional selector.",
        },
        param_description_i18n={
            "keys": {"zh": "按键或文本，如 ENTER、hello", "en": "Keys or text, e.g. ENTER, hello"},
            "selector": {"zh": "可选：目标元素 selector", "en": "Optional target selector"},
            "submit": {"zh": "是否提交表单", "en": "Whether to submit form"},
            "timeout_seconds": {"zh": "超时时间（秒）", "en": "Timeout in seconds"},
        },
    )
    async def browser_send_keys(
        self,
        keys: str,
        selector: str = "",
        submit: bool = False,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        return await self._dispatch(
            action="send_keys",
            args={"keys": keys, "selector": selector, "submit": bool(submit)},
            timeout_seconds=max(1.0, float(timeout_seconds)),
        )

    @tool(
        description_i18n={
            "zh": "等待指定秒数后继续。",
            "en": "Wait for a number of seconds.",
        },
        param_description_i18n={
            "seconds": {"zh": "等待秒数", "en": "Seconds to wait"},
            "timeout_seconds": {"zh": "命令超时时间（秒）", "en": "Timeout in seconds"},
        },
    )
    async def browser_wait(self, seconds: float = 1.0, timeout_seconds: float = 30.0) -> dict[str, Any]:
        return await self._dispatch(
            action="wait",
            args={"seconds": float(max(0.1, min(30.0, seconds)))},
            timeout_seconds=max(1.0, float(timeout_seconds)),
        )

    @tool(
        description_i18n={
            "zh": "列出当前窗口标签页，返回 tab id 和标题。",
            "en": "List tabs in current window with tab ids and titles.",
        },
        param_description_i18n={
            "timeout_seconds": {"zh": "超时时间（秒）", "en": "Timeout in seconds"},
        },
    )
    async def browser_list_tabs(self, timeout_seconds: float = 30.0) -> dict[str, Any]:
        return await self._dispatch(
            action="list_tabs",
            args={},
            timeout_seconds=max(1.0, float(timeout_seconds)),
        )

    @tool(
        description_i18n={
            "zh": "切换到指定标签页，可用 tab_id 或 tab_id_suffix。",
            "en": "Switch to a target tab via tab_id or tab_id_suffix.",
        },
        param_description_i18n={
            "tab_id": {"zh": "标签页 ID", "en": "Target tab id"},
            "tab_id_suffix": {"zh": "标签页 ID 后缀（方便短引用）", "en": "Suffix of target tab id"},
            "timeout_seconds": {"zh": "超时时间（秒）", "en": "Timeout in seconds"},
        },
    )
    async def browser_switch_tab(
        self,
        tab_id: int | None = None,
        tab_id_suffix: str = "",
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {}
        if tab_id is not None:
            args["tabId"] = int(tab_id)
        if tab_id_suffix:
            args["tabIdSuffix"] = str(tab_id_suffix)
        return await self._dispatch(
            action="switch_tab",
            args=args,
            timeout_seconds=max(1.0, float(timeout_seconds)),
        )

    @tool(
        description_i18n={
            "zh": "选择下拉框选项（优先匹配文本，也支持值匹配）。",
            "en": "Select an option from dropdown by text/value.",
        },
        param_description_i18n={
            "text": {"zh": "选项文本或值", "en": "Option text or value"},
            "selector": {"zh": "下拉元素选择器（可选）", "en": "Dropdown selector (optional)"},
            "index": {"zh": "下拉元素索引（可选）", "en": "Dropdown index (optional)"},
            "timeout_seconds": {"zh": "超时时间（秒）", "en": "Timeout in seconds"},
        },
    )
    async def browser_select_dropdown(
        self,
        text: str,
        selector: str = "",
        index: int | None = None,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"text": text}
        if selector:
            args["selector"] = selector
        if index is not None:
            args["index"] = int(index)
        return await self._dispatch(
            action="select_dropdown",
            args=args,
            timeout_seconds=max(1.0, float(timeout_seconds)),
        )

    @tool(
        description_i18n={
            "zh": "向 `<input type=file>` 上传 base64 文件内容。",
            "en": "Upload base64 file content to `<input type=file>`.",
        },
        param_description_i18n={
            "file_name": {"zh": "文件名", "en": "File name"},
            "file_data_base64": {"zh": "文件内容（base64）", "en": "File content in base64"},
            "file_mime_type": {"zh": "MIME 类型", "en": "MIME type"},
            "selector": {"zh": "文件输入框 selector（可选）", "en": "File input selector (optional)"},
            "index": {"zh": "文件输入框索引（可选）", "en": "File input index (optional)"},
            "timeout_seconds": {"zh": "超时时间（秒）", "en": "Timeout in seconds"},
        },
    )
    async def browser_upload_file(
        self,
        file_name: str,
        file_data_base64: str,
        file_mime_type: str = "application/octet-stream",
        selector: str = "",
        index: int | None = None,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "fileName": file_name,
            "fileDataBase64": file_data_base64,
            "mimeType": file_mime_type,
        }
        if selector:
            args["selector"] = selector
        if index is not None:
            args["index"] = int(index)
        return await self._dispatch(
            action="upload_file",
            args=args,
            timeout_seconds=max(1.0, float(timeout_seconds)),
        )

    @tool(
        description_i18n={
            "zh": "对当前浏览器页截图，返回 data_url。",
            "en": "Capture screenshot of current browser tab and return data_url.",
        },
        param_description_i18n={
            "format": {"zh": "截图格式：png/jpeg", "en": "Format: png/jpeg"},
            "quality": {"zh": "jpeg 质量（0-100）", "en": "JPEG quality (0-100)"},
            "timeout_seconds": {"zh": "超时时间（秒）", "en": "Timeout in seconds"},
        },
    )
    async def browser_screenshot(
        self,
        format: str = "png",
        quality: int = 85,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        return await self._dispatch(
            action="screenshot",
            args={"format": format, "quality": int(max(0, min(100, quality)))},
            timeout_seconds=max(1.0, float(timeout_seconds)),
        )

    @tool(
        description_i18n={
            "zh": "执行浏览器 DOM 动作。action 支持：click/fill/select_dropdown/upload_file/screenshot/extract_text/run_script/find_text/scroll/send_keys/wait/list_tabs/switch_tab。",
            "en": "Run browser actions. Supported: click/fill/select_dropdown/upload_file/screenshot/extract_text/run_script/find_text/scroll/send_keys/wait/list_tabs/switch_tab.",
        },
        param_description_i18n={
            "action": {"zh": "动作类型", "en": "Action type"},
            "selector": {"zh": "DOM 选择器（click/fill/extract_text 时使用）", "en": "DOM selector for click/fill/extract_text"},
            "dom_id": {"zh": "来自 browser_get_context 的 dom_id（如 d12）", "en": "dom_id from browser_get_context, e.g. d12"},
            "value": {"zh": "填充文本（fill 时使用）", "en": "Input value for fill action"},
            "submit": {"zh": "fill 后是否提交表单", "en": "Whether to submit form after fill"},
            "max_chars": {"zh": "提取文本最大长度（extract_text）", "en": "Maximum extracted text length"},
            "code": {"zh": "脚本代码（run_script）", "en": "Script code for run_script"},
            "text": {"zh": "查找文本（find_text）", "en": "Text for find_text"},
            "direction": {"zh": "滚动方向（scroll）", "en": "Scroll direction"},
            "pages": {"zh": "滚动页数（scroll）", "en": "Scroll pages"},
            "keys": {"zh": "按键或文本（send_keys）", "en": "Keys/text for send_keys"},
            "seconds": {"zh": "等待秒数（wait）", "en": "Seconds for wait"},
            "tab_id": {"zh": "标签页 ID（switch_tab）", "en": "Tab id for switch_tab"},
            "tab_id_suffix": {"zh": "标签页后缀（switch_tab）", "en": "Tab id suffix for switch_tab"},
            "index": {"zh": "元素索引（click/fill/select_dropdown/upload_file）", "en": "Element index"},
            "file_name": {"zh": "文件名（upload_file）", "en": "File name for upload_file"},
            "file_data_base64": {"zh": "文件 base64（upload_file）", "en": "Base64 file data for upload_file"},
            "file_mime_type": {"zh": "文件 MIME（upload_file）", "en": "MIME type for upload_file"},
            "format": {"zh": "截图格式（screenshot）", "en": "Screenshot format"},
            "quality": {"zh": "截图质量（screenshot）", "en": "Screenshot quality"},
            "timeout_seconds": {"zh": "等待结果超时时间（秒）", "en": "Timeout in seconds"},
        },
    )
    async def browser_dom_action(
        self,
        action: str,
        selector: str = "",
        dom_id: str = "",
        value: str = "",
        submit: bool = False,
        max_chars: int = 8000,
        code: str = "",
        text: str = "",
        direction: str = "down",
        pages: float = 1.0,
        keys: str = "",
        seconds: float = 1.0,
        tab_id: int | None = None,
        tab_id_suffix: str = "",
        index: int | None = None,
        file_name: str = "",
        file_data_base64: str = "",
        file_mime_type: str = "application/octet-stream",
        format: str = "png",
        quality: int = 85,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        normalized_action = (action or "").strip()
        if normalized_action not in {
            "click",
            "fill",
            "extract_text",
            "run_script",
            "find_text",
            "scroll",
            "send_keys",
            "wait",
            "list_tabs",
            "switch_tab",
            "select_dropdown",
            "upload_file",
            "screenshot",
        }:
            return {
                "ok": False,
                "error": f"不支持的 action: {normalized_action}",
            }

        args: dict[str, Any] = {}
        if normalized_action in {"click", "fill", "extract_text"}:
            args["selector"] = selector
            if dom_id:
                args["domId"] = dom_id
            if index is not None:
                args["index"] = int(index)
        if normalized_action == "fill":
            args["value"] = value
            args["submit"] = bool(submit)
        if normalized_action == "extract_text":
            args["maxChars"] = int(max(1, max_chars))
        if normalized_action == "run_script":
            args["code"] = code
        if normalized_action == "find_text":
            args["text"] = text
        if normalized_action == "scroll":
            args["direction"] = direction
            args["pages"] = float(max(0.25, min(8.0, pages)))
        if normalized_action == "send_keys":
            args["keys"] = keys
            if selector:
                args["selector"] = selector
            if dom_id:
                args["domId"] = dom_id
            args["submit"] = bool(submit)
        if normalized_action == "wait":
            args["seconds"] = float(max(0.1, min(30.0, seconds)))
        if normalized_action == "switch_tab":
            if tab_id is not None:
                args["tabId"] = int(tab_id)
            if tab_id_suffix:
                args["tabIdSuffix"] = str(tab_id_suffix)
        if normalized_action == "select_dropdown":
            args["text"] = text or value
            if selector:
                args["selector"] = selector
            if dom_id:
                args["domId"] = dom_id
            if index is not None:
                args["index"] = int(index)
        if normalized_action == "upload_file":
            args["fileName"] = file_name
            args["fileDataBase64"] = file_data_base64
            args["mimeType"] = file_mime_type
            if selector:
                args["selector"] = selector
            if dom_id:
                args["domId"] = dom_id
            if index is not None:
                args["index"] = int(index)
        if normalized_action == "screenshot":
            args["format"] = format
            args["quality"] = int(max(0, min(100, quality)))

        return await self._dispatch(
            action=normalized_action,
            args=args,
            timeout_seconds=max(1.0, float(timeout_seconds)),
        )
