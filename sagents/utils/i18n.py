from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator
from typing import Any

DEFAULT_LANGUAGE = "zh"
DEFAULT_TOOL_LANGUAGE = "en"

# Tool calls from different sessions can run concurrently in the same event loop.
# A ContextVar keeps the trusted response language task-local without exposing a
# model-controlled ``response_language`` argument on every tool.
_TOOL_LANGUAGE: ContextVar[str] = ContextVar(
    "sage_tool_language", default=DEFAULT_TOOL_LANGUAGE
)

MESSAGES: dict[str, dict[str, str]] = {
    "zh": {
        "tool.manager.not_found": "未找到工具“{tool_name}”。可用工具：{available}",
        "tool.manager.missing_parameters": "缺少必填参数：{parameters}",
        "tool.manager.unknown_type": "未知工具类型：{tool_type}",
        "tool.manager.invalid_json": "工具返回了无效的 JSON：{message}",
        "tool.manager.execution_failed": "工具“{tool_name}”执行失败（耗时 {seconds} 秒）：{message}",
        "tool.manager.cancelled": "工具“{tool_name}”已取消",
        "tool.result.success": "工具“{tool_name}”执行成功。",
        "tool.result.error": "工具“{tool_name}”执行失败。",
        "tool.error.INVALID_ARGUMENT": "工具参数无效。",
        "tool.error.NOT_FOUND": "未找到请求的资源。",
        "tool.error.PERMISSION_DENIED": "没有权限执行该操作。",
        "tool.error.SAFETY_BLOCKED": "该操作被安全策略阻止。",
        "tool.error.MULTIPLE_MATCHES": "匹配到多个结果，需要缩小匹配范围。",
        "tool.error.NO_MATCH": "没有找到匹配结果。",
        "tool.error.TIMEOUT": "操作超时。",
        "tool.error.SANDBOX_ERROR": "沙箱操作失败。",
        "tool.error.NETWORK_ERROR": "网络操作失败。",
        "tool.error.PARSE_ERROR": "内容解析失败。",
        "tool.error.PRECONDITION_FAILED": "执行该操作所需的前置条件未满足。",
        "tool.error.UNSUPPORTED": "当前不支持该操作。",
        "tool.error.INTERNAL_ERROR": "工具内部执行失败。",
        "tool.error.hint": "请根据错误码和原始详情调整参数或操作后重试。",
        "skill.error.session_required": "load_skill 需要有效的 session_id。",
        "skill.error.invalid_session": "无效的 session_id：{session_id}",
        "skill.error.manager_unavailable": "当前会话无法使用 skill 管理器。",
        "skill.error.not_found": "未找到 skill“{skill_name}”。可用 skills：{available}",
        "skill.heading.skill": "Skill",
        "skill.heading.folder": "Skill 文件夹路径",
        "skill.heading.files": "文件结构",
        "skill.heading.instructions": "说明（SKILL.md）",
        "skill.unknown": "未知",
        "skill.success": "已成功加载 skill“{skill_name}”。当前激活的 skills：{active}. 共 {total} 个。请遵循 System Prompt 中的说明。",
        "todo.updated": "任务清单已更新。新增：{added}，更新：{updated}，当前未完成：{pending}。",
        "todo.completed": "所有任务均已完成，任务清单已清空。新增：{added}，更新：{updated}。",
        "todo.save_failed": "保存任务清单失败。",
        "todo.none": "当前没有未完成的任务。",
        "todo.list_title": "当前未完成的任务：",
        "todo.tag.in_progress": "进行中",
        "todo.tag.pending": "待办",
        "todo.conclusion": "结论",
        "questionnaire.timeout": "用户未在规定时间内提交，已使用默认值。",
        "questionnaire.submitted": "用户已提交回答。",
        "questionnaire.start.success": "问卷已发起并等待用户回复，共 {count} 题。",
        "questionnaire.start.questions_must_be_list": "questions 必须是数组。",
        "questionnaire.start.questions_empty": "questions 不能为空。",
        "questionnaire.start.question_not_object": "{path} 必须是对象。",
        "questionnaire.start.question_type_invalid": "{path} 的题目类型非法，收到 {value!r}。支持 {allowed}。",
        "questionnaire.start.question_text_required": "{path} 缺少 text/title。",
        "questionnaire.start.question_id_duplicate": "{path} 的 id 重复：{value}。",
        "questionnaire.start.question_options_required": "{path} 的选择题需要 options。",
        "questionnaire.start.question_option_invalid": "{path} 选项无效，需为字符串或包含 value/label 的对象。",
        "questionnaire.start.default_type_invalid": "{path} 的 default 类型不合法，期望 {expected}，实际是 {actual}。",
        "questionnaire.start.default_value_not_in_options": "{path} 的 default 包含无效值：{value}。",
        "questionnaire.start.default_list_invalid_items": "{path} 的 default 必须是字符串数组，以下项不是字符串：{invalid_items}。",
        "questionnaire.start.allow_other_type_invalid": "{path} 的 allow_other 必须是布尔值。",
        "file.write.success": "文件写入成功。",
        "file.write.validation_issues": "文件写入成功，但内容校验发现问题。",
        "file.update.unchanged": "已执行按行替换，但目标范围已经与替换内容一致，文件未发生变化。",
        "file.update.unchanged_validation": "已执行按行替换，但文件未发生变化，且内容校验发现问题。",
        "file.update.success": "已成功执行 {operations} 个更新操作，共完成 {replacements} 处替换。",
        "file.update.validation_issues": "已执行 {operations} 个更新操作和 {replacements} 处替换，但内容校验发现问题。",
        "agent.error.session_not_found": "未找到会话：{session_id}",
        "agent.error.orchestrator_missing": "当前会话中没有可用的智能体编排器。",
        "agent.error.team_orchestrator_missing": "当前会话中没有可用的 Team 编排器。",
        "agent.spawned": "智能体已创建。ID：{agent_id}，可以接收任务。",
        "browser.offline": "浏览器扩展当前离线，请确认扩展已安装且浏览器页面仍处于活动状态。",
        "browser.timeout": "浏览器命令执行超时（>{seconds}s）。",
        "browser.failed": "浏览器命令执行失败。",
        "browser.unsupported_action": "不支持的浏览器 action：{action}",
        "lint.not_installed": "未安装 {tool}，已跳过检查。",
        "lint.no_config": "项目中没有找到 {tool} 配置，已跳过检查。",
        "lint.exited": "{tool} 执行失败（退出码 {code}）。",
        "lint.parse_failed": "解析 {tool} 输出失败：{message}",
        "tool_expand.unavailable": "当前会话上下文或工具管理器不可用。",
        "image.default_prompt": "请观察这张图片，识别其中的文字和关键视觉信息，并结合当前对话继续完成用户任务。",
        "image.context": "【工具注入的图片上下文】\n图片来源：{image_path}\n这是用户要求你查看的图片。请将图片内容作为当前任务的上下文，在下一步回复中直接基于图片进行理解、描述或推理。\n\n用户的图片处理要求：{prompt}",
        "image.unsupported": "当前 agent 模型不支持图片输入，请切换到多模态模型后再分析图片。",
        "image.queued": "图片已加入下一轮多模态模型上下文，agent 将直接基于图片继续分析。",
        "image.failed": "图片理解失败：{message}",
        "web.success": "已成功处理全部 {total} 个 URL。",
        "web.partial": "已成功处理 {success}/{total} 个 URL，{failed} 个失败。",
        "web.failed": "全部 {total} 个 URL 均处理失败。",
        "web.download_failed": "文件下载在 {attempts} 次尝试后失败。",
        "web.fetch_failed": "网页获取在 {attempts} 次尝试后失败。",
        "web.timeout": "请求在 {seconds} 秒后超时。",
        "shell.approval.timeout": "沙箱审批已超时，命令未执行。",
        "shell.approval.denied": "沙箱审批被拒绝，命令未执行。",
        "shell.approval.approved": "沙箱审批已通过，正在执行命令。",
        "shell.background": "命令已在后台启动，task_id={task_id}；当前仍在运行。",
        "shell.running": "命令在等待 block_until_ms={block_until_ms} 后仍在运行。",
        "shell.await_running": "await_shell 等待 block_until_ms={block_until_ms} 后任务仍在运行。",
        "shell.next.await_now": "立即调用 await_shell",
        "shell.next.await_again": "再次调用 await_shell",
        "shell.next.no_progress_only": "不要只回复等待或进度文本",
        "workflow.execution_failed": "工作流执行失败: {message}",
        "workflow.error.data_inspection_inappropriate": "输入内容可能包含不适当的内容，请修改后重试",
        "workflow.error.data_inspection_failed": "内容安全检查未通过，请修改输入后重试",
        "workflow.error.rate_limit": "请求过于频繁，请稍后再试",
        "workflow.error.quota": "API 配额不足，请检查账户余额或配额设置",
        "workflow.error.authentication": "API 认证失败，请检查 API Key 是否正确",
        "workflow.error.model_not_found": "指定的模型不存在或不可用，请检查模型配置",
        "workflow.error.context_length": "输入内容过长，请缩短后重试",
        "workflow.error.connection": "网络连接失败，请检查网络设置或稍后重试",
        "workflow.error.service_unavailable": "服务暂时不可用，请稍后再试",
        "runtime.tool_call_parse.title": "我尝试调用工具 `{tool_name}`，但参数解析失败。",
        "runtime.tool_call_parse.reason_title": "错误原因",
        "runtime.tool_call_parse.reason": "JSON格式无效或结构不完整",
        "runtime.tool_call_parse.raw_arguments": "原始参数",
        "runtime.tool_call_parse.suggestions_title": "优化建议",
        "runtime.tool_call_parse.next_step": (
            "我需要重新优化我的工具调用方式和参数，确保工具参数格式正确。"
        ),
        "runtime.tool_call_parse.suggestion.too_long_split": (
            "• 参数内容过长（超过2000字符），建议将任务拆分为多次工具调用"
        ),
        "runtime.tool_call_parse.suggestion.too_long_file": (
            "• 或者将大段内容保存到文件，然后传递文件路径"
        ),
        "runtime.tool_call_parse.suggestion.braces": (
            "• JSON括号不匹配，请检查花括号是否成对闭合"
        ),
        "runtime.tool_call_parse.suggestion.quotes": (
            "• 引号未正确闭合，请检查字符串引号是否成对"
        ),
        "runtime.tool_call_parse.suggestion.backslash": (
            "• 包含反斜杠字符，请确保特殊字符已正确转义"
        ),
        "runtime.tool_call_parse.suggestion.check_json": "• 请检查JSON格式是否正确",
        "runtime.tool_call_parse.suggestion.double_quotes": (
            "• 确保所有字符串使用双引号包裹"
        ),
        "runtime.tool_call_parse.suggestion.commas": ("• 确保没有多余的逗号或缺少逗号"),
        "runtime.tool.error.arguments_not_object": "工具参数格式错误: 参数必须是JSON对象",
        "runtime.tool.error.execution_failed": "工具 {tool_name} 执行失败: {message}",
        "runtime.tool.error.execution_cancelled": "工具 {tool_name} 已取消",
        "runtime.repeat_recovery.title": "执行路径正在重复",
        "runtime.repeat_recovery.notice": (
            "检测到重复执行步骤，已暂停以避免在没有进展的情况下继续。请说明后续处理要求。"
        ),
        "runtime.repeat_recovery.question": (
            "请说明你希望我接下来如何处理，也可以补充新的策略、约束或停止要求。"
        ),
        "runtime.repeat_recovery.answer_title": "问卷回答",
        "runtime.repeat_recovery.question_fallback": "问题",
        "runtime.repeat_recovery.unanswered": "未填写",
        "runtime.repeat_recovery.answer_separator": "：",
    },
    "en": {
        "tool.manager.not_found": "Tool '{tool_name}' was not found. Available tools: {available}",
        "tool.manager.missing_parameters": "Missing required parameters: {parameters}",
        "tool.manager.unknown_type": "Unknown tool type: {tool_type}",
        "tool.manager.invalid_json": "The tool returned invalid JSON: {message}",
        "tool.manager.execution_failed": "Tool '{tool_name}' failed after {seconds} seconds: {message}",
        "tool.manager.cancelled": "Tool '{tool_name}' was cancelled",
        "tool.result.success": "Tool '{tool_name}' completed successfully.",
        "tool.result.error": "Tool '{tool_name}' failed.",
        "tool.error.INVALID_ARGUMENT": "The tool arguments are invalid.",
        "tool.error.NOT_FOUND": "The requested resource was not found.",
        "tool.error.PERMISSION_DENIED": "Permission was denied for this operation.",
        "tool.error.SAFETY_BLOCKED": "The operation was blocked by the safety policy.",
        "tool.error.MULTIPLE_MATCHES": "Multiple results matched; narrow the match.",
        "tool.error.NO_MATCH": "No matching result was found.",
        "tool.error.TIMEOUT": "The operation timed out.",
        "tool.error.SANDBOX_ERROR": "The sandbox operation failed.",
        "tool.error.NETWORK_ERROR": "The network operation failed.",
        "tool.error.PARSE_ERROR": "The content could not be parsed.",
        "tool.error.PRECONDITION_FAILED": "A prerequisite for this operation was not met.",
        "tool.error.UNSUPPORTED": "This operation is not supported.",
        "tool.error.INTERNAL_ERROR": "The tool failed internally.",
        "tool.error.hint": "Review the error code and raw details, adjust the operation, and retry.",
        "skill.error.session_required": "load_skill requires a valid session_id.",
        "skill.error.invalid_session": "Invalid session_id: {session_id}",
        "skill.error.manager_unavailable": "The skill manager is unavailable for this session.",
        "skill.error.not_found": "Skill '{skill_name}' was not found. Available skills: {available}",
        "skill.heading.skill": "Skill",
        "skill.heading.folder": "Skill Folder Path",
        "skill.heading.files": "File Structure",
        "skill.heading.instructions": "Instructions (SKILL.md)",
        "skill.unknown": "Unknown",
        "skill.success": "Skill '{skill_name}' loaded successfully. Active skills: {active}. Total: {total}. Follow the instructions in the System Prompt.",
        "todo.updated": "Task list updated. Added: {added}, updated: {updated}, currently unfinished: {pending}.",
        "todo.completed": "All tasks are complete and the task list was cleared. Added: {added}, updated: {updated}.",
        "todo.save_failed": "Failed to save the task list.",
        "todo.none": "There are no unfinished tasks.",
        "todo.list_title": "Current unfinished tasks:",
        "todo.tag.in_progress": "in progress",
        "todo.tag.pending": "todo",
        "todo.conclusion": "conclusion",
        "questionnaire.timeout": "The user did not submit in time. Default values were used.",
        "questionnaire.submitted": "The user submitted answers.",
        "questionnaire.start.success": "Questionnaire started and waiting for user input, with {count} questions.",
        "questionnaire.start.questions_must_be_list": "The questions field must be an array.",
        "questionnaire.start.questions_empty": "The questions field cannot be empty.",
        "questionnaire.start.question_not_object": "{path} must be an object.",
        "questionnaire.start.question_type_invalid": "{path} has invalid question type: {value!r}. Allowed values are {allowed}.",
        "questionnaire.start.question_text_required": "{path} requires text or title.",
        "questionnaire.start.question_id_duplicate": "{path} has duplicate id: {value}.",
        "questionnaire.start.question_options_required": "{path} requires options for choice questions.",
        "questionnaire.start.question_option_invalid": "{path} option is invalid; use a string or an object with value and label.",
        "questionnaire.start.default_type_invalid": "{path} default has invalid type. Expected {expected}, got {actual}.",
        "questionnaire.start.default_value_not_in_options": "{path} default contains invalid value(s): {value}.",
        "questionnaire.start.default_list_invalid_items": "{path} default must be a list of strings; these values are invalid: {invalid_items}.",
        "questionnaire.start.allow_other_type_invalid": "{path} allow_other must be a boolean.",
        "file.write.success": "File written successfully.",
        "file.write.validation_issues": "File written successfully, but content validation found issues.",
        "file.update.unchanged": "Line-based replacement ran, but the target range already matched the replacement; the file was unchanged.",
        "file.update.unchanged_validation": "Line-based replacement ran, but the file was unchanged and content validation found issues.",
        "file.update.success": "Successfully applied {operations} update operations and made {replacements} replacements.",
        "file.update.validation_issues": "Applied {operations} update operations and {replacements} replacements, but content validation found issues.",
        "agent.error.session_not_found": "Session not found: {session_id}",
        "agent.error.orchestrator_missing": "No agent orchestrator is available in this session.",
        "agent.error.team_orchestrator_missing": "No Team orchestrator is available in this session.",
        "agent.spawned": "Agent created. ID: {agent_id}. It is ready to receive tasks.",
        "browser.offline": "The browser extension is offline. Confirm that it is installed and that a browser page remains active.",
        "browser.timeout": "The browser command timed out (>{seconds}s).",
        "browser.failed": "The browser command failed.",
        "browser.unsupported_action": "Unsupported browser action: {action}",
        "lint.not_installed": "{tool} is not installed; the check was skipped.",
        "lint.no_config": "No {tool} configuration was found in the project; the check was skipped.",
        "lint.exited": "{tool} failed with exit code {code}.",
        "lint.parse_failed": "Failed to parse {tool} output: {message}",
        "tool_expand.unavailable": "The session context or tool manager is unavailable.",
        "image.default_prompt": "Inspect this image, identify its text and key visual information, and use it with the current conversation to continue the user's task.",
        "image.context": "[Image context injected by a tool]\nImage source: {image_path}\nThe user asked you to inspect this image. Treat its contents as context for the current task and use the image directly in your next response for understanding, description, or reasoning.\n\nUser's image-processing request: {prompt}",
        "image.unsupported": "The current agent model does not support image input. Switch to a multimodal model before analyzing the image.",
        "image.queued": "The image was added to the next multimodal model turn. The agent will continue by inspecting it directly.",
        "image.failed": "Image understanding failed: {message}",
        "web.success": "Successfully processed all {total} URLs.",
        "web.partial": "Successfully processed {success}/{total} URLs; {failed} failed.",
        "web.failed": "Failed to process all {total} URLs.",
        "web.download_failed": "File download failed after {attempts} attempts.",
        "web.fetch_failed": "Webpage fetch failed after {attempts} attempts.",
        "web.timeout": "The request timed out after {seconds} seconds.",
        "shell.approval.timeout": "Sandbox approval timed out; the command was not run.",
        "shell.approval.denied": "Sandbox approval was denied; the command was not run.",
        "shell.approval.approved": "Sandbox approval was granted; running the command.",
        "shell.background": "Started the command in the background with task_id={task_id}; it is still running.",
        "shell.running": "The command is still running after waiting block_until_ms={block_until_ms}.",
        "shell.await_running": "The task is still running after await_shell waited block_until_ms={block_until_ms}.",
        "shell.next.await_now": "call await_shell immediately",
        "shell.next.await_again": "call await_shell again",
        "shell.next.no_progress_only": "do not answer with waiting/progress text only",
        "workflow.execution_failed": "Workflow execution failed: {message}",
        "workflow.error.data_inspection_inappropriate": (
            "The input may contain inappropriate content. Edit it and try again"
        ),
        "workflow.error.data_inspection_failed": (
            "Content safety check failed. Edit the input and try again"
        ),
        "workflow.error.rate_limit": "Too many requests. Try again later",
        "workflow.error.quota": (
            "API quota is insufficient. Check the account balance or quota settings"
        ),
        "workflow.error.authentication": (
            "API authentication failed. Check whether the API key is correct"
        ),
        "workflow.error.model_not_found": (
            "The selected model does not exist or is unavailable. "
            "Check the model configuration"
        ),
        "workflow.error.context_length": "The input is too long. Shorten it and try again",
        "workflow.error.connection": (
            "Network connection failed. Check the network settings or try again later"
        ),
        "workflow.error.service_unavailable": (
            "The service is temporarily unavailable. Try again later"
        ),
        "runtime.tool_call_parse.title": (
            "I tried to call tool `{tool_name}`, but its arguments could not be parsed."
        ),
        "runtime.tool_call_parse.reason_title": "Reason",
        "runtime.tool_call_parse.reason": "Invalid JSON or incomplete argument structure",
        "runtime.tool_call_parse.raw_arguments": "Raw arguments",
        "runtime.tool_call_parse.suggestions_title": "Suggestions",
        "runtime.tool_call_parse.next_step": (
            "I need to adjust the tool call and retry with valid arguments."
        ),
        "runtime.tool_call_parse.suggestion.too_long_split": (
            "• The arguments are long (over 2000 characters); split the work into multiple tool calls"
        ),
        "runtime.tool_call_parse.suggestion.too_long_file": (
            "• Or save large content to a file and pass the file path"
        ),
        "runtime.tool_call_parse.suggestion.braces": (
            "• JSON braces appear unbalanced; check that every brace is paired"
        ),
        "runtime.tool_call_parse.suggestion.quotes": (
            "• A quote appears unclosed; check that string quotes are paired"
        ),
        "runtime.tool_call_parse.suggestion.backslash": (
            "• Backslashes are present; make sure special characters are escaped correctly"
        ),
        "runtime.tool_call_parse.suggestion.check_json": "• Check that the arguments are valid JSON",
        "runtime.tool_call_parse.suggestion.double_quotes": (
            "• Ensure all strings are wrapped in double quotes"
        ),
        "runtime.tool_call_parse.suggestion.commas": (
            "• Ensure there are no trailing commas or missing commas"
        ),
        "runtime.tool.error.arguments_not_object": (
            "Tool argument format error: arguments must be a JSON object"
        ),
        "runtime.tool.error.execution_failed": "Tool {tool_name} failed: {message}",
        "runtime.tool.error.execution_cancelled": "Tool {tool_name} was cancelled",
        "runtime.repeat_recovery.title": "Execution path is repeating",
        "runtime.repeat_recovery.notice": (
            "I detected repeated execution steps and paused to avoid continuing "
            "without progress. Please tell me how I should proceed."
        ),
        "runtime.repeat_recovery.question": (
            "Please describe how you want me to proceed. You may include a new "
            "strategy, constraints, or a request to stop."
        ),
        "runtime.repeat_recovery.answer_title": "Questionnaire answers",
        "runtime.repeat_recovery.question_fallback": "Question",
        "runtime.repeat_recovery.unanswered": "Not answered",
        "runtime.repeat_recovery.answer_separator": ": ",
    },
    "pt": {
        "tool.manager.not_found": "A ferramenta '{tool_name}' não foi encontrada. Ferramentas disponíveis: {available}",
        "tool.manager.missing_parameters": "Parâmetros obrigatórios ausentes: {parameters}",
        "tool.manager.unknown_type": "Tipo de ferramenta desconhecido: {tool_type}",
        "tool.manager.invalid_json": "A ferramenta retornou JSON inválido: {message}",
        "tool.manager.execution_failed": "A ferramenta '{tool_name}' falhou após {seconds} segundos: {message}",
        "tool.manager.cancelled": "A ferramenta '{tool_name}' foi cancelada",
        "tool.result.success": "A ferramenta '{tool_name}' foi executada com sucesso.",
        "tool.result.error": "A execução da ferramenta '{tool_name}' falhou.",
        "tool.error.INVALID_ARGUMENT": "Os parâmetros da ferramenta são inválidos.",
        "tool.error.NOT_FOUND": "O recurso solicitado não foi encontrado.",
        "tool.error.PERMISSION_DENIED": "A operação não tem a permissão necessária.",
        "tool.error.SAFETY_BLOCKED": "A operação foi bloqueada pela política de segurança.",
        "tool.error.MULTIPLE_MATCHES": "Vários resultados corresponderam; restrinja a busca.",
        "tool.error.NO_MATCH": "Nenhum resultado correspondente foi encontrado.",
        "tool.error.TIMEOUT": "A operação excedeu o tempo limite.",
        "tool.error.SANDBOX_ERROR": "A operação no ambiente isolado falhou.",
        "tool.error.NETWORK_ERROR": "A operação de rede falhou.",
        "tool.error.PARSE_ERROR": "Não foi possível analisar o conteúdo.",
        "tool.error.PRECONDITION_FAILED": "Um pré-requisito da operação não foi atendido.",
        "tool.error.UNSUPPORTED": "Esta operação não é compatível.",
        "tool.error.INTERNAL_ERROR": "A ferramenta apresentou uma falha interna.",
        "tool.error.hint": "Revise o código do erro e os detalhes originais, ajuste a operação e tente novamente.",
        "skill.error.session_required": "load_skill requer um session_id válido.",
        "skill.error.invalid_session": "session_id inválido: {session_id}",
        "skill.error.manager_unavailable": "O gerenciador de skills não está disponível nesta sessão.",
        "skill.error.not_found": "O skill '{skill_name}' não foi encontrado. Skills disponíveis: {available}",
        "skill.heading.skill": "Skill",
        "skill.heading.folder": "Caminho da pasta do skill",
        "skill.heading.files": "Estrutura de arquivos",
        "skill.heading.instructions": "Instruções (SKILL.md)",
        "skill.unknown": "Desconhecido",
        "skill.success": "O skill '{skill_name}' foi carregado com sucesso. Skills ativos: {active}. Total: {total}. Siga as instruções no System Prompt.",
        "todo.updated": "A lista de tarefas foi atualizada. Adicionadas: {added}, atualizadas: {updated}, atualmente pendentes: {pending}.",
        "todo.completed": "Todas as tarefas foram concluídas e a lista foi limpa. Adicionadas: {added}, atualizadas: {updated}.",
        "todo.save_failed": "Não foi possível salvar a lista de tarefas.",
        "todo.none": "Não há tarefas pendentes.",
        "todo.list_title": "Tarefas pendentes atuais:",
        "todo.tag.in_progress": "em andamento",
        "todo.tag.pending": "pendente",
        "todo.conclusion": "conclusão",
        "questionnaire.timeout": "O usuário não enviou respostas a tempo. Os valores padrão foram usados.",
        "questionnaire.submitted": "O usuário enviou as respostas.",
        "questionnaire.start.success": "O questionário foi iniciado e está aguardando resposta do usuário, com {count} perguntas.",
        "questionnaire.start.questions_must_be_list": "O campo questions deve ser um array.",
        "questionnaire.start.questions_empty": "O campo questions não pode ficar vazio.",
        "questionnaire.start.question_not_object": "{path} deve ser um objeto.",
        "questionnaire.start.question_type_invalid": "{path} tem tipo de pergunta inválido: {value!r}. Os valores permitidos são {allowed}.",
        "questionnaire.start.question_text_required": "{path} precisa de text ou title.",
        "questionnaire.start.question_id_duplicate": "{path} possui id duplicado: {value}.",
        "questionnaire.start.question_options_required": "{path} para perguntas de escolha requer options.",
        "questionnaire.start.question_option_invalid": "{path} option está inválida; use uma string ou um objeto com value e label.",
        "questionnaire.start.default_type_invalid": "{path} default tem tipo inválido. Esperava {expected}, recebeu {actual}.",
        "questionnaire.start.default_value_not_in_options": "{path} default contém valor(es) inválido(s): {value}.",
        "questionnaire.start.default_list_invalid_items": "{path} default precisa ser uma lista de strings; estes valores não são válidos: {invalid_items}.",
        "questionnaire.start.allow_other_type_invalid": "{path} allow_other deve ser booleano.",
        "file.write.success": "O arquivo foi gravado com sucesso.",
        "file.write.validation_issues": "O arquivo foi gravado, mas a validação de conteúdo encontrou problemas.",
        "file.update.unchanged": "A substituição por linhas foi executada, mas o intervalo já correspondia ao novo conteúdo; o arquivo não foi alterado.",
        "file.update.unchanged_validation": "A substituição por linhas foi executada sem alterar o arquivo, e a validação encontrou problemas.",
        "file.update.success": "Foram aplicadas {operations} operações de atualização e {replacements} substituições.",
        "file.update.validation_issues": "Foram aplicadas {operations} operações e {replacements} substituições, mas a validação encontrou problemas.",
        "agent.error.session_not_found": "Sessão não encontrada: {session_id}",
        "agent.error.orchestrator_missing": "Não há um orquestrador de agentes disponível nesta sessão.",
        "agent.error.team_orchestrator_missing": "Não há um orquestrador de equipe disponível nesta sessão.",
        "agent.spawned": "Agente criado. ID: {agent_id}. Ele está pronto para receber tarefas.",
        "browser.offline": "A extensão do navegador está offline. Confirme que ela está instalada e que uma página continua ativa.",
        "browser.timeout": "O comando do navegador excedeu o tempo limite (>{seconds}s).",
        "browser.failed": "O comando do navegador falhou.",
        "browser.unsupported_action": "Ação do navegador não compatível: {action}",
        "lint.not_installed": "{tool} não está instalado; a verificação foi ignorada.",
        "lint.no_config": "Nenhuma configuração de {tool} foi encontrada no projeto; a verificação foi ignorada.",
        "lint.exited": "{tool} falhou com o código de saída {code}.",
        "lint.parse_failed": "Não foi possível analisar a saída de {tool}: {message}",
        "tool_expand.unavailable": "O contexto da sessão ou o gerenciador de ferramentas não está disponível.",
        "image.default_prompt": "Observe esta imagem, identifique o texto e as principais informações visuais e use-os com a conversa atual para continuar a tarefa do usuário.",
        "image.context": "[Contexto de imagem inserido por uma ferramenta]\nOrigem da imagem: {image_path}\nO usuário pediu que você observe esta imagem. Trate o conteúdo como contexto da tarefa atual e use a imagem diretamente na próxima resposta para compreender, descrever ou raciocinar.\n\nSolicitação do usuário para a imagem: {prompt}",
        "image.unsupported": "O modelo atual do agente não aceita imagens. Mude para um modelo multimodal antes de analisar a imagem.",
        "image.queued": "A imagem foi adicionada ao próximo turno multimodal. O agente continuará analisando-a diretamente.",
        "image.failed": "Falha ao compreender a imagem: {message}",
        "web.success": "Todos os {total} URLs foram processados com sucesso.",
        "web.partial": "Foram processados {success}/{total} URLs; {failed} falharam.",
        "web.failed": "Não foi possível processar nenhum dos {total} URLs.",
        "web.download_failed": "O download do arquivo falhou. Número de tentativas: {attempts}.",
        "web.fetch_failed": "A obtenção da página falhou. Número de tentativas: {attempts}.",
        "web.timeout": "A solicitação excedeu o tempo limite após {seconds} segundos.",
        "shell.approval.timeout": "A aprovação do ambiente isolado expirou; o comando não foi executado.",
        "shell.approval.denied": "A aprovação do ambiente isolado foi negada; o comando não foi executado.",
        "shell.approval.approved": "A aprovação do ambiente isolado foi concedida; executando o comando.",
        "shell.background": "O comando foi iniciado em segundo plano com task_id={task_id}; ele ainda está em execução.",
        "shell.running": "O comando ainda está em execução após aguardar block_until_ms={block_until_ms}.",
        "shell.await_running": "A tarefa ainda está em execução após await_shell aguardar block_until_ms={block_until_ms}.",
        "shell.next.await_now": "chame await_shell imediatamente",
        "shell.next.await_again": "chame await_shell novamente",
        "shell.next.no_progress_only": "não responda apenas com texto de espera ou progresso",
        "workflow.execution_failed": "Falha ao executar o fluxo de trabalho: {message}",
        "workflow.error.data_inspection_inappropriate": (
            "A entrada pode conter conteudo inadequado. Edite e tente novamente"
        ),
        "workflow.error.data_inspection_failed": (
            "A verificacao de seguranca do conteudo falhou. "
            "Edite a entrada e tente novamente"
        ),
        "workflow.error.rate_limit": "Muitas solicitacoes. Tente novamente mais tarde",
        "workflow.error.quota": (
            "A cota da API e insuficiente. "
            "Verifique o saldo da conta ou as configuracoes de cota"
        ),
        "workflow.error.authentication": (
            "A autenticacao da API falhou. Verifique se a chave de API esta correta"
        ),
        "workflow.error.model_not_found": (
            "O modelo selecionado nao existe ou esta indisponivel. "
            "Verifique a configuracao do modelo"
        ),
        "workflow.error.context_length": "A entrada e longa demais. Reduza o texto e tente novamente",
        "workflow.error.connection": (
            "Falha na conexao de rede. "
            "Verifique as configuracoes de rede ou tente novamente mais tarde"
        ),
        "workflow.error.service_unavailable": (
            "O servico esta temporariamente indisponivel. Tente novamente mais tarde"
        ),
        "runtime.tool_call_parse.title": (
            "Tentei chamar a ferramenta `{tool_name}`, mas nao consegui analisar os argumentos."
        ),
        "runtime.tool_call_parse.reason_title": "Motivo",
        "runtime.tool_call_parse.reason": "JSON invalido ou estrutura de argumentos incompleta",
        "runtime.tool_call_parse.raw_arguments": "Argumentos originais",
        "runtime.tool_call_parse.suggestions_title": "Sugestoes",
        "runtime.tool_call_parse.next_step": (
            "Preciso ajustar a chamada da ferramenta e tentar novamente com argumentos validos."
        ),
        "runtime.tool_call_parse.suggestion.too_long_split": (
            "• Os argumentos sao longos (mais de 2000 caracteres); divida o trabalho em varias chamadas de ferramenta"
        ),
        "runtime.tool_call_parse.suggestion.too_long_file": (
            "• Ou salve conteudo grande em um arquivo e passe o caminho do arquivo"
        ),
        "runtime.tool_call_parse.suggestion.braces": (
            "• As chaves JSON parecem desbalanceadas; verifique se cada chave esta pareada"
        ),
        "runtime.tool_call_parse.suggestion.quotes": (
            "• Uma aspa parece nao estar fechada; verifique se as aspas das strings estao pareadas"
        ),
        "runtime.tool_call_parse.suggestion.backslash": (
            "• Ha barras invertidas; verifique se os caracteres especiais foram escapados corretamente"
        ),
        "runtime.tool_call_parse.suggestion.check_json": (
            "• Verifique se os argumentos sao JSON valido"
        ),
        "runtime.tool_call_parse.suggestion.double_quotes": (
            "• Garanta que todas as strings estejam entre aspas duplas"
        ),
        "runtime.tool_call_parse.suggestion.commas": (
            "• Garanta que nao haja virgulas extras ou faltando"
        ),
        "runtime.tool.error.arguments_not_object": (
            "Erro no formato dos argumentos da ferramenta: os argumentos devem ser um objeto JSON"
        ),
        "runtime.tool.error.execution_failed": "Ferramenta {tool_name} falhou: {message}",
        "runtime.tool.error.execution_cancelled": (
            "A ferramenta {tool_name} foi cancelada"
        ),
        "runtime.repeat_recovery.title": "O caminho de execucao esta se repetindo",
        "runtime.repeat_recovery.notice": (
            "Detectei etapas de execucao repetidas e pausei para evitar continuar "
            "sem progresso. Diga como devo prosseguir."
        ),
        "runtime.repeat_recovery.question": (
            "Descreva como voce deseja que eu prossiga. Voce pode incluir uma "
            "nova estrategia, restricoes ou um pedido para parar."
        ),
        "runtime.repeat_recovery.answer_title": "Respostas do questionario",
        "runtime.repeat_recovery.question_fallback": "Pergunta",
        "runtime.repeat_recovery.unanswered": "Nao respondido",
        "runtime.repeat_recovery.answer_separator": ": ",
    },
}


