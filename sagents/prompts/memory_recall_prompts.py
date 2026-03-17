"""
Memory Recall Agent Prompts

专门用于记忆召回 Agent 的提示模板。
"""
AGENT_IDENTIFIER = "MemoryRecallAgent"

# 记忆召回主模板
memory_recall_template = {
    "zh": """
基于用户对话历史，生成一个精准的搜索查询，用于召回工作空间中最相关的文件记忆。

## 用户对话历史
{messages}

## 任务说明
1. 分析用户的当前请求和对话上下文
2. 提取关键概念、技术术语、文件名、函数名等
3. 生成一个简洁但精准的搜索查询（建议 3-10 个关键词）
4. 搜索查询应该能够匹配到最相关的代码文件或文档

## 注意事项
1. 优先使用技术术语和关键词，而非完整句子
2. 如果用户提到了具体文件名或函数名，请包含在查询中
3. 如果涉及特定编程语言或框架，请包含相关关键词
4. 查询应该足够通用以召回相关内容，但足够具体以过滤无关内容

## 输出格式
请返回一个搜索查询字符串，可以是以下格式之一：

格式1 - 纯文本（推荐）：
```
关键词1 关键词2 关键词3
```

格式2 - JSON：
```json
{{"query": "关键词1 关键词2 关键词3"}}
```

不要包含任何解释或额外文本，只返回搜索查询。
""",

    "en": """
Based on the user conversation history, generate a precise search query to recall the most relevant file memories from the workspace.

## User Conversation History
{messages}

## Task Instructions
1. Analyze the user's current request and conversation context
2. Extract key concepts, technical terms, filenames, function names, etc.
3. Generate a concise but precise search query (recommended 3-10 keywords)
4. The search query should match the most relevant code files or documents

## Notes
1. Prioritize technical terms and keywords over complete sentences
2. If the user mentions specific filenames or function names, include them in the query
3. If specific programming languages or frameworks are involved, include relevant keywords
4. The query should be general enough to recall relevant content but specific enough to filter out irrelevant content

## Output Format
Please return a search query string in one of the following formats:

Format 1 - Plain text (recommended):
```
keyword1 keyword2 keyword3
```

Format 2 - JSON:
```json
{{"query": "keyword1 keyword2 keyword3"}}
```

Do not include any explanations or additional text, only return the search query.
""",

    "pt": """
Com base no histórico de conversas do usuário, gere uma consulta de pesquisa precisa para recuperar as memórias de arquivo mais relevantes do espaço de trabalho.

## Histórico de Conversas do Usuário
{messages}

## Instruções da Tarefa
1. Analise a solicitação atual do usuário e o contexto da conversa
2. Extraia conceitos-chave, termos técnicos, nomes de arquivos, nomes de funções, etc.
3. Gere uma consulta de pesquisa concisa mas precisa (recomendado 3-10 palavras-chave)
4. A consulta de pesquisa deve corresponder aos arquivos de código ou documentos mais relevantes

## Notas
1. Priorize termos técnicos e palavras-chave em vez de frases completas
2. Se o usuário mencionar nomes de arquivos ou funções específicos, inclua-os na consulta
3. Se linguagens de programação ou frameworks específicos estiverem envolvidos, inclua palavras-chave relevantes
4. A consulta deve ser geral o suficiente para recuperar conteúdo relevante, mas específica o suficiente para filtrar conteúdo irrelevante

## Formato de Saída
Por favor, retorne uma string de consulta de pesquisa em um dos seguintes formatos:

Formato 1 - Texto simples (recomendado):
```
palavra-chave1 palavra-chave2 palavra-chave3
```

Formato 2 - JSON:
```json
{{"query": "palavra-chave1 palavra-chave2 palavra-chave3"}}
```

Não inclua nenhuma explicação ou texto adicional, retorne apenas a consulta de pesquisa.
"""
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

Por favor, mantenha-se sempre profissional, preciso e priorize a relevância dos resultados de recuperação."""
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

Essas memórias podem ser úteis para sua tarefa atual."""
}
