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