def normalize_language(language: str | None) -> str:
    value = str(language or "").strip().replace("_", "-").lower()
    if not value:
        return DEFAULT_LANGUAGE
    if "zh" in value or "中文" in value:
        return "zh"
    if "pt" in value or "portugu" in value:
        return "pt"
    if "en" in value or "english" in value:
        return "en"
    return DEFAULT_LANGUAGE


def t(
    key: str,
    language: str | None = None,
    params: Mapping[str, Any] | None = None,
    default: str | None = None,
) -> str:
    resolved_language = normalize_language(language)
    template = MESSAGES.get(resolved_language, {}).get(key)
    if template is None:
        template = MESSAGES[DEFAULT_LANGUAGE].get(key)
    if template is None:
        return default if default is not None else key
    if params:
        return template.format(**params)
    return template


def get_tool_language() -> str:
    """Return the trusted language bound to the current tool execution task."""
    return _TOOL_LANGUAGE.get()


def set_tool_language(language: str | None) -> Token[str]:
    """Bind a normalized language and return a token suitable for reset."""
    return _TOOL_LANGUAGE.set(normalize_language(language or DEFAULT_TOOL_LANGUAGE))


def reset_tool_language(token: Token[str]) -> None:
    _TOOL_LANGUAGE.reset(token)


@contextmanager
def tool_language(language: str | None) -> Iterator[str]:
    """Temporarily bind the language for one (possibly async) tool call."""
    token = set_tool_language(language)
    try:
        yield get_tool_language()
    finally:
        reset_tool_language(token)


def tool_t(
    key: str,
    params: Mapping[str, Any] | None = None,
    default: str | None = None,
) -> str:
    """Translate tool-authored text using the task-local trusted language."""
    return t(key, language=get_tool_language(), params=params, default=default)
