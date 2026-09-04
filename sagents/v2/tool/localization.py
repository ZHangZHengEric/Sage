"""Localized metadata for SAgents-owned V2 tools.

V1 exposes detailed Chinese, English, and Portuguese tool metadata.  V2 keeps
its execution contracts independent, but presents the same language surface to
models and catalog UIs through this projection layer.
"""

from __future__ import annotations

import copy
from typing import Any

from sagents.v2.tool.contracts import ToolDefinition


ToolText = tuple[str, str, str]


def _text(zh: str, en: str, pt: str) -> ToolText:
    return (zh, en, pt)


_TOOL_DESCRIPTIONS: dict[str, ToolText] = {
    "file_read": _text(
        "读取文本文件指定行范围内容。",
        "Read text from a selected line range in a file.",
        "Ler um intervalo de linhas de um arquivo de texto.",
    ),
    "file_write": _text(
        "写入文本到文件。适合短内容；较长代码或文档请拆成多次追加写入。",
        "Write text to a file. Use multiple append calls for longer code or documents.",
        "Gravar texto em um arquivo; use várias chamadas de anexação para conteúdo longo.",
    ),
    "file_update": _text(
        "更新单个文件的局部内容。优先使用局部替换或按行区间替换，不要整文件重写。",
        "Update targeted parts of one file. Prefer local or line-range replacement over rewriting the whole file.",
        "Atualizar partes específicas de um arquivo sem reescrevê-lo por completo.",
    ),
    "apply_patch": _text(
        "一次性对工作区中的一个或多个文本文件应用结构化补丁；所有操作会先预检，失败时尽力回滚。",
        "Apply one structured patch to one or more workspace files. Operations are preflighted and failed writes trigger best-effort rollback.",
        "Aplicar um patch estruturado a um ou mais arquivos, com validação prévia e reversão em caso de falha.",
    ),
    "grep": _text(
        "在工作区执行结构化全文搜索并返回文件、行号和匹配内容。优先使用本工具而不是手写 shell rg。",
        "Run structured full-text search and return files, line numbers, and matches. Prefer this over hand-written shell rg.",
        "Pesquisar texto no workspace e retornar arquivos, linhas e correspondências estruturadas.",
    ),
    "glob": _text(
        "按 glob 表达式查找文件，支持 ** 跨目录和常用通配符。",
        "Find files by glob pattern, including ** recursive matching and common wildcards.",
        "Localizar arquivos por padrão glob, incluindo correspondência recursiva com **.",
    ),
    "list_dir": _text(
        "以紧凑文本树列出目录结构，默认忽略 .git、node_modules 等噪音。",
        "List a directory as a compact text tree, ignoring noise such as .git and node_modules by default.",
        "Listar um diretório como árvore de texto compacta, ignorando ruído comum por padrão.",
    ),
    "execute_shell_command": _text(
        "在沙箱中执行 Shell 命令。可同步等待，也可后台运行并返回 task_id；需要结果时继续调用 await_shell。",
        "Execute a shell command in the sandbox. Wait synchronously or run it in the background and use await_shell when its result is needed.",
        "Executar um comando shell no sandbox, aguardando-o ou continuando em segundo plano com await_shell.",
    ),
    "await_shell": _text(
        "等待后台 Shell 任务并读取输出；可在正则命中时提前返回，结束后返回退出码。",
        "Wait for a background shell task and read its output; optionally return early when a regex matches.",
        "Aguardar uma tarefa shell em segundo plano e ler sua saída, com retorno antecipado por regex.",
    ),
    "kill_shell": _text(
        "终止后台 Shell 任务；先发送 SIGTERM，必要时升级为 SIGKILL。",
        "Terminate a background shell task with SIGTERM, escalating to SIGKILL when necessary.",
        "Encerrar uma tarefa shell com SIGTERM e, se necessário, SIGKILL.",
    ),
    "todo_write": _text(
        "增量创建或更新任务清单。只提交新增或真正变化的任务；执行前标记 in_progress，完成后标记 completed 并填写结论。",
        "Incrementally create or update the task list. Send only new or changed tasks; mark work in_progress before starting and completed with a conclusion when done.",
        "Criar ou atualizar a lista de tarefas de forma incremental, enviando apenas itens novos ou alterados.",
    ),
    "todo_read": _text(
        "读取当前任务清单及其状态。",
        "Read the current task list and task states.",
        "Ler a lista de tarefas atual e seus estados.",
    ),
    "goal_submit": _text(
        "提交当前 Run 的完整目标正文。计划模式下正文是待审批计划；目标模式下正文是直接执行目标。",
        "Submit the complete goal for this Run. In Plan mode it is the Plan awaiting approval; in Goal mode it is the direct execution goal.",
        "Enviar o objetivo completo desta execução; no modo de plano, o conteúdo é o plano que aguarda aprovação.",
    ),
    "turn_status": _text(
        "报告本轮执行状态。调用前必须先向用户说明结果、问题或阻塞原因。",
        "Report the current turn status. Produce user-facing result, question, or blocker text before calling it.",
        "Informar o estado do turno após apresentar ao usuário o resultado, a pergunta ou o bloqueio.",
    ),
    "tool_expand_tools": _text(
        "按准确名称扩展当前 Run 可见的工具；成功后重新调用原本需要的工具。",
        "Activate exact tool names for the current Run, then retry the tool that was originally needed.",
        "Ativar ferramentas pelo nome exato no Run atual e repetir a chamada necessária.",
    ),
    "search_memory": _text(
        "搜索 Agent 的长期记忆和相关会话信息，返回最相关的内容。",
        "Search the Agent's long-term memory and relevant session information.",
        "Pesquisar a memória de longo prazo do Agent e informações relevantes da sessão.",
    ),
    "fetch_webpages": _text(
        "抓取网页文本或下载远程文件到工作区，支持超时、重试和内容长度限制。",
        "Fetch webpage text or download remote files into the workspace with timeout, retry, and length controls.",
        "Buscar texto de páginas ou baixar arquivos remotos com controle de tempo, tentativas e tamanho.",
    ),
    "analyze_image": _text(
        "将图片加入下一轮多模态模型上下文，让 Agent 原生观察图片并继续推理。",
        "Attach an image to the next multimodal model turn so the Agent can inspect it natively.",
        "Anexar uma imagem ao próximo turno multimodal para análise nativa pelo Agent.",
    ),
    "read_lints": _text(
        "对指定 Python、JavaScript 或 TypeScript 文件运行可用的静态检查并返回结构化诊断。",
        "Run available static checks on selected Python, JavaScript, or TypeScript files and return structured diagnostics.",
        "Executar verificações estáticas nos arquivos indicados e retornar diagnósticos estruturados.",
    ),
    "questionnaire_async": _text(
        "校验并发起 Markdown 风格问卷，返回等待用户回复的状态。",
        "Validate and start a Markdown-style questionnaire, returning a pending-user-input status.",
        "Validar e iniciar um questionário em Markdown, retornando estado de espera pelo usuário.",
    ),
    "load_skill": _text(
        "加载一个已启用 Skill 的说明与工作区资源，并在当前 Run 中激活。",
        "Load an enabled Skill's instructions and workspace resources into the current Run.",
        "Carregar as instruções e os recursos de um Skill habilitado no Run atual.",
    ),
    "goal_complete": _text(
        "在独立验证全部验收标准后完成当前目标。成功后，向用户简洁总结交付物、实际验证结果和剩余限制。",
        "Complete the active goal after independently verifying every acceptance criterion. After success, give the user a concise summary of deliverables, actual verification, and remaining limitations.",
        "Concluir o objetivo ativo após verificar de forma independente todos os critérios de aceitação. Após o sucesso, resumir para o usuário as entregas, a verificação realizada e as limitações restantes.",
    ),
    "sys_spawn_agent": _text(
        "创建一个可在当前会话中复用的通用专家子智能体；system_prompt 用于定义角色与能力，而不是一次性任务。",
        "Create a reusable general-purpose expert sub-agent for the current session; system_prompt defines its role and capabilities, not a one-off task.",
        "Criar um subagente especialista reutilizável na sessão atual; system_prompt define seu papel e capacidades, não uma tarefa única.",
    ),
    "sys_delegate_task": _text(
        "把一个或多个具体任务并发委派给已有子智能体。",
        "Delegate one or more concrete tasks concurrently to existing sub-agents.",
        "Delegar uma ou mais tarefas concretas simultaneamente a subagentes existentes.",
    ),
    "sys_team_delegate_task": _text(
        "把一个或多个具体任务并发委派给已有团队成员。",
        "Delegate one or more concrete tasks concurrently to existing Team members.",
        "Delegar uma ou mais tarefas concretas simultaneamente a membros existentes da equipe.",
    ),
}


