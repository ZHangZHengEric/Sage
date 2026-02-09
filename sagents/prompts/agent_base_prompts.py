#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentBase通用指令定义

包含AgentBase使用的通用指令内容，支持中文、英文和葡萄牙语
"""

# Agent标识符 - 标识这个prompt文件对应的agent类型
AGENT_IDENTIFIER = "common"

# 智能体介绍模板
agent_intro_template = {
    "zh": "\n你是一个{agent_name}智能体。",
    "en": "\nYou are a {agent_name} agent.",
    "pt": "\nVocê é um agente {agent_name}."
}

# 补充信息提示
additional_info_label = {
    "zh": "\n补充其他的信息：\n ",
    "en": "\nAdditional information:\n ",
    "pt": "\nInformações adicionais:\n "
}

# 工作空间文件情况提示
workspace_files_label = {
    "zh": "\n当前工作空间 {workspace} 的文件情况：\n",
    "en": "\nFile status in current workspace {workspace}:\n",
    "pt": "\nStatus dos arquivos no espaço de trabalho atual {workspace}:\n"
}

# 无文件提示
no_files_message = {
    "zh": "当前工作空间下没有文件。\n",
    "en": "There are no files in the current workspace.\n",
    "pt": "Não há arquivos no espaço de trabalho atual.\n"
}

# 任务管理器相关文本
task_manager_no_tasks = {
    "zh": "任务管理器中暂无任务",
    "en": "Task manager has no tasks",
    "pt": "O gerenciador de tarefas não tem tarefas"
}

task_manager_contains_tasks = {
    "zh": "任务管理器包含 {count} 个任务：",
    "en": "Task manager contains {count} tasks:",
    "pt": "O gerenciador de tarefas contém {count} tarefas:"
}

task_manager_task_info = {
    "zh": "- 任务ID: {task_id}, 描述: {description}, 状态: {status}",
    "en": "- Task ID: {task_id}, Description: {description}, Status: {status}",
    "pt": "- ID da Tarefa: {task_id}, Descrição: {description}, Status: {status}"
}

task_info_simple = {
    "zh": "- 任务ID: {task_id}, 描述: {description}",
    "en": "- Task ID: {task_id}, Description: {description}",
    "pt": "- ID da Tarefa: {task_id}, Descrição: {description}"
}

task_manager_status_failed = {
    "zh": "任务管理器状态获取失败: {error}",
    "en": "Failed to get task manager status: {error}",
    "pt": "Falha ao obter status do gerenciador de tarefas: {error}"
}

task_manager_none = {
    "zh": "无任务管理器",
    "en": "No task manager",
    "pt": "Sem gerenciador de tarefas"
}

# 任务分解相关文本
task_decomposition_planning = {
    "zh": "任务拆解规划：",
    "en": "Task Decomposition Planning:",
    "pt": "Planejamento de Decomposição de Tarefas:"
}

task_decomposition_failed = {
    "zh": "任务分解失败: {error}",
    "en": "Task decomposition failed: {error}",
    "pt": "Falha na decomposição de tarefas: {error}"
}

# 阶段性总结相关文本
stage_summary_label = {
    "zh": "阶段性任务总结：",
    "en": "Stage Task Summary:",
    "pt": "Resumo da Tarefa por Etapa:"
}

no_generated_documents = {
    "zh": "本次执行过程中没有生成任何文件文档。",
    "en": "No file documents were generated during this execution.",
    "pt": "Nenhum documento de arquivo foi gerado durante esta execução."
}

file_path_label = {
    "zh": "文件路径:",
    "en": "File path:",
    "pt": "Caminho do arquivo:"
}

generated_documents_summary = {
    "zh": "本次执行过程中生成了 {count} 个文件文档：",
    "en": "{count} file documents were generated during this execution:",
    "pt": "{count} documentos de arquivo foram gerados durante esta execução:"
}

cannot_extract_documents = {
    "zh": "无法提取生成文档信息。",
    "en": "Unable to extract generated document information.",
    "pt": "Não foi possível extrair informações dos documentos gerados."
}

# Skills 相关提示
skills_info_label = {
    "zh": "\n当前工作空间可用技能Skills（**重点：当任务与技能相关，优先使用技能来解决用户的需求**）：\n",
    "en": "\nAvailable Skills in Workspace(**Priority: When tasks are related to skills, prioritize using skills to meet user needs**):\n",
    "pt": "\nHabilidades Disponíveis no Espaço de Trabalho(**Prioridade: quando as tarefas são relacionadas a habilidades, priorize o uso de habilidades para atender às necessidades dos usuários**):\n"
}
skills_usage_hint = {
    "zh": """
