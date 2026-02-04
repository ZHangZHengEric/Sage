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
    "zh": "\n当前工作空间可用技能（当任务与技能相关，优先使用技能来解决用户的需求）：\n",
    "en": "\nAvailable Skills in Workspace(when tasks are related to skills, prioritize using skills to meet user needs) :\n",
    "pt": "\nHabilidades Disponíveis no Espaço de Trabalho(quando as tarefas são relacionadas a habilidades, priorize o uso de habilidades para atender às necessidades dos usuários):\n"
}

skills_usage_hint = {
    "zh": """
**技能使用说明**：
这些技能位于 `/workspace/skills` 目录下。
先试用tree命令行工具查看技能目录结构，再使用 `file_read` 工具阅读技能目录下的 SKILL.md 或 README.md 文件的全部内容(set end_line=None)，确认技能的适用场景、输入/输出要求和使用步骤。
注意事项：1. 按文档说明调用 / 复用 Skill。2. 严禁修改 Skill 仓库内的任何文件。3. 优先从 Skill 仓库匹配适用 Skill。
失败处理：1. 若调用 Skill 时出现失败 / 结果不符合预期（如参数错误、执行报错），先核对使用文档确认是否操作不当，重新按规范执行；2. 若仍失败，向用户反馈「XX Skill 执行失败，无法完成该任务」，不得擅自修改 Skill 内容尝试修复。
""",
    "en": """
**Skill Usage Instructions**:
These skills are located in the `/workspace/skills` directory.
First, use the `tree` command-line tool to view the directory structure of the skills directory, and then use the `file_read` tool to read the full content of the SKILL.md or README.md file in the skill directory(set end_line=None) to confirm the skill's applicable scenarios, input/output requirements, and usage steps.
Notes: 1. Call/reuse the Skill according to the documentation. 2. Strictly forbidden to modify any files within the Skill repository. 3. Prioritize matching applicable Skills from the Skill repository.
Failure Handling: 1. If a Skill call fails or the result is not as expected (e.g., parameter error, execution error), first check the documentation to confirm if the operation was incorrect, and re-execute according to the specifications; 2. If it still fails, report to the user "XX Skill execution failed, unable to complete the task", and do not attempt to modify the Skill content to fix it without permission.
""",
    "pt": """
**Instruções de Uso de Habilidades**:
Essas habilidades estão localizadas no diretório `/workspace/skills`.
Primeiro, use a ferramenta `tree` linha de comando para visualizar a estrutura de diretórios do diretório de habilidades, e depois use a ferramenta `file_read` para ler todo o conteúdo do arquivo SKILL.md ou README.md no diretório da habilidade(set end_line=None) para confirmar os cenários aplicáveis, requisitos de entrada/saída e etapas de uso.
Notas: 1. Chame/reutilize a Habilidade de acordo com a documentação. 2. É estritamente proibido modificar quaisquer arquivos dentro do repositório de Habilidades. 3. Priorize a correspondência de Habilidades aplicáveis do repositório de Habilidades.
Tratamento de Falhas: 1. Se uma chamada de Habilidade falhar ou o resultado não for o esperado (por exemplo, erro de parâmetro, erro de execução), verifique primeiro a documentação para confirmar se a operação foi incorreta e reexecute de acordo com as especificações; 2. Se ainda falhar, informe ao usuário "Execução da Habilidade XX falhou, impossível completar a tarefa", e não tente modificar o conteúdo da Habilidade para corrigi-la sem permissão.
"""
}
