"""Central i18n enrichment for Sage-authored built-in tool schemas.

The decorators remain the source of the detailed Chinese and English wording.
This module fills the Portuguese surface and recursively covers nested parameter
and return-schema fields, which the legacy top-level maps could not describe.
External MCP schemas are deliberately left untouched.
"""

from __future__ import annotations

from typing import Any, Dict, MutableMapping, Optional


TOOL_PT_DESCRIPTIONS: Dict[str, str] = {
    "file_read": "Ler um intervalo de linhas de um arquivo de texto.",
    "file_write": "Gravar texto em um arquivo.",
    "file_update": "Atualizar partes específicas de um único arquivo.",
    "grep": "Pesquisar conteúdo de arquivos com uma expressão regular.",
    "glob": "Localizar arquivos por um padrão glob.",
    "list_dir": "Listar a estrutura de um diretório.",
    "execute_shell_command": "Executar um comando de shell no ambiente isolado.",
    "await_shell": "Aguardar e consultar a saída de uma tarefa de shell.",
    "kill_shell": "Encerrar uma tarefa de shell em execução.",
    "read_lints": "Executar diagnósticos estáticos nos arquivos indicados.",
    "todo_write": "Criar ou atualizar incrementalmente a lista de tarefas.",
    "todo_read": "Ler a lista de tarefas atual.",
    "questionnaire": "Exibir um questionário ao usuário e coletar as respostas.",
    "questionnaire_async": "Iniciar um questionário e aguardar a resposta do usuário.",
    "turn_status": "Informar o estado atual da execução ao usuário.",
    "search_memory": "Pesquisar informações relevantes na memória do usuário.",
    "fetch_webpages": "Baixar e extrair o conteúdo das páginas informadas.",
    "analyze_image": "Carregar uma imagem para análise pelo modelo.",
    "tool_expand_tools": "Disponibilizar ferramentas adicionais no turno atual.",
    "load_skill": "Carregar as instruções e a estrutura de um skill na sessão.",
    "sys_spawn_agent": "Criar um novo subagente com uma função especializada.",
    "sys_delegate_task": "Delegar tarefas concorrentes a subagentes existentes.",
    "sys_team_delegate_task": "Delegar tarefas concorrentes aos membros existentes da equipe.",
    "browser_get_context": "Obter o contexto atual do navegador conectado.",
    "browser_navigate": "Navegar a guia atual para uma URL.",
    "browser_find_text": "Localizar texto na página atual.",
    "browser_scroll": "Rolar a página atual.",
    "browser_send_keys": "Enviar teclas a um elemento da página.",
    "browser_wait": "Aguardar por um intervalo curto no navegador.",
    "browser_list_tabs": "Listar as guias abertas do navegador.",
    "browser_switch_tab": "Mudar para outra guia do navegador.",
    "browser_select_dropdown": "Selecionar uma opção em uma lista da página.",
    "browser_upload_file": "Enviar um arquivo a um campo de upload da página.",
    "browser_screenshot": "Capturar uma imagem da página atual.",
    "browser_dom_action": "Executar uma ação estruturada no DOM do navegador.",
}


def _field(zh: str, en: str, pt: str) -> Dict[str, str]:
    return {"zh": zh, "en": en, "pt": pt}


