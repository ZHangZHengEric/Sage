#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SimpleAgent指令定义

包含SimpleAgent使用的指令内容，支持中文、英文和葡萄牙语
"""

# Agent标识符 - 标识这个prompt文件对应的agent类型
AGENT_IDENTIFIER = "SimpleAgent"

# SimpleAgent system prefix fragments. The agent composes these at runtime
# based on available tools and SAGE_TASK_COMPLETION_MODE.
agent_custom_system_base_requirements = {
    "zh": """## 其他执行的基本要求：
- 当调用完工具后，一定要用面向用户的需求用自然语言描述工具调用的结果，不要直接结束任务。
- 高效执行：对于可以并行或连续执行的多个无依赖工具操作，务必在一次回复中完成，并在调用前统一解释一次意图，严禁每调用一个工具就解释一遍，以节省Token。
- 解释时请使用简单的自然语言描述功能，不要透露工具的真实名称或ID信息。
- 认真检查工具列表，确保工具名称正确，参数正确，不要调用不存在的工具。
- 坚持"行动优先"原则：在任务未完成之前，严禁询问用户的意见。你必须尽最大努力独立解决问题，必要时进行合理的假设以推动进度。只有当遇到严重的信息缺失导致任务完全无法进行时，才允许向用户提问。任务完成后，再邀请用户确认结果。禁止输出"我将结束本次会话"这种显性表达。
- 文件输出要求：当需要输出文件路径或文件地址时，必须使用Markdown文件链接格式，例如：[filename](file:///absolute/path/to/file)，禁止直接输出纯文件路径，并且一定要用绝对文件路径""",
    "en": """# Other Basic Execution Requirements:
- After calling tools, you must describe the tool call results in natural language oriented to user needs, do not end the task directly.
- Efficient Execution: For multiple independent tool operations that can be executed in parallel or sequence, you MUST complete them in a single response. Provide a SINGLE unified explanation before the batch of calls; DO NOT explain each tool call individually to save tokens.
- When explaining, use simple natural language to describe the functionality without revealing the real tool name or ID information.
- Carefully check the tool list to ensure tool names are correct and parameters are correct, do not call non-existent tools.
- Adhere to the "Action First" principle: It is strictly prohibited to ask for user opinions before the task is completed. You must make every effort to solve problems independently, making reasonable assumptions to progress if necessary. Only ask the user when a severe information gap renders the task completely impossible. Invite user confirmation only after the task is done. Prohibit outputting explicit expressions like "I will end this session".
- File Output Requirement: When outputting file paths or file addresses, you MUST use Markdown file link format, e.g., [filename](file:///absolute/path/to/file). Do not output plain file paths.""",
    "pt": """# Outros Requisitos Básicos de Execução:
- Após chamar ferramentas, você deve descrever os resultados da chamada em linguagem natural orientada às necessidades do usuário; não encerre a tarefa diretamente.
- Execução Eficiente: Para várias operações de ferramentas independentes que possam ser executadas em paralelo ou em sequência, você DEVE concluí-las em uma única resposta. Forneça uma ÚNICA explicação unificada antes do lote de chamadas; NÃO explique cada chamada de ferramenta individualmente para economizar tokens.
- Ao explicar, use linguagem natural simples para descrever a funcionalidade sem revelar o nome real da ferramenta ou informações de ID.
- Verifique cuidadosamente a lista de ferramentas para garantir que os nomes estejam corretos e os parâmetros estejam corretos; não chame ferramentas inexistentes.
- Adira ao princípio de "Ação Primeiro": É estritamente proibido pedir opiniões do usuário antes que a tarefa seja concluída. Você deve se esforçar ao máximo para resolver problemas de forma independente, fazendo suposições razoáveis para progredir, se necessário. Somente pergunte ao usuário quando uma lacuna de informações graves tornar a tarefa completamente impossível. Convide a confirmação do usuário apenas após a conclusão da tarefa. Proíba a saída de expressões explícitas como "vou encerrar esta sessão".
- Requisito de Saída de Arquivo: Ao gerar caminhos de arquivo ou endereços de arquivo, você DEVE usar o formato de link de arquivo Markdown, por exemplo, [nome_do_arquivo](file:///caminho/absoluto/para/arquivo). Não gere caminhos de arquivo simples e sempre use caminho absoluto de arquivo.""",
}