_FIELD_DESCRIPTIONS: dict[str, ToolText] = {
    "file_path": _text(
        "文件虚拟路径", "Virtual path to the file", "Caminho virtual do arquivo"
    ),
    "path": _text(
        "搜索或遍历的虚拟根路径",
        "Virtual root path to search or traverse",
        "Caminho virtual raiz para busca",
    ),
    "start_line": _text(
        "起始行号，从 0 开始", "Zero-based start line", "Linha inicial baseada em zero"
    ),
    "end_line": _text(
        "结束行号；具体是否包含边界由该工具定义",
        "End line; boundary behavior is defined by the tool",
        "Linha final; o limite depende da ferramenta",
    ),
    "include_line_numbers": _text(
        "是否在结果中包含行号",
        "Whether to include line numbers",
        "Se deve incluir números de linha",
    ),
    "content": _text(
        "要写入或处理的文本内容",
        "Text content to write or process",
        "Conteúdo textual a gravar ou processar",
    ),
    "name": _text("名称", "Name", "Nome"),
    "description": _text("角色描述", "Role description", "Descrição do papel"),
    "system_prompt": _text(
        "定义子智能体角色、职责与能力的系统提示词",
        "System prompt defining the sub-agent role, responsibilities, and capabilities",
        "Prompt de sistema que define o papel, as responsabilidades e as capacidades do subagente",
    ),
    "agent_id": _text(
        "目标智能体的准确 ID",
        "Exact target agent ID",
        "ID exato do agente de destino",
    ),
    "task_name": _text(
        "可选的简短稳定任务名",
        "Optional short stable task name",
        "Nome curto e estável opcional da tarefa",
    ),
    "original_task": _text(
        "用于补充上下文的原始用户请求",
        "Original user request supplied as additional context",
        "Solicitação original do usuário fornecida como contexto adicional",
    ),
    "mode": _text("操作模式", "Operation mode", "Modo da operação"),
    "operations": _text(
        "局部更新操作列表",
        "List of targeted update operations",
        "Lista de operações de atualização",
    ),
    "update_mode": _text(
        "更新模式：search_replace 或 line_range",
        "Update mode: search_replace or line_range",
        "Modo: search_replace ou line_range",
    ),
    "search_pattern": _text(
        "要查找的文本或正则表达式",
        "Text or regular expression to find",
        "Texto ou expressão regular a localizar",
    ),
    "replacement": _text("替换内容", "Replacement content", "Conteúdo de substituição"),
    "replace_all": _text(
        "是否替换全部匹配项",
        "Whether to replace every match",
        "Se deve substituir todas as correspondências",
    ),
    "patch": _text(
        "由 Begin Patch / End Patch 包裹的结构化补丁文本",
        "Structured patch text wrapped by Begin Patch / End Patch",
        "Patch estruturado entre Begin Patch e End Patch",
    ),
    "pattern": _text(
        "搜索表达式或匹配模式",
        "Search expression or matching pattern",
        "Expressão de busca ou padrão",
    ),
    "glob": _text("文件 glob 过滤器", "File glob filter", "Filtro glob de arquivos"),
    "type": _text("文件类型过滤器", "File type filter", "Filtro de tipo de arquivo"),
    "output_mode": _text("结果输出模式", "Result output mode", "Modo de saída"),
    "case_insensitive": _text(
        "是否忽略大小写",
        "Whether matching is case-insensitive",
        "Se a busca ignora maiúsculas",
    ),
    "multiline": _text(
        "是否启用跨行匹配",
        "Whether multiline matching is enabled",
        "Se a busca multilinha está ativa",
    ),
    "before_lines": _text(
        "匹配前的上下文行数",
        "Context lines before a match",
        "Linhas antes da correspondência",
    ),
    "after_lines": _text(
        "匹配后的上下文行数",
        "Context lines after a match",
        "Linhas após a correspondência",
    ),
    "context_lines": _text(
        "匹配前后的上下文行数",
        "Context lines around a match",
        "Linhas ao redor da correspondência",
    ),
    "head_limit": _text(
        "最多返回的结果数", "Maximum number of results", "Número máximo de resultados"
    ),
    "depth": _text(
        "目录遍历深度", "Directory traversal depth", "Profundidade da árvore"
    ),
    "max_items_per_dir": _text(
        "每个目录最多展示的条目数",
        "Maximum entries per directory",
        "Máximo de itens por diretório",
    ),
    "include_hidden": _text(
        "是否包含隐藏文件",
        "Whether to include hidden files",
        "Se deve incluir arquivos ocultos",
    ),
    "command": _text(
        "要执行的 Shell 命令", "Shell command to execute", "Comando shell a executar"
    ),
    "workdir": _text(
        "命令工作目录；默认使用工作区",
        "Command working directory; defaults to the workspace",
        "Diretório do comando; padrão é o workspace",
    ),
    "block_until_ms": _text(
        "同步等待毫秒数；0 表示立即后台运行",
        "Milliseconds to wait; 0 starts in the background immediately",
        "Milissegundos de espera; 0 inicia em segundo plano",
    ),
    "env_vars": _text(
        "附加环境变量 JSON 对象",
        "Additional environment variables as a JSON object",
        "Variáveis adicionais como objeto JSON",
    ),
    "approval_id": _text(
        "已批准请求的标识符",
        "Identifier of an approved request",
        "Identificador de uma aprovação",
    ),
    "sandbox_approval_mode": _text(
        "运行时沙箱审批模式",
        "Runtime sandbox approval mode",
        "Modo de aprovação do sandbox",
    ),
    "command_policy": _text(
        "运行时命令执行策略",
        "Runtime command execution policy",
        "Política de execução de comandos",
    ),
    "task_id": _text(
        "后台任务标识符",
        "Background task identifier",
        "Identificador da tarefa em segundo plano",
    ),
    "tasks": _text("任务列表", "Task list", "Lista de tarefas"),
    "id": _text(
        "稳定且唯一的标识符",
        "Stable unique identifier",
        "Identificador estável e exclusivo",
    ),
    "conclusion": _text(
        "任务完成后的结论或说明",
        "Conclusion or note recorded when the task is complete",
        "Conclusão registrada ao finalizar a tarefa",
    ),
    "status": _text("稳定的状态值", "Stable status value", "Valor de estado estável"),
    "note": _text(
        "面向用户的简短状态备注",
        "Short user-facing status note",
        "Nota curta de estado para o usuário",
    ),
    "tool_names": _text(
        "要启用的准确工具名列表",
        "Exact tool names to activate",
        "Nomes exatos das ferramentas a ativar",
    ),
    "query": _text("记忆查询文本", "Memory search query", "Consulta de memória"),
    "top_k": _text(
        "最多返回的结果数", "Maximum number of results", "Número máximo de resultados"
    ),
    "urls": _text(
        "要抓取或下载的 URL 列表",
        "URLs to fetch or download",
        "URLs a buscar ou baixar",
    ),
    "max_length_per_url": _text(
        "每个 URL 最多返回的文本字符数",
        "Maximum text characters returned per URL",
        "Máximo de caracteres por URL",
    ),
    "timeout": _text(
        "单次请求超时秒数",
        "Timeout per request in seconds",
        "Tempo limite por requisição",
    ),
    "retries": _text(
        "失败后的重试次数",
        "Number of retries after failure",
        "Número de tentativas após falha",
    ),
    "image_path": _text(
        "图片虚拟路径或 HTTP/HTTPS URL",
        "Image virtual path or HTTP/HTTPS URL",
        "Caminho virtual ou URL HTTP/HTTPS da imagem",
    ),
    "prompt": _text(
        "指导模型如何观察图片的可选提示词",
        "Optional prompt guiding how the model should inspect the image",
        "Prompt opcional para orientar a análise da imagem",
    ),
    "paths": _text(
        "要检查的文件虚拟路径列表",
        "Virtual paths of files to inspect",
        "Caminhos virtuais dos arquivos",
    ),
    "max_diagnostics": _text(
        "最多返回的诊断条数", "Maximum diagnostics to return", "Máximo de diagnósticos"
    ),
    "title": _text(
        "面向用户的问卷标题",
        "User-facing questionnaire title",
        "Título do questionário",
    ),
    "questions": _text(
        "问题列表；选择题需提供选项",
        "Questions; choice questions require options",
        "Perguntas; questões de escolha exigem opções",
    ),
    "question": _text(
        "面向用户的问题文本",
        "User-facing question text",
        "Texto da pergunta para o usuário",
    ),
    "options": _text(
        "选择题的可选项列表",
        "Choices for a selection question",
        "Opções da pergunta de escolha",
    ),
    "label": _text(
        "面向用户显示的选项文本",
        "User-facing choice label",
        "Rótulo da opção para o usuário",
    ),
    "value": _text(
        "稳定且不翻译的选项值",
        "Stable choice value; do not translate it",
        "Valor estável da opção; não traduzir",
    ),
    "default": _text("默认答案", "Default answer", "Resposta padrão"),
    "placeholder": _text(
        "文本输入提示", "Text input hint", "Dica para entrada de texto"
    ),
    "allow_other": _text(
        "是否允许用户填写其他选项",
        "Whether the user may enter another choice",
        "Se o usuário pode informar outra opção",
    ),
    "questionnaire_id": _text(
        "用于关联问卷结果的稳定标识符",
        "Stable identifier used to correlate questionnaire results",
        "Identificador estável do questionário",
    ),
    "wait_time": _text(
        "等待用户提交的最长秒数",
        "Maximum seconds to wait for submission",
        "Segundos máximos para aguardar envio",
    ),
    "questionnaire_kind": _text(
        "问卷用途类型", "Questionnaire purpose", "Finalidade do questionário"
    ),
    "skill_name": _text(
        "要加载的已启用 Skill 准确名称",
        "Exact enabled Skill name to load",
        "Nome exato do Skill habilitado",
    ),
    "session_id": _text(
        "当前会话标识符（通常由运行时注入）",
        "Current session identifier (normally runtime-injected)",
        "Identificador da sessão atual (normalmente injetado)",
    ),
    "summary": _text(
        "完成目标后的验证摘要",
        "Verification summary recorded when the goal is completed",
        "Resumo da verificação registrado ao concluir o objetivo",
    ),
}


