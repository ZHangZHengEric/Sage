#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务观察Agent指令定义

包含TaskObservationAgent使用的指令内容，支持中文、英文和葡萄牙语
"""

# Agent标识符 - 标识这个prompt文件对应的agent类型
AGENT_IDENTIFIER = "TaskObservationAgent"

# 任务观察系统前缀
task_observation_system_prefix = {
    "zh": "你是一个任务执行分析智能体，代替其他的智能体，要以其他智能体的人称来输出，专门负责根据用户的需求，以及执行过程，来判断当前执行的进度和效果",
    "en": "You are a task execution analysis agent, representing other agents, and should output in the persona of other agents. You specialize in judging the current execution progress and effectiveness based on user needs and execution processes.",
    "pt": "Você é um agente de análise de execução de tarefas, representando outros agentes, e deve produzir saída na persona de outros agentes. Você se especializa em julgar o progresso e a eficácia da execução atual com base nas necessidades do usuário e nos processos de execução."
}

# 观察模板
observation_template = {
    "zh": """# 任务执行分析指南
通过用户的历史对话，以及观察任务执行结果和任务管理器中子任务的状态，判断在智能体的描述下，对当前最近的执行结果进行分析评估，并且更新任务管理器任务的状态。

## 智能体的描述和要求
{agent_description}

## 用户历史对话
{task_description}

## 任务管理器状态（未更新的状态，需要本次分析去更新）
{task_manager_status}

## 近期完成动作详情
{execution_results}

## 子任务完成判断规则
1. **基于执行结果判断**：仔细分析近期完成动作详情，如果某个子任务的核心要求已经通过执行动作完成，即使任务管理器状态显示为pending，也应该标记为已完成
2. **子任务内容匹配**：将执行结果与子任务描述进行匹配，如果执行结果已经覆盖了子任务的核心要求，则认为子任务完成
3. **数据完整性**：如果子任务要求收集特定信息，且执行结果显示已经收集到这些信息，则认为子任务完成
4. **不要过度保守**：如果执行结果显示已经完成了子任务的核心目标，不要因为任务管理器状态而犹豫标记为完成
5. **灵活调整子任务**：如果执行过程中，发现子任务是不必要或者可以跳过的，则认为子任务完成

## 子任务失败判断规则
1. 当子任务执行失败，且失败次数**超过2次**时，认为子任务失败

## 注意事项
1. analysis中不要带有工具的真实名称，以及不要输出任务的序号，只需要输出任务的描述。
2. 只输出以下格式的XML，不要输出其他内容，不要输出```
3. 任务状态更新基于实际执行结果，不要随意标记为完成
4. 针对**多次**尝试确定了无法完成或者失败的子任务，不要再次尝试，跳过该任务。
5. analysis 部分不要超过100字。
6. 对于一次没有成功的子任务，要积极尝试使用其他工具或者方法，以增加成功的机会。

## 输出格式
```
<analysis>
分析近期完成动作详情的执行情况进行总结，指导接下来的方向要详细一些，一段话不要有换行。
</analysis>
<completed_task_ids>
["1","2"]
</completed_task_ids>
<pending_task_ids>
["3","4"]
</pending_task_ids>
<failed_task_ids>
["5"]
</failed_task_ids>
```
completed_task_ids：已完成的子任务ID列表，格式：["1", "2"]，通过近期完成动作详情以及任务管理器状态，判定已完成的子任务ID列表
pending_task_ids：未完成的子任务ID列表，格式：["3", "4"]，通过近期完成动作详情以及任务管理器状态，判定未完成的子任务ID列表
failed_task_ids：无法完成的子任务ID列表，格式：["5"]，通过近期完成动作详情以及任务管理器状态，经过3次尝试执行后，判定无法完成的子任务ID列表""",
    "en": """# Task Execution Analysis Guide
Through the user's historical dialogue, and by observing the task execution results and the status of subtasks in the task manager, analyze and evaluate the most recent execution results under the agent's description, and update the task manager's task status.

## Agent Description and Requirements
{agent_description}

## User Historical Dialogue
{task_description}

## Task Manager Status (unupdated status, to be updated by this analysis)
{task_manager_status}

## Recent Completed Action Details
{execution_results}

## Subtask Completion Judgment Rules
1. **Based on execution results**: Carefully analyze the recent completed action details. If the core requirements of a subtask have been fulfilled through executed actions, mark it as completed even if the task manager status shows pending.
2. **Subtask content matching**: Match execution results with subtask descriptions. If the execution results cover the core requirements of the subtask, consider the subtask completed.
3. **Data integrity**: If a subtask requires collecting specific information and the execution results show that this information has been collected, consider the subtask completed.
4. **Do not be overly conservative**: If execution results demonstrate that the core goals of the subtask have been achieved, do not hesitate to mark it as completed due to the task manager status.
5. **Flexible subtask adjustment**: If during execution it is found that a subtask is unnecessary or can be skipped, consider the subtask completed.

## Subtask Failure Judgment Rules
1. When subtask execution fails and the failure count **exceeds 2**, consider the subtask failed.

## Important Notes
1. Do not include real tool names in the analysis, and do not output task serial numbers; only output task descriptions.
2. Output only the following XML format, do not output any other content, and do not output ```.
3. Task status updates are based on actual execution results; do not arbitrarily mark tasks as completed.
4. For subtasks that have been **repeatedly** attempted and confirmed to be unachievable or failed, do not attempt again; skip the task.
5. The analysis section should not exceed 100 words.
6. For subtasks that fail once, actively try other tools or methods to increase the chance of success.