FIELD_I18N: Dict[str, Dict[str, str]] = {
    "file_path": _field(
        "文件虚拟路径", "File virtual path", "Caminho virtual do arquivo"
    ),
    "path": _field("搜索根目录路径", "Search root path", "Caminho raiz da busca"),
    "start_line": _field("起始行号", "Start line number", "Número da linha inicial"),
    "end_line": _field("结束行号", "End line number", "Número da linha final"),
    "include_line_numbers": _field(
        "是否包含行号",
        "Whether to include line numbers",
        "Se a saída deve incluir números de linha",
    ),
    "content": _field(
        "内容或详细说明",
        "Content or detailed description",
        "Conteúdo ou descrição detalhada",
    ),
    "mode": _field("操作模式", "Operation mode", "Modo da operação"),
    "operations": _field(
        "局部更新操作列表",
        "List of local update operations",
        "Lista de operações de atualização local",
    ),
    "update_mode": _field("更新模式", "Update mode", "Modo de atualização"),
    "search_pattern": _field(
        "要查找的文本或正则表达式",
        "Text or regular expression to find",
        "Texto ou expressão regular a localizar",
    ),
    "replacement": _field(
        "替换内容", "Replacement content", "Conteúdo de substituição"
    ),
    "replace_all": _field(
        "是否替换全部匹配项",
        "Whether to replace every match",
        "Se todas as correspondências devem ser substituídas",
    ),
    "pattern": _field("搜索模式", "Search pattern", "Padrão de busca"),
    "glob": _field("文件 glob 过滤器", "File glob filter", "Filtro glob de arquivos"),
    "type": _field("类型", "Type", "Tipo"),
    "output_mode": _field(
        "结果输出模式", "Result output mode", "Modo de saída dos resultados"
    ),
    "case_insensitive": _field(
        "是否忽略大小写",
        "Whether matching is case-insensitive",
        "Se a busca ignora maiúsculas e minúsculas",
    ),
    "multiline": _field(
        "是否启用多行匹配",
        "Whether multiline matching is enabled",
        "Se a correspondência multilinha está ativada",
    ),
    "before_lines": _field(
        "匹配前的上下文行数",
        "Context lines before a match",
        "Linhas de contexto antes da correspondência",
    ),
    "after_lines": _field(
        "匹配后的上下文行数",
        "Context lines after a match",
        "Linhas de contexto depois da correspondência",
    ),
    "context_lines": _field(
        "匹配前后的上下文行数",
        "Context lines around a match",
        "Linhas de contexto ao redor da correspondência",
    ),
    "head_limit": _field(
        "最大结果数量", "Maximum number of results", "Número máximo de resultados"
    ),
    "depth": _field(
        "目录遍历深度",
        "Directory traversal depth",
        "Profundidade de navegação no diretório",
    ),
    "max_items_per_dir": _field(
        "每个目录的最大条目数",
        "Maximum items per directory",
        "Máximo de itens por diretório",
    ),
    "include_hidden": _field(
        "是否包含隐藏文件",
        "Whether to include hidden files",
        "Se arquivos ocultos devem ser incluídos",
    ),
    "command": _field(
        "要执行的 shell 命令", "Shell command to execute", "Comando de shell a executar"
    ),
    "workdir": _field("工作目录", "Working directory", "Diretório de trabalho"),
    "block_until_ms": _field(
        "同步等待毫秒数",
        "Milliseconds to wait synchronously",
        "Milissegundos de espera síncrona",
    ),
    "env_vars": _field(
        "附加环境变量",
        "Additional environment variables",
        "Variáveis de ambiente adicionais",
    ),
    "approval_id": _field(
        "已批准请求的标识符",
        "Identifier of an approved request",
        "Identificador de uma solicitação aprovada",
    ),
    "sandbox_approval_mode": _field(
        "沙箱审批模式", "Sandbox approval mode", "Modo de aprovação do ambiente isolado"
    ),
    "command_policy": _field(
        "命令执行策略", "Command execution policy", "Política de execução de comandos"
    ),
    "task_id": _field("任务标识符", "Task identifier", "Identificador da tarefa"),
    "paths": _field(
        "要检查的文件路径", "File paths to inspect", "Caminhos dos arquivos a verificar"
    ),
    "max_diagnostics": _field(
        "最大诊断数量", "Maximum number of diagnostics", "Número máximo de diagnósticos"
    ),
    "tasks": _field("任务列表", "Task list", "Lista de tarefas"),
    "id": _field("唯一标识符", "Unique identifier", "Identificador exclusivo"),
    "status": _field("稳定的状态值", "Stable status value", "Valor de estado estável"),
    "conclusion": _field(
        "任务结论或说明，应使用当前回复语言",
        "Task conclusion or note; use the response language",
        "Conclusão ou observação da tarefa; use o idioma de resposta",
    ),
    "title": _field(
        "面向用户的标题，应使用当前回复语言",
        "User-facing title; use the response language",
        "Título exibido ao usuário; use o idioma de resposta",
    ),
    "questions": _field("问题列表", "List of questions", "Lista de perguntas"),
    "questionnaire_id": _field(
        "问卷标识符", "Questionnaire identifier", "Identificador do questionário"
    ),
    "wait_time": _field(
        "最长等待秒数",
        "Maximum wait time in seconds",
        "Tempo máximo de espera em segundos",
    ),
    "questionnaire_kind": _field(
        "问卷类型", "Questionnaire kind", "Tipo de questionário"
    ),
    "options": _field("可选项列表", "List of choices", "Lista de opções"),
    "label": _field(
        "面向用户的选项文本，应使用当前回复语言",
        "User-facing choice text; use the response language",
        "Texto da opção exibido ao usuário; use o idioma de resposta",
    ),
    "value": _field(
        "稳定且不翻译的选项值",
        "Stable option value; do not translate it",
        "Valor estável da opção; não o traduza",
    ),
    "default": _field("默认值", "Default value", "Valor padrão"),
    "placeholder": _field(
        "面向用户的输入提示，应使用当前回复语言",
        "User-facing input hint; use the response language",
        "Dica de entrada exibida ao usuário; use o idioma de resposta",
    ),
    "max_length": _field(
        "最大字符数", "Maximum character count", "Número máximo de caracteres"
    ),
    "query": _field("查询文本", "Query text", "Texto da consulta"),
    "top_k": _field(
        "最多返回的结果数", "Maximum number of results", "Número máximo de resultados"
    ),
    "urls": _field("要获取的 URL 列表", "URLs to fetch", "URLs a buscar"),
    "max_length_per_url": _field(
        "每个 URL 的最大内容长度",
        "Maximum content length per URL",
        "Tamanho máximo do conteúdo por URL",
    ),
    "timeout": _field("超时时间", "Timeout", "Tempo limite"),
    "retries": _field(
        "失败重试次数", "Number of retries", "Número de novas tentativas"
    ),
    "image_path": _field(
        "图片路径或 URL", "Image path or URL", "Caminho ou URL da imagem"
    ),
    "prompt": _field(
        "图片分析提示，应使用当前回复语言",
        "Image analysis prompt; use the response language",
        "Instrução para analisar a imagem; use o idioma de resposta",
    ),
    "tool_names": _field(
        "要启用的准确工具名",
        "Exact tool names to enable",
        "Nomes exatos das ferramentas a ativar",
    ),
    "note": _field(
        "面向用户的状态说明，应使用当前回复语言",
        "User-facing status note; use the response language",
        "Observação de estado exibida ao usuário; use o idioma de resposta",
    ),
    "skill_name": _field(
        "要加载的 skill 名称，保持原样",
        "Name of the skill to load; preserve it verbatim",
        "Nome do skill a carregar; preserve-o literalmente",
    ),
    "name": _field(
        "名称，应匹配当前回复语言",
        "Name; match the response language",
        "Nome; use o idioma de resposta",
    ),
    "description": _field(
        "说明，应使用当前回复语言",
        "Description; use the response language",
        "Descrição; use o idioma de resposta",
    ),
    "system_prompt": _field(
        "子智能体系统提示词，应使用当前回复语言",
        "Sub-agent system prompt; use the response language",
        "Prompt de sistema do subagente; use o idioma de resposta",
    ),
    "agent_id": _field(
        "目标智能体标识符",
        "Target agent identifier",
        "Identificador do agente de destino",
    ),
    "task_name": _field(
        "稳定的任务标识符", "Stable task identifier", "Identificador estável da tarefa"
    ),
    "original_task": _field(
        "用户原始任务描述，保持原文",
        "Original user task; preserve it verbatim",
        "Tarefa original do usuário; preserve-a literalmente",
    ),
    "session_id": _field(
        "要继续的已有子会话标识符",
        "Existing child-session identifier to continue",
        "Identificador da sessão filha existente a continuar",
    ),
    "url": _field("目标 URL", "Target URL", "URL de destino"),
    "timeout_seconds": _field(
        "超时秒数", "Timeout in seconds", "Tempo limite em segundos"
    ),
    "text": _field(
        "要匹配或输入的页面文本，保持原样",
        "Page text to match or enter; preserve it verbatim",
        "Texto da página a localizar ou inserir; preserve-o literalmente",
    ),
    "direction": _field("滚动方向", "Scroll direction", "Direção da rolagem"),
    "pages": _field(
        "滚动页数", "Number of pages to scroll", "Número de páginas a rolar"
    ),
    "keys": _field(
        "要发送的按键序列", "Key sequence to send", "Sequência de teclas a enviar"
    ),
    "selector": _field("DOM/CSS 选择器", "DOM/CSS selector", "Seletor DOM/CSS"),
    "submit": _field(
        "操作后是否提交",
        "Whether to submit after the action",
        "Se deve enviar após a ação",
    ),
    "seconds": _field("等待秒数", "Seconds to wait", "Segundos de espera"),
    "tab_id": _field(
        "浏览器标签页标识符",
        "Browser tab identifier",
        "Identificador da guia do navegador",
    ),
    "tab_id_suffix": _field(
        "标签页标识符后缀", "Tab identifier suffix", "Sufixo do identificador da guia"
    ),
    "index": _field("从零开始的索引", "Zero-based index", "Índice baseado em zero"),
    "file_name": _field("上传文件名", "Upload file name", "Nome do arquivo enviado"),
    "file_data_base64": _field(
        "Base64 编码的文件内容",
        "Base64-encoded file content",
        "Conteúdo do arquivo codificado em base64",
    ),
    "file_mime_type": _field(
        "文件 MIME 类型", "File MIME type", "Tipo MIME do arquivo"
    ),
    "format": _field("输出格式", "Output format", "Formato de saída"),
    "quality": _field("图片质量", "Image quality", "Qualidade da imagem"),
    "action": _field(
        "要执行的浏览器动作",
        "Browser action to perform",
        "Ação do navegador a executar",
    ),
    "dom_id": _field(
        "DOM 元素标识符", "DOM element identifier", "Identificador do elemento DOM"
    ),
    "max_chars": _field(
        "最多返回的字符数",
        "Maximum characters to return",
        "Máximo de caracteres a retornar",
    ),
    "code": _field(
        "要执行的代码，保持原样",
        "Code to execute; preserve it verbatim",
        "Código a executar; preserve-o literalmente",
    ),
    "message": _field(
        "面向用户的结果摘要",
        "User-facing result summary",
        "Resumo do resultado exibido ao usuário",
    ),
    "validation": _field(
        "内容校验结果",
        "Content validation result",
        "Resultado da validação do conteúdo",
    ),
    "file_extension": _field("文件扩展名", "File extension", "Extensão do arquivo"),
    "enabled": _field("是否启用", "Whether enabled", "Se está ativado"),
    "skipped": _field("是否跳过", "Whether skipped", "Se foi ignorado"),
    "passed": _field(
        "校验是否通过",
        "Whether validation passed",
        "Se a validação foi aprovada",
    ),
    "validator": _field("校验器名称", "Validator name", "Nome do validador"),
    "warnings": _field("校验警告列表", "Validation warnings", "Avisos de validação"),
    "errors": _field("校验错误列表", "Validation errors", "Erros de validação"),
    "success": _field(
        "操作是否成功",
        "Whether the operation succeeded",
        "Se a operação foi bem-sucedida",
    ),
    "output_file": _field(
        "后台输出文件路径",
        "Background output file path",
        "Caminho do arquivo de saída em segundo plano",
    ),
    "stdout": _field(
        "命令标准输出，保持原样",
        "Command standard output; preserve it verbatim",
        "Saída padrão do comando; preserve-a literalmente",
    ),
    "exit_code": _field(
        "命令退出码", "Command exit code", "Código de saída do comando"
    ),
}