_TOOL_FIELD_OVERRIDES: dict[tuple[str, str], ToolText] = {
    ("goal_submit", "content"): _text(
        "完整目标正文；计划模式中填写待审批计划，可使用任意文本或 Markdown 格式",
        "Complete goal body; in Plan mode, provide the Plan awaiting approval as plain text or Markdown",
        "Objetivo completo; no modo de plano, forneça o plano para aprovação em texto livre ou Markdown",
    ),
    ("file_write", "mode"): _text(
        "写入模式：overwrite 覆盖，append 追加",
        "Write mode: overwrite replaces; append adds to the end",
        "Modo: overwrite substitui; append acrescenta",
    ),
    ("file_update", "operations"): _text(
        "更新操作列表；每项选择 search_replace 或 line_range，并只提交需要改变的范围",
        "Update operations; each selects search_replace or line_range and targets only the content that must change",
        "Operações search_replace ou line_range apenas para o conteúdo alterado",
    ),
    ("grep", "pattern"): _text(
        "正则表达式；默认按 ripgrep/PCRE2 风格解析",
        "Regex pattern, interpreted with ripgrep/PCRE2 semantics by default",
        "Expressão regular no estilo ripgrep/PCRE2",
    ),
    ("glob", "pattern"): _text(
        "glob 表达式，例如 **/*.py",
        "Glob expression such as **/*.py",
        "Expressão glob, por exemplo **/*.py",
    ),
    ("await_shell", "pattern"): _text(
        "可选正则；命中输出时提前返回",
        "Optional regex; return early when output matches",
        "Regex opcional para retorno antecipado",
    ),
    ("todo_write", "tasks"): _text(
        "只包含本次新增或真正变化的任务；更新时仅提供 id 和变化字段",
        "Only tasks that are new or actually changed; updates contain the id and changed fields only",
        "Apenas tarefas novas ou alteradas; atualizações incluem id e campos modificados",
    ),
    ("turn_status", "status"): _text(
        "task_done / need_user_input / blocked / continue_work / failed",
        "task_done / need_user_input / blocked / continue_work / failed",
        "task_done / need_user_input / blocked / continue_work / failed",
    ),
}