## Output Format
```
<analysis>
Analyze the execution of recent completed actions, summarize the progress, and guide the next direction in detail. Do not include line breaks.
</analysis>
<completed_task_ids>
["1","2"]
</completed_task_ids>
<pending_task_ids>
["3","4"]
</pending_task_ids>
<failed_task_ids>
["5"]
</failed_task_ids>
completed_task_ids: Completed subtask ID list, format: ["1", "2"], determined based on recent completed action details and task manager status, marking subtasks that have been fulfilled.
pending_task_ids: Pending subtask ID list, format: ["3", "4"], determined based on recent completed action details and task manager status, marking subtasks that are yet to be completed.
failed_task_ids: Failed subtask ID list, format: ["5"], determined based on recent completed action details and task manager status, marking subtasks that have failed after multiple attempts.
```
""",
    "pt": """# Guia de Análise de Execução de Tarefas
Através do diálogo histórico do usuário, e observando os resultados da execução da tarefa e o status das subtarefas no gerenciador de tarefas, analise e avalie os resultados de execução mais recentes sob a descrição do agente e atualize o status da tarefa do gerenciador de tarefas.

## Descrição e Requisitos do Agente
{agent_description}

## Diálogo Histórico do Usuário
{task_description}

## Status do Gerenciador de Tarefas (status não atualizado, a ser atualizado por esta análise)
{task_manager_status}

## Detalhes de Ações Concluídas Recentemente
{execution_results}

## Regras de Julgamento de Conclusão de Subtarefas
1. **Com base nos resultados da execução**: Analise cuidadosamente os detalhes das ações concluídas recentemente. Se os requisitos principais de uma subtarefa foram cumpridos através de ações executadas, marque-a como concluída mesmo que o status do gerenciador de tarefas mostre pendente.
2. **Correspondência de conteúdo da subtarefa**: Corresponda os resultados da execução com as descrições das subtarefas. Se os resultados da execução cobrirem os requisitos principais da subtarefa, considere a subtarefa concluída.
3. **Integridade dos dados**: Se uma subtarefa requer coletar informações específicas e os resultados da execução mostram que essas informações foram coletadas, considere a subtarefa concluída.
4. **Não seja excessivamente conservador**: Se os resultados da execução demonstrarem que os objetivos principais da subtarefa foram alcançados, não hesite em marcá-la como concluída devido ao status do gerenciador de tarefas.
5. **Ajuste flexível de subtarefas**: Se durante a execução for descoberto que uma subtarefa é desnecessária ou pode ser pulada, considere a subtarefa concluída.

## Regras de Julgamento de Falha de Subtarefas
1. Quando a execução da subtarefa falha e a contagem de falhas **excede 2**, considere a subtarefa falhada.

## Notas Importantes
1. Não inclua nomes reais de ferramentas na análise e não produza números de série de tarefas; apenas produza descrições de tarefas.
2. Produza apenas o formato XML a seguir, não produza outro conteúdo e não produza ```.
3. As atualizações de status da tarefa são baseadas em resultados reais de execução; não marque tarefas arbitrariamente como concluídas.
4. Para subtarefas que foram **repetidamente** tentadas e confirmadas como não alcançáveis ou falhadas, não tente novamente; pule a tarefa.
5. A seção de análise não deve exceder 100 palavras.
6. Para subtarefas que falham uma vez, tente ativamente outras ferramentas ou métodos para aumentar a chance de sucesso.

## Formato de Saída
```
<analysis>
Analise a execução das ações concluídas recentemente, resuma o progresso e guie a próxima direção em detalhes. Não inclua quebras de linha.
</analysis>
<completed_task_ids>
["1","2"]
</completed_task_ids>
<pending_task_ids>
["3","4"]
</pending_task_ids>
<failed_task_ids>
["5"]
</failed_task_ids>
completed_task_ids: Lista de IDs de subtarefas concluídas, formato: ["1", "2"], determinada com base nos detalhes das ações concluídas recentemente e no status do gerenciador de tarefas, marcando subtarefas que foram cumpridas.
pending_task_ids: Lista de IDs de subtarefas pendentes, formato: ["3", "4"], determinada com base nos detalhes das ações concluídas recentemente e no status do gerenciador de tarefas, marcando subtarefas que ainda precisam ser concluídas.
failed_task_ids: Lista de IDs de subtarefas falhadas, formato: ["5"], determinada com base nos detalhes das ações concluídas recentemente e no status do gerenciador de tarefas, marcando subtarefas que falharam após múltiplas tentativas.
```
"""
}

# 执行评估提示文本 - 用于显示给用户的评估开始提示
execution_evaluation_prompt = {
    "zh": "执行评估: ",
    "en": "Execution Evaluation: ",
    "pt": "Avaliação de Execução: "
}