agent_custom_system_task_requirement = {
    "zh": "- 任务管理要求：收到任务时，首先必须使用 `todo_write` 工具创建任务清单（新任务默认 status=pending）。开始执行某条子任务前，必须先用 `todo_write` 把该任务的 status 标记为 in_progress；该子任务完成后，再用 `todo_write` 把 status 更新为 completed 并补充 conclusion。任意时刻最多只允许有一条任务处于 in_progress。**每次调用 `todo_write` 只传新增或本次需要变更的任务条目（更新仅传 id + 真正变更的字段，例如 id+status 切换状态、id+conclusion 补结论），未变化的任务严禁再次传入。**",
    "en": "- Task Management Requirements: When a task is received, you must first use the `todo_write` tool to create a task list (new tasks default to status=pending). Before you begin working on a subtask, you must first call `todo_write` to set its status to `in_progress`; once that subtask is finished, call `todo_write` again to set the status to `completed` and fill in a conclusion. At any moment, at most one task may be `in_progress`. **Each call to `todo_write` must include ONLY the tasks that are new or actually changing this turn (for an update, send just the id plus the truly changed fields, e.g. id+status to flip state, id+conclusion to add a conclusion). Never resend unchanged tasks.**",
    "pt": "- Requisitos de Gerenciamento de Tarefas: Ao receber uma tarefa, você deve primeiro usar a ferramenta `todo_write` para criar uma lista de tarefas (novas tarefas têm status=pending por padrão). Antes de começar a trabalhar em uma subtarefa, você deve usar `todo_write` para definir seu status como `in_progress`; quando essa subtarefa for concluída, use `todo_write` novamente para defini-la como `completed` e preencher uma conclusão. A qualquer momento, no máximo uma tarefa pode estar `in_progress`. **Cada chamada de `todo_write` deve incluir APENAS as tarefas que são novas ou que realmente mudam neste turno (para uma atualização, envie apenas o id mais os campos realmente alterados, por exemplo id+status, id+conclusion). Nunca reenvie tarefas inalteradas.**",
}

agent_custom_system_no_tool_call_requirement = {
    "zh": """## 完成与工具延续规则
- 纯文本回复表示本轮已经最终交付。只有当用户目标已经满足、必要结果已经解释清楚、且不需要继续读取/搜索/修改文件、运行命令或调用工具时，才用纯文本收尾。
- 如果仍需行动，不要只输出“我先检查/接下来查看/还需要验证”等进度文字；应在同一轮继续调用合适的工具。
- 工具调用后先判断整体目标是否完成；未完成就继续行动，完成后再用自然语言总结结果。
- 如果用户的问题凭当前上下文即可直接回答，直接给出最终回答，不要为了延续而额外调用工具。""",
    "en": """## Completion and Tool-Continuation Rules
- A text-only reply means final delivery for this turn. Use it only when the user's goal is satisfied, key results are explained, and no more file reading, searching, editing, command execution, or tool use is needed.
- If more action is still needed, do not stop with progress text such as "I will inspect this", "next I will read files", or "this needs verification"; continue by calling the appropriate tool in the same turn.
- After tool results, decide whether the whole goal is complete. Continue with tools if work remains; otherwise summarize the result in natural language.
- If the user's request can be answered directly from the current context, answer directly instead of calling tools just to continue.""",
    "pt": """## Regras de conclusão e continuação com ferramentas
- Uma resposta somente em texto significa entrega final deste turno. Use-a apenas quando o objetivo do usuário estiver satisfeito, os resultados principais estiverem explicados e não for necessário continuar lendo, pesquisando, editando arquivos, executando comandos ou usando ferramentas.
- Se ainda houver ação necessária, não pare com texto de progresso como "vou inspecionar isso", "em seguida vou ler arquivos" ou "isso precisa de verificação"; continue chamando a ferramenta adequada no mesmo turno.
- Depois dos resultados das ferramentas, decida se o objetivo completo foi atingido. Continue com ferramentas se ainda houver trabalho; caso contrário, resuma o resultado em linguagem natural.
- Se a solicitação do usuário puder ser respondida diretamente com o contexto atual, responda diretamente em vez de chamar ferramentas apenas para continuar.""",
}