# Context-sensitive Portuguese wording for natural-language values whose field
# names are shared with machine-oriented parameters in other tools.
PARAM_PT_OVERRIDES: Dict[str, Dict[tuple[str, ...], str]] = {
    "file_write": {
        (
            "content",
        ): "Conteúdo textual a gravar; mantenha o idioma exigido pelo artefato, sem tradução automática.",
    },
    "todo_write": {
        (
            "tasks",
            "[]",
            "content",
        ): "Descrição da tarefa exibida ao usuário; use o idioma de resposta.",
        (
            "tasks",
            "[]",
            "conclusion",
        ): "Conclusão da tarefa exibida ao usuário; use o idioma de resposta.",
    },
    "questionnaire": {
        ("title",): "Título exibido ao usuário; use o idioma de resposta.",
        (
            "questions",
            "[]",
            "title",
        ): "Texto da pergunta exibido ao usuário; use o idioma de resposta.",
        (
            "questions",
            "[]",
            "options",
            "[]",
            "label",
        ): "Rótulo da opção exibido ao usuário; use o idioma de resposta.",
        (
            "questions",
            "[]",
            "options",
            "[]",
            "value",
        ): "Valor estável da opção; não o traduza automaticamente.",
        (
            "questions",
            "[]",
            "placeholder",
        ): "Dica de entrada exibida ao usuário; use o idioma de resposta.",
    },
    "turn_status": {
        (
            "note",
        ): "Observação de progresso exibida ao usuário; use o idioma de resposta.",
    },
    "sys_spawn_agent": {
        ("name",): "Nome legível do subagente; use o idioma da conversa.",
        ("description",): "Descrição da função do subagente; use o idioma de resposta.",
        ("system_prompt",): "Prompt de sistema do subagente; use o idioma de resposta.",
    },
    "sys_delegate_task": {
        (
            "tasks",
            "[]",
            "content",
        ): "Descrição detalhada da subtarefa; use o idioma de resposta.",
        (
            "tasks",
            "[]",
            "original_task",
        ): "Descrição original fornecida pelo usuário; preserve-a literalmente.",
        (
            "tasks",
            "[]",
            "session_id",
        ): "ID opcional de uma sessão filha existente; deixe vazio para uma nova tarefa.",
    },
    "sys_team_delegate_task": {
        (
            "tasks",
            "[]",
            "content",
        ): "Descrição detalhada da subtarefa; use o idioma de resposta.",
        (
            "tasks",
            "[]",
            "original_task",
        ): "Descrição original fornecida pelo usuário; preserve-a literalmente.",
        (
            "tasks",
            "[]",
            "session_id",
        ): "ID opcional de uma sessão filha existente; deixe vazio para uma nova tarefa.",
    },
    "browser_dom_action": {
        (
            "value",
        ): "Valor textual a inserir na página; preserve o texto exigido pela página.",
    },
}


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _fallback_i18n(field_name: Optional[str], base: str) -> Dict[str, str]:
    if field_name and field_name in FIELD_I18N:
        return dict(FIELD_I18N[field_name])
    label = field_name or "value"
    result = _field(
        f"{label} 字段",
        base or f"The {label} field",
        f"Campo {label}",
    )
    if base:
        result["zh" if _contains_cjk(base) else "en"] = base
    return result


