#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作流选择Agent指令定义

包含工作流选择agent使用的指令内容，支持中文、英文和葡萄牙语
"""

# Agent标识符 - 标识这个prompt文件对应的agent类型
AGENT_IDENTIFIER = "WorkflowSelectAgent"

# 工作流选择模板
workflow_select_template = {
    "zh": """你是一个工作流选择专家。请根据用户的对话历史，从提供的工作流模板中选择最合适的一个。
## agent的描述和要求
{agent_description}

## 对话历史
{conversation_history}

## 可用的工作流模板
{workflow_list}

## 任务要求
1. 仔细分析对话历史中用户的核心需求和任务类型
2. 对比各个工作流模板的适用场景
3. 选择匹配的工作流，或者判断没有合适的工作流

## 输出格式（JSON）
```json
{{
    "has_matching_workflow": true/false,
    "selected_workflow_index": 0
}}
```

请确保输出的JSON格式正确。本次输出只输出JSON字符串，不需要包含任何其他内容和解释。
如果没有合适的工作流，请设置has_matching_workflow为false。
selected_workflow_index 从0 开始计数""",
    "en": """You are a workflow selection expert. Please select the most suitable one from the provided workflow templates based on the user's dialogue history.
## Agent Description and Requirements
{agent_description}

## Dialogue History
{conversation_history}

## Available Workflow Templates
{workflow_list}

## Task Requirements
1. Carefully analyze the user's core needs and task types in the dialogue history
2. Compare the applicable scenarios of each workflow template
3. Select a matching workflow, or determine that there is no suitable workflow

## Output Format (JSON)
```json
{{
    "has_matching_workflow": true/false,
    "selected_workflow_index": 0
}}
```

Please ensure the output JSON format is correct. Only output the JSON string without any other content or explanation.
If there is no suitable workflow, please set has_matching_workflow to false.
selected_workflow_index starts counting from 0""",
    "pt": """Você é um especialista em seleção de fluxo de trabalho. Por favor, selecione o mais adequado dos modelos de fluxo de trabalho fornecidos com base no histórico de diálogo do usuário.
## Descrição e Requisitos do Agente
{agent_description}

## Histórico de Diálogo
{conversation_history}

## Modelos de Fluxo de Trabalho Disponíveis
{workflow_list}

## Requisitos da Tarefa
1. Analise cuidadosamente as necessidades principais e os tipos de tarefas do usuário no histórico de diálogo
2. Compare os cenários aplicáveis de cada modelo de fluxo de trabalho
3. Selecione um fluxo de trabalho correspondente ou determine que não há fluxo de trabalho adequado

## Formato de Saída (JSON)
```json
{{
    "has_matching_workflow": true/false,
    "selected_workflow_index": 0
}}
```

Por favor, certifique-se de que o formato JSON de saída está correto. Esta saída produz apenas a string JSON, não precisa conter nenhum outro conteúdo ou explicação.
Se não houver fluxo de trabalho adequado, defina has_matching_workflow como false.
selected_workflow_index começa a contar a partir de 0"""
}