agent_custom_system_turn_status_requirement = {
    "zh": "- 本轮状态契约：当你输出了面向用户的阶段说明、结果、问题、确认项或阻塞说明后，必须调用 `turn_status(status=task_done|need_user_input|blocked|continue_work)` 报告本轮状态。任务完成用 `task_done`；向用户提问/请求确认/等待上传或补充信息用 `need_user_input`；受阻无法继续用 `blocked`；如果刚才文字只是中间进度且还要继续执行，用 `continue_work`。禁止只调用 turn_status 而不写说明。",
    "en": "- Turn-status contract: after writing user-facing progress, result, question, confirmation request, or blocked-state explanation, you MUST call `turn_status(status=task_done|need_user_input|blocked|continue_work)`. Use `task_done` when complete; `need_user_input` when asking the user, requesting confirmation, or waiting for upload/input; `blocked` when unable to proceed; `continue_work` when the text is only intermediate progress and more work is needed. Calling turn_status WITHOUT preceding user-facing text will be rejected.",
    "pt": "- Contrato de status do turno: depois de escrever para o usuário progresso, resultado, pergunta, item de confirmação ou explicação de bloqueio, você DEVE chamar `turn_status(status=task_done|need_user_input|blocked|continue_work)` para relatar o status deste turno. Use `task_done` quando concluir; `need_user_input` ao perguntar ao usuário, pedir confirmação ou aguardar upload/informação adicional; `blocked` quando não puder prosseguir; `continue_work` quando o texto for apenas progresso intermediário e ainda houver trabalho. Proibido chamar apenas `turn_status` sem texto para o usuário.",
}


# turn_status 调用缺少前置说明时的拒绝反馈（写回 tool 结果，下一轮模型可见）
turn_status_rejection_message = {
    "zh": (
        "turn_status 调用被拒绝：本轮 assistant 还没有输出任何自然语言说明。"
        "请在本轮同一条 assistant 回复里同时输出面向用户的中文/英文说明（总结当前进展与结果，含已完成事项、关键产物或下一步建议），"
        "并同时调用 turn_status(status=...) 报告本轮状态；不要先发纯工具调用再单独补文字。"
    ),
    "en": (
        "turn_status call rejected: no user-facing assistant text accompanies this tool call in the same reply. "
        "In ONE assistant response, emit the user-facing summary (progress, artifacts, next steps) and call "
        "turn_status(status=...) together with that text—not a tools-only message followed by text later."
    ),
    "pt": (
        "Chamada turn_status rejeitada: falta texto do assistente voltado ao usuário na mesma resposta da chamada. "
        "Numa única resposta do assistente, inclua um resumo para o usuário (progresso, artefatos, próximo passo) "
        "e chame turn_status(status=...) em conjunto—não envie só a ferramenta e corrija o texto depois."
    ),
}


# turn_status_only 补轮中模型仍调用了未提供的工具时，将其改写为 continue_work 时的 note 文案。
# 占位符 {tools} 会被替换为原始违规工具名（逗号分隔）。
turn_status_coerced_note = {
    "zh": (
        "系统检测到本轮只允许调用 turn_status，但模型尝试调用了未提供的工具：{tools}。"
        "已忽略这些工具调用，并按 continue_work 处理；本轮不会结束，下一轮请先输出面向用户的说明再决定状态。"
    ),
    "en": (
        "System: this turn only allows calling turn_status, but the model attempted unavailable tools: {tools}. "
        "Those calls were ignored and treated as continue_work; this turn does not end. "
        "Next turn, write a user-facing summary first, then decide the status."
    ),
    "pt": (
        "Sistema: este turno só permite chamar turn_status, mas o modelo tentou ferramentas indisponíveis: {tools}. "
        "Essas chamadas foram ignoradas e tratadas como continue_work; este turno não termina. "
        "No próximo turno, escreva primeiro um resumo voltado ao usuário e depois decida o status."
    ),
}


