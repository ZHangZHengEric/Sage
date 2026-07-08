from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_LANGUAGE = "zh"

MESSAGES: dict[str, dict[str, str]] = {
    "zh": {
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
        "runtime.context_over_limit": (
            "当前上下文压缩后仍超过模型输入限制：{current_tokens} > {limit}。"
            "请缩小当前请求范围，或允许我先整理/归档更早的执行过程后继续。"
        ),
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
    },
    "en": {
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
        "runtime.context_over_limit": (
            "The compressed context still exceeds the model input limit: "
            "{current_tokens} > {limit}. Narrow the current request, or let me "
            "summarize/archive earlier execution history before continuing."
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
    },
    "pt": {
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
        "runtime.context_over_limit": (
            "O contexto comprimido ainda excede o limite de entrada do modelo: "
            "{current_tokens} > {limit}. Reduza o escopo da solicitacao atual ou permita "
            "que eu resuma/arquive o historico de execucao anterior antes de continuar."
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
