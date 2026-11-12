"""Short voice cues keyed by the Sage tool identifiers."""

import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit

# Labels in the settings UI come from Sage's shared tool name map.
DEFAULT_TOOL_SPEECH = {
    "get_local_time": ("我在核对时间。", "I'm checking the time."),
    "search_web": ("我在查找网页资料。", "I'm searching the web."),
    "fetch_webpages": ("我在查看网页。", "I'm checking the page."),
    "file_read": ("我在读取文件。", "I'm reading the file."),
    "file_write": ("我在写入文件。", "I'm writing the file."),
    "file_update": ("我在更新文件。", "I'm updating the file."),
    "glob": ("我在查找文件。", "I'm looking for files."),
    "grep": ("我在搜索文件内容。", "I'm searching the files."),
    "list_dir": ("我在查看目录。", "I'm checking the directory."),
    "read_lints": ("我在检查诊断结果。", "I'm checking the diagnostics."),
    "execute_shell_command": ("我在执行命令。", "I'm running a command."),
    "await_shell": ("我在等待命令完成。", "I'm waiting for the command."),
}
TARGETED_TOOL_SPEECH = {
    "fetch_webpages": ("我在查看 {target}。", "I'm checking {target}."),
    "file_read": ("我在读取 {target}。", "I'm reading {target}."),
    "file_write": ("我在写入 {target}。", "I'm writing {target}."),
    "file_update": ("我在更新 {target}。", "I'm updating {target}."),
}
_TOOL_ALIASES = {
    "web_search": "search_web",
    "read_file": "file_read",
    "write_file": "file_write",
    "update_file": "file_update",
}


def canonical_tool_name(name: str) -> str:
    return _TOOL_ALIASES.get(name, name)


def tool_speech_target(name: str, arguments: dict) -> str | None:
    """Expose only a basename or one common HTTP(S) hostname to speech."""
    name = canonical_tool_name(name)
    if name in {"file_read", "file_write", "file_update"}:
        path = arguments.get("file_path") or arguments.get("path")
        if isinstance(path, str):
            name = PurePosixPath(path.replace("\\", "/")).name
            if re.fullmatch(r"[\w][\w .-]{0,49}", name):
                return name
    elif name == "fetch_webpages":
        urls = arguments.get("urls") or arguments.get("url")
        if isinstance(urls, str):
            urls = [urls]
        if isinstance(urls, list) and urls:
            hosts = set()
            for url in urls:
                if not isinstance(url, str):
                    return None
                try:
                    parsed = urlsplit(url)
                    host = parsed.hostname
                except ValueError:
                    return None
                if parsed.scheme not in {"http", "https"} or not host:
                    return None
                if not re.fullmatch(r"[A-Za-z0-9.-]{1,64}", host):
                    return None
                hosts.add(host)
            if len(hosts) == 1:
                return hosts.pop()
    return None


def tool_speech_text(name, target, *, chinese, overrides):
    canonical = canonical_tool_name(name)
    rule = overrides.get(canonical, {})
    if not rule.get("enabled", True):
        return None
    language = "zh" if chinese else "en"
    index = 0 if chinese else 1
    plain = DEFAULT_TOOL_SPEECH.get(canonical, ("", ""))[index]
    template = rule.get(language) or (
        TARGETED_TOOL_SPEECH[canonical][index]
        if target and canonical in TARGETED_TOOL_SPEECH
        else plain
    )
    if "{target}" in template:
        template = template.replace("{target}", target) if target else plain
    return template or None


def default_tool_speech_settings():
    settings = {}
    for name in (*DEFAULT_TOOL_SPEECH, *_TOOL_ALIASES):
        canonical = canonical_tool_name(name)
        zh, en = TARGETED_TOOL_SPEECH.get(canonical, DEFAULT_TOOL_SPEECH[canonical])
        settings[name] = {
            "canonical_tool": canonical,
            "zh": zh,
            "en": en,
            "supports_target": canonical in TARGETED_TOOL_SPEECH,
        }
    return settings