def normalize_tool_language(language: str | None) -> str:
    value = (language or "en").strip().lower().replace("-", "_")
    for supported in ("zh", "en", "pt", "es", "fr", "de", "ja", "ko", "ru"):
        if value == supported or value.startswith(f"{supported}_"):
            return supported
    return "en"


def _select(value: ToolText, language: str) -> str:
    return value[{"zh": 0, "en": 1, "pt": 2}.get(language, 1)]


def _generic_tool_description(tool_name: str, language: str) -> str:
    templates = {
        "es": "Herramienta para ejecutar la operación {name}.",
        "fr": "Outil permettant d’exécuter l’opération {name}.",
        "de": "Werkzeug zum Ausführen der Operation {name}.",
        "ja": "{name} 操作を実行するためのツールです。",
        "ko": "{name} 작업을 실행하는 도구입니다.",
        "ru": "Инструмент для выполнения операции {name}.",
    }
    return templates.get(language, "Tool for the {name} operation.").format(
        name=tool_name
    )


def _generic_field_description(field_name: str, language: str) -> str:
    templates = {
        "es": "Parámetro {name} de la herramienta.",
        "fr": "Paramètre d’outil {name}.",
        "de": "Werkzeugparameter {name}.",
        "ja": "ツールの {name} パラメーター。",
        "ko": "도구의 {name} 매개변수입니다.",
        "ru": "Параметр инструмента {name}.",
    }
    return templates.get(language, "Tool parameter {name}.").format(name=field_name)


