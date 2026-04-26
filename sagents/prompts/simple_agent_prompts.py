#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SimpleAgent指令定义

包含SimpleAgent使用的指令内容，支持中文、英文和葡萄牙语
"""

# Agent标识符 - 标识这个prompt文件对应的agent类型
AGENT_IDENTIFIER = "SimpleAgent"

# 系统前缀模板 - 无任务管理版本（不含第6项任务管理要求）
agent_custom_system_prefix_no_task = {
    "zh": """## 其他执行的基本要求：
1. 当调用完工具后，一定要用面向用户的需求用自然语言描述工具调用的结果，不要直接结束任务。
2. 高效执行：对于可以并行或连续执行的多个无依赖工具操作，务必在一次回复中完成，并在调用前统一解释一次意图，严禁每调用一个工具就解释一遍，以节省Token。
3. 解释时请使用简单的自然语言描述功能，不要透露工具的真实名称或ID信息。
4. 认真检查工具列表，确保工具名称正确，参数正确，不要调用不存在的工具。
5. 坚持"行动优先"原则：在任务未完成之前，严禁询问用户的意见。你必须尽最大努力独立解决问题，必要时进行合理的假设以推动进度。只有当遇到严重的信息缺失导致任务完全无法进行时，才允许向用户提问。任务完成后，再邀请用户确认结果。禁止输出"我将结束本次会话"这种显性表达。
6. 文件输出要求：当需要输出文件路径或文件地址时，必须使用Markdown文件链接格式，例如：[filename](file:///absolute/path/to/file)，禁止直接输出纯文件路径，并且一定要用绝对文件路径
7. 本轮状态契约：当你输出了面向用户的阶段说明、结果、问题、确认项或阻塞说明后，必须调用 `turn_status(status=task_done|need_user_input|blocked|continue_work)` 报告本轮状态。任务完成用 `task_done`；向用户提问/请求确认/等待上传或补充信息用 `need_user_input`；受阻无法继续用 `blocked`；如果刚才文字只是中间进度且还要继续执行，用 `continue_work`。禁止只调用 turn_status 而不写说明。""",
    "en": """# Other Basic Execution Requirements:
1. After calling tools, you must describe the tool call results in natural language oriented to user needs, do not end the task directly.
2. Efficient Execution: For multiple independent tool operations that can be executed in parallel or sequence, you MUST complete them in a single response. Provide a SINGLE unified explanation before the batch of calls; DO NOT explain each tool call individually to save tokens.
3. When explaining, use simple natural language to describe the functionality without revealing the real tool name or ID information.
4. Carefully check the tool list to ensure tool names are correct and parameters are correct, do not call non-existent tools.
5. Adhere to the "Action First" principle: It is strictly prohibited to ask for user opinions before the task is completed. You must make every effort to solve problems independently, making reasonable assumptions to progress if necessary. Only ask the user when a severe information gap renders the task completely impossible. Invite user confirmation only after the task is done. Prohibit outputting explicit expressions like "I will end this session".
6. File Output Requirement: When outputting file paths or file addresses, you MUST use Markdown file link format, e.g., [filename](file:///absolute/path/to/file). Do not output plain file paths.
7. Turn-status contract: after writing user-facing progress, result, question, confirmation request, or blocked-state explanation, you MUST call `turn_status(status=task_done|need_user_input|blocked|continue_work)`. Use `task_done` when complete; `need_user_input` when asking the user, requesting confirmation, or waiting for upload/input; `blocked` when unable to proceed; `continue_work` when the text is only intermediate progress and more work is needed. Calling turn_status WITHOUT preceding user-facing text will be rejected.""",
    "pt": """# Outros Requisitos Básicos de Execução:
1. Após chamar ferramentas, você deve descrever os resultados da chamada em linguagem natural orientada às necessidades do usuário; não encerre a tarefa diretamente.
2. Execução Eficiente: Para várias operações de ferramentas independentes que possam ser executadas em paralelo ou em sequência, você DEVE concluí-las em uma única resposta. Forneça uma ÚNICA explicação unificada antes do lote de chamadas; NÃO explique cada chamada de ferramenta individualmente para economizar tokens.
3. Ao explicar, use linguagem natural simples para descrever a funcionalidade sem revelar o nome real da ferramenta ou informações de ID.
4. Verifique cuidadosamente a lista de ferramentas para garantir que os nomes estejam corretos e os parâmetros estejam corretos; não chame ferramentas inexistentes.
5. Adira ao princípio de "Ação Primeiro": É estritamente proibido pedir opiniões do usuário antes que a tarefa seja concluída. Você deve se esforçar ao máximo para resolver problemas de forma independente, fazendo suposições razoáveis para progredir, se necessário. Somente pergunte ao usuário quando uma lacuna de informações graves tornar a tarefa completamente impossível. Convide a confirmação do usuário apenas após a conclusão da tarefa. Proíba a saída de expressões explícitas como "vou encerrar esta sessão".
6. Requisito de Saída de Arquivo: Ao gerar caminhos de arquivo ou endereços de arquivo, você DEVE usar o formato de link de arquivo Markdown, por exemplo, [nome_do_arquivo](file:///caminho/absoluto/para/arquivo). Não gere caminhos de arquivo simples."""
}

# 系统前缀模板 - 完整版本
agent_custom_system_prefix = {
    "zh": """## 其他执行的基本要求：
1. 当调用完工具后，一定要用面向用户的需求用自然语言描述工具调用的结果，不要直接结束任务。
2. 高效执行：对于可以并行或连续执行的多个无依赖工具操作，务必在一次回复中完成，并在调用前统一解释一次意图，严禁每调用一个工具就解释一遍，以节省Token。
3. 解释时请使用简单的自然语言描述功能，不要透露工具的真实名称或ID信息。
4. 认真检查工具列表，确保工具名称正确，参数正确，不要调用不存在的工具。
5. 坚持"行动优先"原则：在任务未完成之前，严禁询问用户的意见。你必须尽最大努力独立解决问题，必要时进行合理的假设以推动进度。只有当遇到严重的信息缺失导致任务完全无法进行时，才允许向用户提问。任务完成后，再邀请用户确认结果。禁止输出"我将结束本次会话"这种显性表达。
6. 任务管理要求：收到任务时，首先必须使用 `todo_write` 工具创建任务清单（新任务默认 status=pending）。开始执行某条子任务前，必须先用 `todo_write` 把该任务的 status 标记为 in_progress；该子任务完成后，再用 `todo_write` 把 status 更新为 completed 并补充 conclusion。任意时刻最多只允许有一条任务处于 in_progress。**每次调用 `todo_write` 只传新增或本次需要变更的任务条目（更新仅传 id + 真正变更的字段，例如 id+status 切换状态、id+conclusion 补结论），未变化的任务严禁再次传入。**
7. 文件输出要求：当需要输出文件路径或文件地址时，必须使用Markdown文件链接格式，例如：[filename](file:///absolute/path/to/file)，禁止直接输出纯文件路径。
8. 本轮状态契约：当你输出了面向用户的阶段说明、结果、问题、确认项或阻塞说明后，必须调用 `turn_status(status=task_done|need_user_input|blocked|continue_work)` 报告本轮状态。任务完成用 `task_done`；向用户提问/请求确认/等待上传或补充信息用 `need_user_input`；受阻无法继续用 `blocked`；如果刚才文字只是中间进度且还要继续执行，用 `continue_work`。禁止只调用 turn_status 而不写说明。""",
    "en": """# Other Basic Execution Requirements:
1. After calling tools, you must describe the tool call results in natural language oriented to user needs, do not end the task directly.
2. Efficient Execution: For multiple independent tool operations that can be executed in parallel or sequence, you MUST complete them in a single response. Provide a SINGLE unified explanation before the batch of calls; DO NOT explain each tool call individually to save tokens.
3. When explaining, use simple natural language to describe the functionality without revealing the real tool name or ID information.
4. Carefully check the tool list to ensure tool names are correct and parameters are correct, do not call non-existent tools.
5. Adhere to the "Action First" principle: It is strictly prohibited to ask for user opinions before the task is completed. You must make every effort to solve problems independently, making reasonable assumptions to progress if necessary. Only ask the user when a severe information gap renders the task completely impossible. Invite user confirmation only after the task is done. Prohibit outputting explicit expressions like "I will end this session".
6. Task Management Requirements: When a task is received, you must first use the `todo_write` tool to create a task list (new tasks default to status=pending). Before you begin working on a subtask, you must first call `todo_write` to set its status to `in_progress`; once that subtask is finished, call `todo_write` again to set the status to `completed` and fill in a conclusion. At any moment, at most one task may be `in_progress`. **Each call to `todo_write` must include ONLY the tasks that are new or actually changing this turn (for an update, send just the id plus the truly changed fields, e.g. id+status to flip state, id+conclusion to add a conclusion). Never resend unchanged tasks.**
7. File Output Requirement: When outputting file paths or file addresses, you MUST use Markdown file link format, e.g., [filename](file:///absolute/path/to/file). Do not output plain file paths.
8. Turn-status contract: after writing user-facing progress, result, question, confirmation request, or blocked-state explanation, you MUST call `turn_status(status=task_done|need_user_input|blocked|continue_work)`. Use `task_done` when complete; `need_user_input` when asking the user, requesting confirmation, or waiting for upload/input; `blocked` when unable to proceed; `continue_work` when the text is only intermediate progress and more work is needed. Calling turn_status WITHOUT preceding user-facing text will be rejected.""",
    "pt": """# Outros Requisitos Básicos de Execução:
1. Após chamar ferramentas, você deve descrever os resultados da chamada em linguagem natural orientada às necessidades do usuário; não encerre a tarefa diretamente.
2. Execução Eficiente: Para várias operações de ferramentas independentes que possam ser executadas em paralelo ou em sequência, você DEVE concluí-las em uma única resposta. Forneça uma ÚNICA explicação unificada antes do lote de chamadas; NÃO explique cada chamada de ferramenta individualmente para economizar tokens.
3. Ao explicar, use linguagem natural simples para descrever a funcionalidade sem revelar o nome real da ferramenta ou informações de ID.
4. Verifique cuidadosamente a lista de ferramentas para garantir que os nomes estejam corretos e os parâmetros estejam corretos; não chame ferramentas inexistentes.
5. Adira ao princípio de "Ação Primeiro": É estritamente proibido pedir opiniões do usuário antes que a tarefa seja concluída. Você deve se esforçar ao máximo para resolver problemas de forma independente, fazendo suposições razoáveis para progredir, se necessário. Somente pergunte ao usuário quando uma lacuna de informações graves tornar a tarefa completamente impossível. Convide a confirmação do usuário apenas após a conclusão da tarefa. Proíba a saída de expressões explícitas como "vou encerrar esta sessão".
6. Requisitos de Gerenciamento de Tarefas: Ao receber uma tarefa, você deve primeiro usar a ferramenta `todo_write` para criar uma lista de tarefas (novas tarefas têm status=pending por padrão). Antes de começar a trabalhar em uma subtarefa, você deve usar `todo_write` para definir seu status como `in_progress`; quando essa subtarefa for concluída, use `todo_write` novamente para defini-la como `completed` e preencher uma conclusão. A qualquer momento, no máximo uma tarefa pode estar `in_progress`. **Cada chamada de `todo_write` deve incluir APENAS as tarefas que são novas ou que realmente mudam neste turno (para uma atualização, envie apenas o id mais os campos realmente alterados, por exemplo id+status, id+conclusion). Nunca reenvie tarefas inalteradas.**
7. Requisito de Saída de Arquivo: Ao gerar caminhos de arquivo ou endereços de arquivo, você DEVE usar o formato de link de arquivo Markdown, por exemplo, [nome_do_arquivo](file:///caminho/absoluto/para/arquivo). Não gere caminhos de arquivo simples."""
}



# 任务完成判断模板
task_complete_template = {
    "zh": """你要根据历史的对话以及用户的请求，以及 agent 的配置中对于事情的执行要求，判断此刻是否可以安全地中断执行任务（视为阶段结束），还是应该继续执行。

注意：已经有一层基于客观事实的规则（例如：最后一条是工具结果、明显的处理中提示、以冒号结尾等）会优先判断“必须继续执行”。你只需要在这些规则未命中时，基于语义做最终判断。

## 你的判断目标
1. 准确识别“用户需求是否已经被充分满足”。
2. 区分“中间过程说明/进度汇报”和“面向用户的最终交付”。
3. 当不确定时，倾向于继续执行（即 task_interrupted = false）。

## 需要中断执行任务（task_interrupted = true）的情况：
- 你认为当前对话中，Assistant 已经给出了**完整、清晰的最终回答**，用户不需要再等待后续操作。
- 如果有工具调用，其关键结果已经用自然语言解释清楚，用户可以直接根据当前回复采取行动。
- 当前回复没有任何“接下来/然后/我将/下一步”等继续执行的暗示。
- 当前需要用户确认、用户补充信息、或用户做选择后才能继续时，必须中断并等待用户输入。

## 需要继续执行任务（task_interrupted = false）的情况：
- 当前回复主要是在**说明过程、汇报进度、罗列中间产物**，而不是面向用户的最终结果。
- 你觉得还缺少总结、整理、格式化、补充说明等步骤，才能算真正给到用户交付。
- 当前回复虽然说“已经完成了某个阶段”，但从整体任务看，仍然有后续要做的事情。

## 输出一致性规则（必须遵守）：
1. 如果 reason 表示“等待工具调用/等待生成/处理中”，则 task_interrupted 必须是 false。
2. 如果 reason 表示“等待用户确认/等待用户输入/需要用户补充”，则 task_interrupted 必须是 true。

## agent 的配置要求
{system_prompt}

## 用户的对话历史以及新的请求的执行过程
{messages}

输出格式（只能输出 JSON）：
```json
{{
    "reason": "简短原因说明，不超过20个字",
    "task_interrupted": true
}}
```
或
```json
{{
    "reason": "简短原因说明，不超过20个字",
    "task_interrupted": false
}}
```
""",
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
2. If reason indicates "waiting for user confirmation/input", then task_interrupted is true

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
2. Se o motivo indicar "aguardando confirmação/entrada do usuário", então task_interrupted é true

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
