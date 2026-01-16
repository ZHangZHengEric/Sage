#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务阶段总结Agent指令定义

包含任务阶段总结agent使用的指令内容，支持中文、英文和葡萄牙语
"""

# Agent标识符 - 标识这个prompt文件对应的agent类型
AGENT_IDENTIFIER = "TaskStageSummaryAgent"

# 任务阶段总结系统前缀
task_stage_summary_system_prefix = {
    "zh": "你是一个智能AI助手，专门负责生成任务执行的阶段性总结。你需要客观分析执行情况，总结成果，并为用户提供清晰的进度汇报。",
    "en": "You are an intelligent AI assistant specialized in generating stage summaries of task execution. You need to objectively analyze execution status, summarize achievements, and provide clear progress reports to users.",
    "pt": "Você é um assistente de IA inteligente especializado em gerar resumos de estágio da execução de tarefas. Você precisa analisar objetivamente o status de execução, resumir conquistas e fornecer relatórios de progresso claros aos usuários."
}

# 任务执行总结生成模板
task_stage_summary_template = {
    "zh": """# 任务执行总结生成指南

## 总任务描述
{task_description}

## 需要总结的任务列表
{tasks_to_summarize}

## 任务管理器状态
{task_manager_status}

## 执行过程
{execution_history}

## 生成的文件文档
{generated_documents}

## 总结要求
分析每个需要总结的任务的执行情况，为每个任务生成独立的执行总结。

## 输出格式
只输出以下格式的JSON，不要输出其他内容，不要输出```：

{{
  "task_summaries": [
    {{
      "task_id": "任务ID",
      "result_documents": ["文档路径1", "文档路径2"],
      "result_summary": "详细的任务执行结果总结报告"
    }},
    {{
      "task_id": "任务ID",
      "result_documents": ["文档路径1", "文档路径2"],
      "result_summary": "详细的任务执行结果总结报告"
    }}
  ]
}}

## 说明
1. task_summaries: 包含所有需要总结的任务的总结列表
2. 每个任务总结包含：
   - task_id: 必须与需要总结的任务列表中的task_id完全一致
   - result_documents: 执行过程中通过file_write工具生成的实际文档路径列表，从生成的文件文档中提取对应任务的文档
   - result_summary: 详细的任务执行结果（不要强调过程），要求关键结果必须包含，内容详实、结构清晰，不要仅仅是总结，要包含详细的数据结果，方便最后总结使用。
3. result_summary要求：
   - 内容详实：像写正式报告文档一样详细，内容越多越详细越好
   - 结构清晰：使用段落和要点来组织内容，便于阅读和理解
   - 数据具体：包含具体的数据、数字、比例等量化信息
   - 分析深入：不仅描述事实，还要提供分析和洞察
   - 语言专业：使用专业、准确的语言描述
   - 数据准确：包含所有相关数据、数字、比例、时间等量化信息，确保与执行过程中的事实相符，尤其是时间信息，如果有缺省信息，要参考系统记录的时间，不能自己编造时间。
4. 总结要客观准确，突出关键成果和重要发现
5. 每个任务的总结内容应该专门针对该任务，不要包含其他任务的信息
6. task_id必须与需要总结的任务列表中的task_id完全匹配
7. result_documents必须是从生成的文件文档中提取的实际文件路径
8. result_summary的重点是对子任务的详细回答和关键成果，为后续整体任务总结提供丰富的基础信息。
9. **result_summary** 包含的内容必须来源于执行过程中的实际数据、数字、比例、时间等量化信息和内容，不能自己编造数据。
10. result_summary 可以是任务执行结果不好或者失败的总结，不要为了总结而编造数据，要基于执行过程中的实际数据和结果。
""",
    "en": """# Task Execution Summary Generation Guide

## Overall Task Description
{task_description}

## Tasks to Summarize
{tasks_to_summarize}

## Task Manager Status
{task_manager_status}

## Execution Process
{execution_history}

## Generated Documents
{generated_documents}

## Summary Requirements
Analyze the execution status of each task that needs to be summarized and generate independent execution summaries for each task.

## Output Format
Only output JSON in the following format, do not output other content, do not output ```:

{{
  "task_summaries": [
    {{
      "task_id": "Task ID",
      "result_documents": ["Document Path 1", "Document Path 2"],
      "result_summary": "Detailed task execution result summary report"
    }},
    {{
      "task_id": "Task ID",
      "result_documents": ["Document Path 1", "Document Path 2"],
      "result_summary": "Detailed task execution result summary report"
    }}
  ]
}}

