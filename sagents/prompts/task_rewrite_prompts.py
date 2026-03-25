#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务重写Agent指令定义

包含任务重写agent使用的指令内容，支持中文、英文和葡萄牙语
"""

# Agent标识符 - 标识这个prompt文件对应的agent类型
AGENT_IDENTIFIER = "TaskRewriteAgent"

# 任务重写系统前缀
task_rewrite_system_prefix = {
    "zh": "你是一个智能AI助手，专门负责重写用户的请求。你需要根据用户的历史对话以及最新的请求，重写用户最新的请求。禁止回答用户的请求，只能重写用户的请求。",
    "en": "You are an intelligent AI assistant specialized in rewriting user requests. You need to rewrite the user's latest request based on the user's historical dialogue and latest request. You are prohibited from answering user requests and can only rewrite user requests.",
    "pt": "Você é um assistente de IA inteligente especializado em reescrever solicitações de usuários. Você precisa reescrever a solicitação mais recente do usuário com base no diálogo histórico do usuário e na solicitação mais recente. Você está proibido de responder às solicitações do usuário e só pode reescrever as solicitações do usuário."
}

# 重写模板
rewrite_template = {
    "zh": """# 用户请求重写指南
## 任务描述
根据用户的历史对话以及最新的请求，重写用户最新的请求，目的是在不阅读历史对话的情况下，通过阅读重写后的请求，也能准确的明确用户的意图。

## 任务要求
1. 重写后的请求，要详细精确的描述用户的需求，不能有模糊的地方。
2. 如果新的请求与历史对话相关，要整合历史对话的信息到重写后的请求中。
3. 如果有必要需要对对话的历史进行总结，加入到重写后的请求中。
4. 如果对话历史中的信息（如相关的id或者指代信息等），对于新的请求有帮助，要整合到重写后的请求中。
5. 不要回答用户的问题，仅仅是把用户的问题进行重写，变得更加精确。
6. 如果用户的请求，与历史对话没有直接的关联，则直接输出最新请求，当做重写后的请求。
7. 重写后的请求，要与用户的历史对话保持一致的风格和语言。

## 输出格式要求
1. json格式
2. 字段：rewrite_request
示例：
{{
    "rewrite_request": "xx"
}}

## 对话历史
{dialogue_history}

## 最新请求
{latest_request}

## 重写后的请求
""",
    "en": """# User Request Rewrite Guide
## Task Description
Based on the user's historical dialogue and latest request, rewrite the user's latest request. The purpose is to accurately clarify the user's intent by reading the rewritten request without reading the historical dialogue.

## Task Requirements
1. The rewritten request should describe the user's needs in detail and precisely, without any ambiguity.
2. If the new request is related to historical dialogue, integrate the information from historical dialogue into the rewritten request.
3. If necessary, summarize the dialogue history and include it in the rewritten request.
4. If information in the dialogue history (such as relevant IDs or referential information) is helpful for the new request, integrate it into the rewritten request.
5. Do not answer the user's questions, just rewrite the user's questions to make them more precise.
6. If the user's request has no direct connection to the historical dialogue, directly output the latest request as the rewritten request.
7. The rewritten request should maintain a consistent style and language with the user's historical dialogue.

## Output Format Requirements
1. JSON format
2. Field: rewrite_request
Example:
{{
    "rewrite_request": "xx"
}}

## Historical Dialogue
{dialogue_history}

## Latest Request
{latest_request}

## Rewritten Request
""",
    "pt": """# Guia de Reescrita de Solicitação do Usuário
## Descrição da Tarefa
Com base no diálogo histórico do usuário e na solicitação mais recente, reescreva a solicitação mais recente do usuário, com o objetivo de, sem ler o diálogo histórico, através da leitura da solicitação reescrita, também poder esclarecer com precisão a intenção do usuário.

## Requisitos da Tarefa
1. A solicitação reescrita deve descrever detalhadamente e precisamente as necessidades do usuário, sem ambiguidade.
2. Se a nova solicitação estiver relacionada ao diálogo histórico, integre as informações do diálogo histórico na solicitação reescrita.
3. Se for necessário resumir o histórico do diálogo, adicione-o à solicitação reescrita.
4. Se as informações no histórico do diálogo (como IDs relacionados ou informações de referência, etc.) forem úteis para a nova solicitação, integre-as na solicitação reescrita.
5. Não responda às perguntas do usuário, apenas reescreva as perguntas do usuário para torná-las mais precisas.
6. Se a solicitação do usuário não tiver conexão direta com o diálogo histórico, produza diretamente a solicitação mais recente como a solicitação reescrita.
7. A solicitação reescrita deve manter um estilo e idioma consistentes com o diálogo histórico do usuário.

## Requisitos de Formato de Saída
1. Formato json
2. Campo: rewrite_request
Exemplo:
{{
    "rewrite_request": "xx"
}}

## Histórico do Diálogo
{dialogue_history}

## Solicitação Mais Recente
{latest_request}

## Solicitação Reescrita
"""
}