def _enrich_node(node: Any, field_name: Optional[str] = None) -> None:
    if not isinstance(node, MutableMapping):
        return

    base = str(node.get("description") or "")
    existing = node.get("description_i18n")
    if base or field_name in FIELD_I18N:
        completed = _fallback_i18n(field_name, base)
        if isinstance(existing, dict):
            completed.update({k: str(v) for k, v in existing.items() if v})
        node["description_i18n"] = completed
        if not base:
            node["description"] = completed["en"]

    properties = node.get("properties")
    if isinstance(properties, MutableMapping):
        for child_name, child in properties.items():
            _enrich_node(child, str(child_name))
    items = node.get("items")
    if isinstance(items, MutableMapping):
        _enrich_node(items, field_name)
    for keyword in ("anyOf", "oneOf", "allOf", "prefixItems"):
        alternatives = node.get(keyword)
        if isinstance(alternatives, list):
            for alternative in alternatives:
                _enrich_node(alternative, field_name)
    for keyword in (
        "additionalProperties",
        "contains",
        "not",
        "if",
        "then",
        "else",
    ):
        child = node.get(keyword)
        if isinstance(child, MutableMapping):
            _enrich_node(child, field_name)


def enrich_builtin_tool_i18n(
    tool_name: str,
    description_i18n: Dict[str, str],
    parameters: Dict[str, Dict[str, Any]],
    return_data: Optional[Dict[str, Any]],
) -> None:
    """Fill missing zh/en/pt metadata for one known built-in tool in place."""
    pt_description = TOOL_PT_DESCRIPTIONS.get(tool_name)
    if not pt_description:
        return
    description_i18n.setdefault("pt", pt_description)
    for name, schema in parameters.items():
        _enrich_node(schema, name)
    for path, portuguese_text in PARAM_PT_OVERRIDES.get(tool_name, {}).items():
        node: Any = parameters.get(path[0])
        for part in path[1:]:
            if not isinstance(node, MutableMapping):
                node = None
                break
            node = (
                node.get("items")
                if part == "[]"
                else (node.get("properties") or {}).get(part)
            )
        if isinstance(node, MutableMapping):
            node.setdefault("description_i18n", {})["pt"] = portuguese_text
    if isinstance(return_data, dict):
        _enrich_node(return_data)


__all__ = [
    "FIELD_I18N",
    "TOOL_PT_DESCRIPTIONS",
    "enrich_builtin_tool_i18n",
]