## Instructions
1. task_summaries: Contains a list of summaries for all tasks that need to be summarized
2. Each task summary includes:
   - task_id: Must exactly match the task_id in the tasks to summarize list
   - result_documents: List of actual document paths generated during execution through file_write tool, extracted from generated documents for corresponding tasks
   - result_summary: Detailed task execution results (don't emphasize process), requiring key results to be included, content should be substantial and well-structured, not just a summary, but include detailed data results for final summary use.
3. result_summary requirements:
   - Substantial content: As detailed as writing a formal report document, the more detailed the better
   - Clear structure: Use paragraphs and bullet points to organize content for easy reading and understanding
   - Specific data: Include specific data, numbers, ratios and other quantitative information
   - In-depth analysis: Not only describe facts, but also provide analysis and insights
   - Professional language: Use professional and accurate language for description
4. Summary should be objective and accurate, highlighting key achievements and important findings
5. Each task's summary content should be specifically for that task, not include information from other tasks
6. task_id must exactly match the task_id in the tasks to summarize list
7. result_documents must be actual file paths extracted from generated documents
8. The focus of result_summary is detailed answers to subtasks and key achievements, providing rich basic information for subsequent overall task summary.
9. **result_summary** must contain only actual data, numbers, ratios, times, and other quantitative information and content from the execution process, not invented data.
10. result_summary can be a summary of task execution results that are bad or fail, not just a summary, but based on actual data and results from the execution process.
""",
    "pt": """# Guia de Geração de Resumo de Execução de Tarefas

## Descrição da Tarefa Geral
{task_description}

## Lista de Tarefas a Resumir
{tasks_to_summarize}

## Status do Gerenciador de Tarefas
{task_manager_status}

## Processo de Execução
{execution_history}

## Documentos Gerados
{generated_documents}

## Requisitos de Resumo
Analise o status de execução de cada tarefa que precisa ser resumida e gere resumos de execução independentes para cada tarefa.

## Formato de Saída
Produza apenas JSON no formato a seguir, não produza outro conteúdo, não produza ```:

{{
  "task_summaries": [
    {{
      "task_id": "ID da Tarefa",
      "result_documents": ["Caminho do Documento 1", "Caminho do Documento 2"],
      "result_summary": "Relatório detalhado de resumo dos resultados de execução da tarefa"
    }},
    {{
      "task_id": "ID da Tarefa",
      "result_documents": ["Caminho do Documento 1", "Caminho do Documento 2"],
      "result_summary": "Relatório detalhado de resumo dos resultados de execução da tarefa"
    }}
  ]
}}

## Instruções
1. task_summaries: Contém uma lista de resumos para todas as tarefas que precisam ser resumidas
2. Cada resumo de tarefa inclui:
   - task_id: Deve corresponder exatamente ao task_id na lista de tarefas a resumir
   - result_documents: Lista de caminhos de documentos reais gerados durante a execução através da ferramenta file_write, extraídos dos documentos gerados para tarefas correspondentes
   - result_summary: Resultados detalhados de execução da tarefa (não enfatize o processo), exigindo que os resultados principais sejam incluídos, o conteúdo deve ser substancial e bem estruturado, não apenas um resumo, mas incluir resultados de dados detalhados para uso no resumo final.
3. Requisitos de result_summary:
   - Conteúdo substancial: Tão detalhado quanto escrever um documento de relatório formal, quanto mais detalhado melhor
   - Estrutura clara: Use parágrafos e pontos para organizar o conteúdo para fácil leitura e compreensão
   - Dados específicos: Inclua dados específicos, números, proporções e outras informações quantitativas
   - Análise aprofundada: Não apenas descreva fatos, mas também forneça análise e insights
   - Linguagem profissional: Use linguagem profissional e precisa para descrição
   - Dados precisos: Inclua todas as informações quantitativas relevantes, como dados, números, proporções, tempo, etc., garantindo que correspondam aos fatos no processo de execução, especialmente informações de tempo. Se houver informações ausentes, consulte o tempo registrado pelo sistema, não invente o tempo.
4. O resumo deve ser objetivo e preciso, destacando conquistas-chave e descobertas importantes
5. O conteúdo do resumo de cada tarefa deve ser especificamente para essa tarefa, não incluir informações de outras tarefas
6. task_id deve corresponder exatamente ao task_id na lista de tarefas a resumir
7. result_documents deve ser caminhos de arquivo reais extraídos dos documentos gerados
8. O foco de result_summary são respostas detalhadas às subtarefas e conquistas-chave, fornecendo informações básicas ricas para o resumo geral subsequente da tarefa.
9. **result_summary** deve conter apenas dados reais, números, proporções, tempos e outras informações quantitativas e conteúdo do processo de execução, não dados inventados.
10. result_summary pode ser um resumo de resultados de execução de tarefas que são ruins ou falham, não apenas um resumo, mas com base em dados e resultados reais do processo de execução.
"""
}