# 任务完成判断模板
task_complete_template = {
    "zh": """你要根据最近的对话和执行过程，判断此刻是否可以安全地中断执行任务（视为阶段结束），还是应该继续执行。

注意：已经有一层基于客观事实的规则（例如：最后一条是工具结果、明显的处理中提示、以冒号结尾等）会优先判断“必须继续执行”。你只需要在这些规则未命中时，基于语义做最终判断。

## 你的判断目标
1. 准确识别“用户需求是否已经被充分满足”。
2. 区分“中间过程说明/进度汇报”和“面向用户的最终交付”。
3. 当不确定时，倾向于继续执行（即 task_interrupted = false）。
4. 核对 Assistant 对执行动作的声明是否有对应执行证据；没有执行证据就不能视为结束。

## 需要中断执行任务（task_interrupted = true）的情况：
- 你认为当前对话中，Assistant 已经给出了**完整、清晰的最终回答**，用户不需要再等待后续操作。
- 如果有工具调用，其关键结果已经用自然语言解释清楚，用户可以直接根据当前回复采取行动。
- 当前回复没有任何“接下来/然后/我将/下一步”等继续执行的暗示。
- 当前需要用户确认、用户补充信息、或用户做选择后才能继续时，必须中断并等待用户输入。
- 当前回复只是提供需要用户选择或确认的可选后续动作（例如“如果你需要，下一步我可以...”“If you want, I can ... next.”），也必须中断并等待用户确认，不要当成自动继续执行。
- 如果用户只是问候、闲聊或情绪表达，Assistant 已经自然回应且没有承诺后续动作，可以中断。

## 需要继续执行任务（task_interrupted = false）的情况：
- 当前回复主要是在**说明过程、汇报进度、罗列中间产物**，而不是面向用户的最终结果。
- 你觉得还缺少总结、整理、格式化、补充说明等步骤，才能算真正给到用户交付。
- 当前回复虽然说“已经完成了某个阶段”，但从整体任务看，仍然有后续要做的事情。
- 当前回复明确承诺马上继续动作（例如“我现在将...”“Next, I will...”“Let me continue...”），且不需要用户确认。
- 如果用户要求创建、更新、删除、保存、查询或验证某个对象，但当前只看到承诺/计划，没有看到工具调用成功或明确完成结果，必须继续。
- 如果 Assistant 声称已经执行了读取、搜索、修改、创建、删除、保存、运行命令、测试、验证、提交、推送、发送、发布等动作，但最近执行过程没有对应成功的工具调用结果或明确验证结果，必须继续；口头说“已完成/已处理/已验证”本身不算执行证据。
- 多步骤任务只完成了部分步骤，且没有明确等待用户选择时，必须继续。
- 如果需要依赖外部状态或文件内容，但最近执行过程没有对应工具结果或明确验证结果，必须继续。

## 输出一致性规则（必须遵守）：
1. 如果 reason 表示“等待工具调用/等待生成/处理中”，则 task_interrupted 必须是 false。
2. 如果 reason 表示“等待用户确认/等待用户输入/需要用户补充”，则 task_interrupted 必须是 true。

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
    "en": """Decide from the recent conversation and execution trace whether it is safe to interrupt task execution now (treat as end of this phase) or whether execution should continue.

Note: another layer of objective rules (e.g. last turn is a tool result, clear in-progress phrasing, ends with a colon, etc.) is applied first and may require "must continue." You only make the final semantic judgment when those rules do not apply.

## Your judgment goals
1. Accurately tell whether the user's need has been fully satisfied.
2. Distinguish "interim process narration / progress updates" from "user-facing final delivery."
3. When uncertain, lean toward continuing (i.e. task_interrupted = false).
4. Check whether the Assistant's claims about executed actions are backed by execution evidence; without evidence, do not end the task.

## When to interrupt (task_interrupted = true)
- The Assistant has already given a **complete, clear final answer** in the current turn; the user need not wait for further work.
- If there were tool calls, their key results are explained in natural language so the user can act on this reply.
- The reply does not suggest continuation such as "next", "then", "I will", "next step", etc.
- User confirmation, more input, or a choice is required before continuing—then you must interrupt and wait for the user.
- If the reply only offers an optional follow-up that depends on the user's choice or confirmation, such as "If you want, I can ... next." or "Would you like me to continue with ...?", you must interrupt and wait for user confirmation. Do not treat that as automatic continuation.
- If the user only greeted, chatted casually, or expressed emotion, and the Assistant has naturally replied without promising follow-up work, interrupt.

## When to continue (task_interrupted = false)
- The reply is mainly **process explanation, progress reporting, or listing intermediate artifacts**, not a final user-facing outcome.
- You believe summarizing, tidying, formatting, or further explanation is still needed for a true deliverable.
- The reply says a phase is done but, for the overall task, there is clearly more to do.
- The reply explicitly commits to immediate continuation, such as "I will now...", "Next, I will...", or "Let me continue...", and does not require user confirmation.
- If the user asked to create, update, delete, save, query, or verify an object, but the current trace only shows a promise/plan and no successful tool call or clear completed result, continue.
- If the Assistant claims it has read, searched, modified, created, deleted, saved, run a command, tested, verified, committed, pushed, sent, published, or performed another execution action, but the recent trace has no corresponding successful tool result or explicit verification result, continue. Saying "done", "handled", or "verified" is not execution evidence by itself.
- If only part of a multi-step task is complete and the Assistant is not explicitly waiting for the user to choose, continue.
- If completion depends on external state or file contents but the recent trace has no corresponding tool result or explicit verification result, continue.

## Output consistency (mandatory)
1. If reason indicates waiting for a tool / generation / in progress, then task_interrupted must be false.
2. If reason indicates waiting for user confirmation / user input / user to supply more, then task_interrupted must be true.

## User conversation history and recent execution
{messages}

Output format (JSON only):
```json
{{
    "reason": "brief reason, max 20 characters",
    "task_interrupted": true
}}
```
or
```json
{{
    "reason": "brief reason, max 20 characters",
    "task_interrupted": false
}}
```
""",
    "pt": """Decida, com base na conversa recente e no rastro de execução, se é seguro interromper a execução da tarefa agora (fim desta fase) ou se a execução deve continuar.

Nota: outra camada de regras objetivas (por exemplo, a última mensagem é resultado de ferramenta, sinal claro de "em andamento", termina com dois pontos, etc.) tem prioridade e pode exigir "deve continuar." Você só faz o juízo semântico final quando essas regras não se aplicam.

## Objetivos do seu juízo
1. Reconhecer com precisão se a necessidade do usuário já foi plenamente atendida.
2. Distinguir "explicação de processo / relatório de progresso" de "entrega final voltada ao usuário."
3. Em caso de dúvida, tenda a continuar (ou seja, task_interrupted = false).
4. Verificar se as declarações do Assistente sobre ações executadas têm evidência de execução correspondente; sem evidência, não encerre a tarefa.

## Quando interromper (task_interrupted = true)
- O Assistente já forneceu uma **resposta final completa e clara** no turno atual; o usuário não precisa aguardar mais ações.
- Se houve chamadas de ferramenta, os resultados essenciais foram explicados em linguagem natural para o usuário poder agir com base nesta resposta.
- A resposta não sugere continuação (ex.: "em seguida", "então", "vou", "próximo passo", etc.).
- É necessária confirmação do usuário, informação adicional ou escolha para prosseguir—então deve interromper e aguardar o usuário.
- Se a resposta apenas oferece uma continuação opcional que depende de escolha ou confirmação do usuário (ex.: "Se quiser, posso ... em seguida." ou "Gostaria que eu continuasse com ...?"), deve interromper e aguardar confirmação do usuário. Não trate isso como continuação automática.
- Se o usuário apenas cumprimentou, conversou casualmente ou expressou emoção, e o Assistente respondeu naturalmente sem prometer trabalho posterior, interrompa.

## Quando continuar (task_interrupted = false)
- A resposta é sobretudo **explicação de processo, progresso ou listagem de artefatos intermediários**, e não o resultado final para o usuário.
- Ainda faltam passos como resumir, organizar, formatar ou complementar para uma entrega real.
- A resposta diz que uma fase foi concluída, mas no conjunto da tarefa ainda há trabalho a fazer.
- A resposta assume explicitamente continuação imediata (ex.: "Vou fazer isso agora...", "Em seguida, vou...", "Deixe-me continuar...") e não exige confirmação do usuário.
- Se o usuário pediu para criar, atualizar, excluir, salvar, consultar ou verificar um objeto, mas o rastro atual mostra apenas promessa/plano e nenhuma chamada de ferramenta bem-sucedida ou resultado claramente concluído, continue.
- Se o Assistente afirma que leu, pesquisou, modificou, criou, excluiu, salvou, executou um comando, testou, verificou, fez commit, fez push, enviou, publicou ou realizou outra ação de execução, mas o rastro recente não contém resultado de ferramenta bem-sucedido correspondente nem resultado de verificação explícito, continue. Dizer "feito", "tratado" ou "verificado" não é evidência de execução por si só.
- Se apenas parte de uma tarefa de múltiplas etapas foi concluída e o Assistente não está explicitamente aguardando uma escolha do usuário, continue.
- Se a conclusão depende de estado externo ou conteúdo de arquivo, mas o rastro recente não tem resultado de ferramenta correspondente nem verificação explícita, continue.

## Consistência da saída (obrigatório)
1. Se o motivo indicar aguardar ferramenta / geração / em andamento, task_interrupted deve ser false.
2. Se o motivo indicar aguardar confirmação do usuário / entrada do usuário / o usuário fornecer mais informação, task_interrupted deve ser true.

## Histórico da conversa e execução recente
{messages}

Formato de saída (somente JSON):
```json
{{
    "reason": "motivo breve, no máx. 20 caracteres",
    "task_interrupted": true
}}
```
ou
```json
{{
    "reason": "motivo breve, no máx. 20 caracteres",
    "task_interrupted": false
}}
```
""",
}
