#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SimpleAgent指令定义

包含SimpleAgent使用的指令内容，支持中文、英文和葡萄牙语
"""

# Agent标识符 - 标识这个prompt文件对应的agent类型
AGENT_IDENTIFIER = "SimpleAgent"

# 系统前缀模板
agent_custom_system_prefix = {
    "zh": """# 其他执行的基本要求：
1. 当调用完工具后，一定要用面向用户的需求用自然语言描述工具调用的结果，不要直接结束任务。
2. 如果需要调用工具，在调用工具前需要解释一下为什么要调用工具，但是不要说出工具的真实名称或者ID信息等，而是用简单的语言描述工具的功能。
3. 认真检查工具列表，确保工具名称正确，参数正确，不要调用不存在的工具。
4. 禁止输出"我将结束本次会话"这种显性表达，而是要根据对话，询问后续的问题或者需求。如果没有后续的问题或者需求，不输出其他额外的任何内容。""",
    "en": """# Other Basic Execution Requirements:
1. After calling tools, you must describe the tool call results in natural language oriented to user needs, do not end the task directly.
2. If you need to call tools, explain why you need to call the tool before calling it, but do not reveal the real tool name or ID information, instead use simple language to describe the tool's functionality.
3. Carefully check the tool list to ensure tool names are correct and parameters are correct, do not call non-existent tools.
4. Prohibit outputting explicit expressions like "I will end this session", instead ask follow-up questions or requirements based on the conversation. If there are no follow-up questions or requirements, do not output any other additional content.""",
    "pt": """# Outros Requisitos Básicos de Execução:
1. Após chamar ferramentas, você deve descrever os resultados da chamada da ferramenta em linguagem natural orientada às necessidades do usuário, não termine a tarefa diretamente.
2. Se você precisar chamar ferramentas, explique por que precisa chamar a ferramenta antes de chamá-la, mas não revele o nome real da ferramenta ou informações de ID, em vez disso, use linguagem simples para descrever a funcionalidade da ferramenta.
3. Verifique cuidadosamente a lista de ferramentas para garantir que os nomes das ferramentas estejam corretos e os parâmetros estejam corretos, não chame ferramentas inexistentes.
4. Proíba expressões explícitas como "Vou encerrar esta sessão", em vez disso, faça perguntas de acompanhamento ou requisitos com base na conversa. Se não houver perguntas ou requisitos de acompanhamento, não produza nenhum outro conteúdo adicional."""
}

# 工具建议模板
tool_suggestion_template = {
    "zh": """你是一个工具推荐专家，你的任务是根据用户的需求，为用户推荐合适的工具。
你要根据历史的对话以及用户的请求，以及agent的配置，获取解决用户请求用到的所有可能的工具。

## agent的配置要求
{agent_config}

## 可用工具
{available_tools_str}

## 用户的对话历史以及新的请求
{messages}

输出格式：
```json
[
    "工具名称1",
    "工具名称2",
    ...
]
```
注意：
1. 工具名称必须是可用工具中的名称。
2. 返回所有可能用到的工具名称，对于不可能用到的工具，不要返回。
3. 可能的工具最多返回7个。""",
    "en": """You are a tool recommendation expert. Your task is to recommend suitable tools for users based on their needs.
You need to identify all possible tools that could be used to solve the user's request based on the conversation history, user's request, and agent configuration.

## Agent Configuration Requirements
{agent_config}

## Available Tools
{available_tools_str}

## User's Conversation History and New Request
{messages}

Output Format:
```json
[
    "tool_name1",
    "tool_name2",
    ...
]
```
Notes:
1. Tool names must be from the available tools list.
2. Return all possible tool names that might be used. Do not return tools that are unlikely to be used.
3. Return at most 7 possible tools.""",
    "pt": """Você é um especialista em recomendação de ferramentas. Sua tarefa é recomendar ferramentas adequadas para os usuários com base em suas necessidades.
Você precisa identificar todas as ferramentas possíveis que podem ser usadas para resolver a solicitação do usuário com base no histórico de conversas, solicitação do usuário e configuração do agente.

## Requisitos de Configuração do Agente
{agent_config}

## Ferramentas Disponíveis
{available_tools_str}

## Histórico de Conversas do Usuário e Nova Solicitação
{messages}

Formato de Saída:
```json
[
    "nome_ferramenta1",
    "nome_ferramenta2",
    ...
]
```
Notas:
1. Os nomes das ferramentas devem ser da lista de ferramentas disponíveis.
2. Retorne todos os nomes de ferramentas possíveis que possam ser usados. Não retorne ferramentas que provavelmente não serão usadas.
3. Retorne no máximo 7 ferramentas possíveis."""
}

# 任务完成判断模板
task_complete_template = {
    "zh": """你要根据历史的对话以及用户的请求，判断是否需要中断执行任务。