**技能使用说明**：
技能文件统一存放于 `/workspace/skills` 目录下。
基于当前工作空间内已有的可用技能，选定某一个指定技能后，执行以下操作：
1. 先用 `tree` 命令行工具查看该指定技能的目录结构，
2. 再使用 `file_read` 工具读取该技能目录下的 SKILL.md 或 README.md 文件全部内容（设置 `end_line=None`），确认该技能的适用场景、输入/输出要求及使用步骤。
注意事项
1. 需严格按照该指定技能的文档说明，调用或复用该Skill。
2. 严禁修改该指定Skill仓库内的任何文件。
3. 优先从当前工作空间的可用技能中，匹配适用的Skill。
失败处理
1. 若调用某一Skill时出现执行失败、结果不符合预期（如参数错误、执行报错等），需先核对该技能的使用文档，确认操作是否得当，再按规范重新执行；
2. 若仍失败，向用户反馈「XX Skill 执行失败，无法完成该任务」，不得擅自修改 Skill 内容尝试修复。
""",
    "en": """
**Skill Usage Instructions**:
Skill files are uniformly stored in the `/workspace/skills` directory.
Based on the available skills in the current workspace, select a specified skill after, and then perform the following operations:
1. First, use the `tree` command-line tool to view the directory structure of the skill directory,
2. Then use the `file_read` tool to read the full content of the SKILL.md or README.md file in the skill directory(set end_line=None) to confirm the applicable scenarios, input/output requirements, and usage steps of the skill.
Note
1. Strictly follow the documentation of the specified skill when calling or reusing the Skill.
2. Strictly prohibit modifying any files within the specified Skill repository.
3. Prioritize matching applicable Skills from the Skill repository in the current workspace.
Failure Handling
1. If a Skill call fails or the result is not as expected (e.g., parameter error, execution error), first check the documentation to confirm if the operation was incorrect, and re-execute according to the specifications;
2. If it still fails, report to the user "XX Skill execution failed, unable to complete the task", and do not attempt to modify the Skill content to fix it without permission.
""",
    "pt": """
**Instruções de Uso de Habilidades**:
Os arquivos de habilidades estão armazenados uniformemente no diretório `/workspace/skills`.
Com base nas habilidades disponíveis no espaço de trabalho atual, após selecionar uma habilidade específica, execute as seguintes operações:
1. Primeiro, use a ferramenta de linha de comando `tree` para visualizar a estrutura do diretório da habilidade,
2. Em seguida, use a ferramenta `file_read` para ler todo o conteúdo do arquivo SKILL.md ou README.md no diretório da habilidade (defina end_line=None), confirmando os cenários aplicáveis, requisitos de entrada/saída e etapas de uso da habilidade.
Observações
1. É necessário seguir rigorosamente a documentação da habilidade especificada ao chamar ou reutilizar a Skill.
2. É proibido modificar qualquer arquivo dentro do repositório da Skill especificada.
3. Priorize a correspondência de Skills aplicáveis a partir do repositório de Skills no espaço de trabalho atual.
Tratamento de Falhas
1. Se a chamada de uma Skill falhar ou o resultado não for o esperado (por exemplo, erro de parâmetro, erro de execução), primeiro verifique a documentação para confirmar se a operação foi incorreta e reexecute de acordo com as especificações;
2. Se ainda falhar, informe ao usuário "Falha na execução da Skill XX, incapaz de completar a tarefa" e não tente modificar o conteúdo da Skill para corrigir sem permissão.
"""
}
