#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
会话上下文Agent指令定义

包含SessionContext使用的指令内容，支持中文、英文和葡萄牙语
"""

# Agent标识符 - 标识这个prompt文件对应的agent类型
AGENT_IDENTIFIER = "SessionContext"

# 历史消息序列化说明文本
history_messages_explanation = {
    "zh": (
        "以下是检索到的相关历史对话上下文，这些消息与当前查询相关，"
        "可以帮助你更好地理解对话背景和用户意图。请参考这些历史消息来提供更准确和连贯的回答。\n"
        "=== 相关历史对话上下文 ===\n"
    ),
    "en": (
        "The following are retrieved relevant historical conversation contexts. These messages are related to the current query "
        "and can help you better understand the conversation background and user intent. Please refer to these historical messages "
        "to provide more accurate and coherent responses.\n"
        "=== Relevant Historical Conversation Context ===\n"
    ),
    "pt": (
        "A seguir estão os contextos relevantes de conversa histórica recuperados. Essas mensagens estão relacionadas à consulta atual "
        "e podem ajudá-lo a entender melhor o contexto da conversa e a intenção do usuário. Por favor, consulte essas mensagens históricas "
        "para fornecer respostas mais precisas e coerentes.\n"
        "=== Contexto de Conversa Histórica Relevante ===\n"
    )
}

# 历史消息格式模板
history_message_format = {
    "zh": "[Memory {index}] ({time}): {content}",
    "en": "[Memory {index}] ({time}): {content}",
    "pt": "[Memória {index}] ({time}): {content}"
}