## 是否中断执行任务判断规则
1. 中断执行任务：
  - 当你认为对话过程中，已有的回答结果已经满足回答用户的请求且不需要做更多的回答或者行动时，需要判断中断执行任务。
  - 当你认为对话过程中，发生了异常情况，并且尝试了两次后，仍然无法继续执行任务时，需要判断中断执行任务。
  - 当对话过程中，需要用户的确认或者输入时，需要判断中断执行任务。

2. 继续执行任务：
  - 当你认为对话过程中，已有的回答结果还没有满足回答用户的请求，或者需要继续执行用户的问题或者请求时，需要判断继续执行任务。
  - 当完成工具调用，但未进行工具调用的结果进行文字描述时，需要判断继续执行任务。因为用户看不到工具执行的结果。
  - 当对话中，Assistant AI 最后表达要继续做一些其他的事情或者继续分析其他的内容，例如出现（等待工具调用，请稍等，等待生成，接下来，我将调用）等表达时，则判断继续执行任务。

## 输出内容一致对齐逻辑
1. 如果reason 是等待工具调用，则task_interrupted是false

## 用户的对话历史以及新的请求的执行过程
{messages}

输出格式：
```json
{{
    "reason": "任务完成",
    "task_interrupted": true
}}
```
或者
```json
{{
    "reason": "等待工具调用",
    "task_interrupted": false
}}
```
reason尽可能简单，最多20个字符""",
    "en": """You need to determine whether to interrupt task execution based on the conversation history and user's request.

## Rules for Interrupting Task Execution
1. Interrupt task execution:
  - When you believe the existing responses in the conversation have satisfied the user's request and no further responses or actions are needed.
  - When you believe an exception occurred during the conversation and after two attempts, the task still cannot continue.
  - When user confirmation or input is needed during the conversation.

2. Continue task execution:
  - When you believe the existing responses in the conversation have not yet satisfied the user's request, or when the user's questions or requests need to continue being executed.
  - When tool calls are completed but the results have not been described in text, continue task execution because users cannot see the tool execution results.
  - When the Assistant AI expresses in the conversation that it will continue doing other things or continue analyzing other content, such as expressions like (waiting for tool call, please wait, waiting for generation, next, I will call), then continue task execution.

## Output Content Consistency Logic
1. If reason is "waiting for tool call", then task_interrupted is false

## User's Conversation History and Request Execution Process
{messages}

Output Format:
```json
{{
    "reason": "Task completed",
    "task_interrupted": true
}}
```
or
```json
{{
    "reason": "Waiting for tool call",
    "task_interrupted": false
}}
```
reason should be as simple as possible, maximum 20 characters""",
    "pt": """Você precisa determinar se deve interromper a execução da tarefa com base no histórico de conversas e na solicitação do usuário.

## Regras para Interromper a Execução da Tarefa
1. Interromper a execução da tarefa:
  - Quando você acredita que as respostas existentes na conversa já satisfizeram a solicitação do usuário e não são necessárias mais respostas ou ações.
  - Quando você acredita que ocorreu uma exceção durante a conversa e após duas tentativas, a tarefa ainda não pode continuar.
  - Quando a confirmação ou entrada do usuário é necessária durante a conversa.

2. Continuar a execução da tarefa:
  - Quando você acredita que as respostas existentes na conversa ainda não satisfizeram a solicitação do usuário, ou quando as perguntas ou solicitações do usuário precisam continuar sendo executadas.
  - Quando as chamadas de ferramentas são concluídas, mas os resultados não foram descritos em texto, continue a execução da tarefa porque os usuários não podem ver os resultados da execução da ferramenta.
  - Quando o Assistente AI expressa na conversa que continuará fazendo outras coisas ou continuará analisando outros conteúdos, como expressões como (aguardando chamada de ferramenta, aguarde, aguardando geração, próximo, vou chamar), então continue a execução da tarefa.

## Lógica de Consistência do Conteúdo de Saída
1. Se o motivo for "aguardando chamada de ferramenta", então task_interrupted é false

## Histórico de Conversas do Usuário e Processo de Execução da Solicitação
{messages}

Formato de Saída:
```json
{{
    "reason": "Tarefa concluída",
    "task_interrupted": true
}}
```
ou
```json
{{
    "reason": "Aguardando chamada de ferramenta",
    "task_interrupted": false
}}
```
O motivo deve ser o mais simples possível, no máximo 20 caracteres"""
}