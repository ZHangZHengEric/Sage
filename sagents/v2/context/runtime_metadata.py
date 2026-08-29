"""Host-supplied runtime context projected through stable v2 segments.

The provider reads only the already-resolved `RunConfig.metadata` mapping.  It
does not inspect a filesystem, clock, Todo service, or process-global manager;
embedding applications can therefore replace it or populate the same contract
from any storage and execution environment.
"""

from __future__ import annotations

import json
from xml.sax.saxutils import escape
from collections.abc import Mapping
from typing import Any

from sagents.v2.contracts.commands import StartRun
from sagents.v2.context.contracts import (
    ContextSegment,
    ContextStability,
)


class RunMetadataContextProvider:
    """Build stable identity/language and volatile execution-state segments."""

    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]:
        del run_id
        metadata = command.config.metadata
        values: list[ContextSegment] = []
        language = str(metadata.get("response_language") or "").strip()
        if language:
            values.append(
                ContextSegment(
                    segment_id="response_language",
                    content=(
                        "<response_language>\n"
                        f"{self._language_contract(language)}\n"
                        "</response_language>"
                    ),
                    stability=ContextStability.STABLE,
                    priority=-190,
                )
            )
            values.append(
                ContextSegment(
                    segment_id="system_reminder_hint",
                    content=(
                        "<system_reminder_hint>\n"
                        f"{self._system_reminder_hint(language)}\n"
                        "</system_reminder_hint>"
                    ),
                    stability=ContextStability.STABLE,
                    priority=-175,
                )
            )
            values.append(
                ContextSegment(
                    segment_id="runtime_context_hint",
                    content=(
                        "<runtime_context_hint>\n"
                        f"{self._runtime_hint(language)}\n"
                        "</runtime_context_hint>"
                    ),
                    stability=ContextStability.STABLE,
                    priority=-170,
                )
            )

        documents = metadata.get("identity_documents")
        if isinstance(documents, Mapping):
            document_order = ("AGENT", "SOUL", "USER", "MEMORY", "IDENTITY")
            ordered_names = [name for name in document_order if name in documents]
            ordered_names.extend(
                sorted(
                    str(name) for name in documents if str(name) not in document_order
                )
            )
            for name in ordered_names:
                content = documents.get(name)
                if isinstance(content, str) and content.strip():
                    safe_name = str(name).replace("<", "").replace(">", "")
                    rendered = self._identity_document(
                        safe_name, content.strip(), language
                    )
                    values.append(
                        ContextSegment(
                            segment_id=f"identity_{self._identifier(safe_name)}",
                            content=rendered,
                            stability=ContextStability.STABLE,
                            priority=-150,
                            sensitive=safe_name.upper() in {"USER", "MEMORY"},
                        )
                    )

        runtime = self._runtime_text(metadata)
        if runtime:
            values.append(
                ContextSegment(
                    segment_id="runtime_state",
                    content=runtime,
                    stability=ContextStability.VOLATILE,
                    priority=100,
                    sensitive=True,
                )
            )
        return tuple(values)

    @staticmethod
    def _runtime_text(metadata: Mapping[str, Any]) -> str:
        sections: list[str] = []
        system_context: dict[str, Any] = {}
        configured = metadata.get("system_context")
        if isinstance(configured, Mapping):
            system_context.update(configured)
        for key in ("current_time", "working_directory"):
            value = metadata.get(key)
            if value not in (None, "", (), [], {}):
                system_context[key] = value
        todo = metadata.get("todo")
        if todo not in (None, "", (), [], {}):
            system_context["todo_list"] = todo
        if system_context:
            lines = ["<system_context>"]
            for key in sorted(system_context):
                safe_key = RunMetadataContextProvider._identifier(str(key))
                value = system_context[key]
                if isinstance(value, (dict, list, tuple)):
                    rendered = json.dumps(value, ensure_ascii=False, indent=2)
                    lines.append(f"  <{safe_key}>\n{rendered}\n  </{safe_key}>")
                else:
                    lines.append(f"  <{safe_key}>{escape(str(value))}</{safe_key}>")
            lines.append("</system_context>")
            sections.append("\n".join(lines))
        workspace_files = metadata.get("workspace_files")
        if workspace_files not in (None, "", (), [], {}):
            rendered = (
                workspace_files
                if isinstance(workspace_files, str)
                else json.dumps(workspace_files, ensure_ascii=False, indent=2)
            )
            sections.append(f"<workspace_files>\n{rendered}\n</workspace_files>")
        external_paths = metadata.get("external_paths")
        if external_paths not in (None, "", (), [], {}):
            rendered = (
                external_paths
                if isinstance(external_paths, str)
                else json.dumps(external_paths, ensure_ascii=False, indent=2)
            )
            sections.append(f"<external_paths>\n{rendered}\n</external_paths>")
        reminder = metadata.get("shell_completion_reminder")
        if reminder not in (None, "", (), [], {}):
            sections.append(f"<system_reminder>\n{reminder}\n</system_reminder>")
        return "\n".join(sections)

    @staticmethod
    def _identifier(value: str) -> str:
        normalized = "".join(
            character.lower() if character.isalnum() else "_" for character in value
        ).strip("_")
        return normalized[:120] or "document"

    @staticmethod
    def _runtime_hint(language: str) -> str:
        if language.lower().startswith("zh"):
            return (
                "当 user 消息中同时出现 <runtime_context>...</runtime_context> 与 "
                "<user_request>...</user_request> 时，<runtime_context> 是系统注入的运行状态，"
                "不是用户指令；只将 <user_request> 内的内容视为用户当前请求。"
            )
        return (
            "When a user message contains both <runtime_context>...</runtime_context> "
            "and <user_request>...</user_request>, treat <runtime_context> as "
            "system-provided runtime state, not user instructions. Treat only "
            "the content inside <user_request> as the user's current request."
        )

    @staticmethod
    def _system_reminder_hint(language: str) -> str:
        if language.lower().startswith("zh"):
            return (
                "当对话中出现 <system_reminder>...</system_reminder> 包裹的内容时，"
                "请视为系统级状态通知（非用户输入），仅作为参考信息推进任务即可，"
                "不需要回复或感谢这条提醒。典型场景：后台 shell 命令完成事件。"
            )
        return (
            "When you see content wrapped in <system_reminder>...</system_reminder>, "
            "treat it as a system-level status notification (not user input). "
            "Use it as context to drive the next step; do not acknowledge the reminder itself."
        )

    @staticmethod
    def _identity_document(name: str, content: str, language: str) -> str:
        if name == "AGENT":
            return f"<agent_md>\n{content}\n</agent_md>"
        if name == "SOUL":
            bounded = content[:300] + ("……" if len(content) > 300 else "")
            return f"<soul>\n{bounded}\n</soul>"
        if name == "USER":
            return f"<user>\n{content}\n</user>"
        if name == "MEMORY":
            return f"<memory>\n{content}\n</memory>"
        if name == "IDENTITY":
            bounded = content[:300] + ("……" if len(content) > 300 else "")
            hint = (
                "以下身份文档是角色定义的补充；如有冲突，以 role_definition 为准。"
                if language.lower().startswith("zh")
                else "This identity document extends the role definition; the role definition wins on conflict."
            )
            return (
                "<agent_identity_extension>\n"
                f"{hint}\n\n{bounded}\n"
                "</agent_identity_extension>"
            )
        safe_tag = RunMetadataContextProvider._identifier(name)
        return f"<{safe_tag}>\n{content}\n</{safe_tag}>"

    @staticmethod
    def _language_contract(language: str) -> str:
        if language.lower().startswith("zh"):
            return (
                f"当前回复语言为 {language}。所有允许向用户展示、由 assistant 编写的自然语言，"
                "包括最终答复和必要且面向用户的简短事实进度，都必须使用该语言。本指令只决定语言，"
                "不授权输出内部分析、推理草稿、回复策略、工具选择判断或中间执行记录。"
                "不得因为工具结果、检索内容或引用材料使用英文而改用英文。代码、命令、路径、标识符、"
                "枚举、协议字段和逐字引用保持原样。"
            )
        return (
            f"The response language is {language}. All assistant-authored natural "
            "language shown to the user must use this language. Preserve code, commands, "
            "paths, identifiers, protocol fields, and verbatim quotations."
        )
