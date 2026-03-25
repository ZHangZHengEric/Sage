#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查询建议Agent指令定义

包含查询建议agent使用的指令内容，支持中文、英文和葡萄牙语
"""

# Agent标识符 - 标识这个prompt文件对应的agent类型
AGENT_IDENTIFIER = "QuerySuggestAgent"

# 建议生成模板
suggest_template = {
    "zh": """# 建议生成指南
你的任务是根据上述的对话，生成接下来用户可能会问的问题，或者可能帮助用户解决相关更加深入的事情。

## 用户对话
{task_description}

## 要求
1. 建议的问题或者方向要与用户对话相关。
2. 建议的问题或者方向要具有一定的深度，能够帮助用户解决问题。
3. 建议的问题或者方向要具有一定的广度，能够帮助用户探索不同的角度。
4. 只生成3条建议。
5. 每条建议要简洁，不超过20个字符。
6. 建议是站在用户的角度。

## 输出格式
```
<suggest_item>
用户可能会问的问题1或者可以深入探索的方向1
</suggest_item>
<suggest_item>
用户可能会问的问题2或者可以深入探索的方向2
</suggest_item>
<suggest_item>
用户可能会问的问题3或者可以深入探索的方向3
</suggest_item>
```""",
    "en": """# Suggestion Generation Guide
Your task is to generate questions that users might ask next based on the above dialogue, or things that might help users solve related deeper issues.

## User Dialogue
{task_description}

## Requirements
1. Suggested questions or directions should be related to user dialogue.
2. Suggested questions or directions should have a certain depth and be able to help users solve problems.
3. Suggested questions or directions should have a certain breadth and be able to help users explore different angles.
4. Only generate 3 suggestions.
5. Each suggestion should be concise, no more than 20 characters.
6. Suggestions are from the user's perspective.

## Output Format
```
<suggest_item>
Question 1 that users might ask or direction 1 for deeper exploration
</suggest_item>
<suggest_item>
Question 2 that users might ask or direction 2 for deeper exploration
</suggest_item>
<suggest_item>
Question 3 that users might ask or direction 3 for deeper exploration
</suggest_item>
```""",
    "pt": """# Guia de Geração de Sugestões
Sua tarefa é gerar perguntas que os usuários podem fazer em seguida com base no diálogo acima, ou coisas que podem ajudar os usuários a resolver questões relacionadas mais profundas.

## Diálogo do Usuário
{task_description}

## Requisitos
1. As perguntas ou direções sugeridas devem estar relacionadas ao diálogo do usuário.
2. As perguntas ou direções sugeridas devem ter uma certa profundidade e ser capazes de ajudar os usuários a resolver problemas.
3. As perguntas ou direções sugeridas devem ter uma certa amplitude e ser capazes de ajudar os usuários a explorar diferentes ângulos.
4. Gere apenas 3 sugestões.
5. Cada sugestão deve ser concisa, não mais de 20 caracteres.
6. As sugestões são da perspectiva do usuário.

## Formato de Saída
```
<suggest_item>
Pergunta 1 que os usuários podem fazer ou direção 1 para exploração mais profunda
</suggest_item>
<suggest_item>
Pergunta 2 que os usuários podem fazer ou direção 2 para exploração mais profunda
</suggest_item>
<suggest_item>
Pergunta 3 que os usuários podem fazer ou direção 3 para exploração mais profunda
</suggest_item>
```"""
}