def _localize_schema(node: Any, tool_name: str, language: str) -> Any:
    if not isinstance(node, dict):
        return node
    properties = node.get("properties")
    if isinstance(properties, dict):
        for field_name, child in properties.items():
            if not isinstance(child, dict):
                continue
            text = _TOOL_FIELD_OVERRIDES.get((tool_name, field_name))
            text = text or _FIELD_DESCRIPTIONS.get(field_name)
            if text is not None:
                child["description"] = (
                    _select(text, language)
                    if language in {"zh", "en", "pt"}
                    else _generic_field_description(field_name, language)
                )
            _localize_schema(child, tool_name, language)
    items = node.get("items")
    if isinstance(items, dict):
        _localize_schema(items, tool_name, language)
    for keyword in ("anyOf", "oneOf", "allOf", "prefixItems"):
        values = node.get(keyword)
        if isinstance(values, list):
            for value in values:
                _localize_schema(value, tool_name, language)
    for keyword in ("additionalProperties", "contains", "not", "if", "then", "else"):
        value = node.get(keyword)
        if isinstance(value, dict):
            _localize_schema(value, tool_name, language)
    return node


def localize_tool_definition(
    definition: ToolDefinition, language: str | None
) -> ToolDefinition:
    """Return one provider-safe localized projection of a Tool definition."""

    description = _TOOL_DESCRIPTIONS.get(definition.name)
    if description is None:
        return definition
    normalized = normalize_tool_language(language)
    schema = _localize_schema(
        copy.deepcopy(definition.input_schema), definition.name, normalized
    )
    return definition.model_copy(
        update={
            "description": (
                _select(description, normalized)
                if normalized in {"zh", "en", "pt"}
                else _generic_tool_description(definition.name, normalized)
            ),
            "input_schema": schema,
        }
    )


__all__ = [
    "localize_tool_definition",
    "normalize_tool_language",
]
