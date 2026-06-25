"""
Memory Recall Agent Prompts

专门用于记忆召回 Agent 的提示模板。
"""

AGENT_IDENTIFIER = "MemoryRecallAgent"

# 记忆召回主模板
memory_recall_template = {
    "zh": """从下面对话文本中提取用于搜索工作区记忆的关键词查询。
优先保留项目名、文件名、路径尾部、函数名、产品名和核心需求。忽略图片、工具、运行时和无关客套。
只返回 JSON：{{"query":"3-10 个关键词"}}

对话文本：
{messages}
""",
    "en": """Extract a keyword query for searching workspace memory from the conversation text below.
Prefer project names, filenames, path tails, function names, product names, and the core request. Ignore images, tools, runtime details, and chatter.
Return JSON only: {{"query":"3-10 keywords"}}

Conversation text:
{messages}
""",
    "pt": """Extraia uma consulta de palavras-chave para pesquisar a memoria do workspace a partir do texto de conversa abaixo.
Priorize nomes de projeto, arquivos, finais de caminhos, funcoes, produtos e o pedido principal. Ignore imagens, ferramentas, runtime e conversa irrelevante.
Retorne apenas JSON: {{"query":"3-10 palavras-chave"}}

Texto da conversa:
{messages}
""",
}

# 记忆召回系统提示
memory_recall_system_prefix = {
    "zh": """你是 Sage AI 的记忆召回专家。你的职责是：
1. 深入理解用户的需求和对话上下文
2. 提取关键概念、技术术语和关键词
3. 生成精准的搜索查询以召回最相关的文件记忆
4. 帮助用户快速找到工作空间中的相关代码和文档

请始终保持专业、准确，并优先考虑召回结果的相关性。""",
    "en": """You are Sage AI's memory recall expert. Your responsibilities are:
1. Deeply understand user needs and conversation context
2. Extract key concepts, technical terms, and keywords
3. Generate precise search queries to recall the most relevant file memories
4. Help users quickly find relevant code and documents in their workspace

Please always remain professional, accurate, and prioritize the relevance of recall results.""",
    "pt": """Você é o especialista em recuperação de memória do Sage AI. Suas responsabilidades são:
1. Compreender profundamente as necessidades do usuário e o contexto da conversa
2. Extrair conceitos-chave, termos técnicos e palavras-chave
3. Gerar consultas de pesquisa precisas para recuperar as memórias de arquivo mais relevantes
4. Ajudar os usuários a encontrar rapidamente código e documentos relevantes em seu espaço de trabalho

Por favor, mantenha-se sempre profissional, preciso e priorize a relevância dos resultados de recuperação.""",
}

# 记忆召回结果解释模板
memory_recall_result_template = {
    "zh": """基于您的请求，我从工作空间中召回了 {count} 条相关记忆：

{memory_list}

这些记忆可能对您当前的任务有帮助。""",
    "en": """Based on your request, I have recalled {count} relevant memories from the workspace:

{memory_list}

These memories may be helpful for your current task.""",
    "pt": """Com base na sua solicitação, recuperei {count} memórias relevantes do espaço de trabalho:

{memory_list}

Essas memórias podem ser úteis para sua tarefa atual.""",
}
