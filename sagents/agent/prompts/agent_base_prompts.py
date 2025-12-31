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

