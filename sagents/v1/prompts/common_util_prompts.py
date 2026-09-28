#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Common utility prompts used across sagents.
"""

AGENT_IDENTIFIER = "common_util"

auto_gen_agent_system_context_prompt = {
    "zh": (
        "你正在为当前 Agent 生成可直接使用的能力模板。\n"
        "如有必要，可以把当前运行环境基础信息当作背景事实使用。\n"
        "当前本地时间：{current_time}\n"
        "当前时区：{timezone_name}\n"
        "除非确实有助于生成更好的模板，否则不要在结果中直接复述这些系统信息。"
    ),
    "en": (
        "You are generating deterministic prompt suggestions for the current agent.\n"
        "Use the current runtime context as background facts when helpful.\n"
        "Current local time: {current_time}\n"
        "Current timezone: {timezone_name}\n"
        "Do not mention these system facts explicitly unless they materially help produce better prompts."
    ),
    "pt": (
        "Você está gerando modelos de capacidade diretamente utilizáveis para o agente atual.\n"
        "Se necessário, use as informações básicas do ambiente atual como fatos de contexto.\n"
        "Hora local atual: {current_time}\n"
        "Fuso horário atual: {timezone_name}\n"
        "A menos que realmente ajude a gerar modelos melhores, não repita essas informações do sistema na resposta."
    ),
}

auto_gen_agent_basic_config_prompt = {
    "zh": """请根据以下Agent描述和可用工具能力，生成Agent的基础配置信息：

Agent描述：{description}

可用工具能力：
{tools_summary}

请生成以下内容，并以JSON格式返回：
1. name: Agent的名称（简洁明了，中文）
2. description: Agent的简要介绍（一句话概括）
3. systemPrefix: Agent的详细系统提示词，按照以下格式：

# 角色
关于角色的详细描述

## 目标
明确描述该Agent要达成的具体目标和使命

## 技能
基于可用工具能力，详细描述该Agent具备的技能：
### 技能1: 名称
技能1的介绍（基于可用工具能力）

### 技能2: 名称
技能2的介绍（基于可用工具能力）

## 限制
- 限制1：只能使用已提供的工具能力
- 限制2：其他相关限制

## 输出形式要求
- 要求1
- 要求2

## 其他特殊要求
- 要求1
- 要求2

注意：
1. 技能部分必须基于实际可用的工具能力来描述，不要描述无法实现的功能
2. 确保Agent的能力与可用工具保持一致
3. 请确保返回的是有效的JSON格式，包含name、description、systemPrefix三个字段。""",
    "en": """Please generate the Agent's basic configuration information based on the following Agent description and available tool capabilities:

Agent description: {description}

Available tool capabilities:
{tools_summary}

Please generate the following content and return it in JSON format:
1. name: the Agent's name (concise and clear, in Chinese)
2. description: a brief introduction to the Agent (one-sentence summary)
3. systemPrefix: the Agent's detailed system prompt, following this structure:

# Role
Detailed description of the role

## Goal
Clearly describe the concrete goal and mission of this Agent

## Skills
Based on the available tool capabilities, describe in detail the skills this Agent has:
### Skill 1: Name
Introduction to skill 1 (based on available tool capabilities)

### Skill 2: Name
Introduction to skill 2 (based on available tool capabilities)

## Constraints
- Constraint 1: only use the provided tool capabilities
- Constraint 2: other related constraints

## Output Requirements
- Requirement 1
- Requirement 2

## Other Special Requirements
- Requirement 1
- Requirement 2

Notes:
1. The skills section must be based on the actual available tool capabilities and must not describe impossible functions
2. Make sure the Agent's capabilities are consistent with the available tools
3. Ensure the response is valid JSON containing name, description, and systemPrefix fields.""",
    "pt": """Por favor, gere as informações básicas de configuração do Agente com base na seguinte descrição do Agente e nas capacidades das ferramentas disponíveis:

Descrição do Agente: {description}

Capacidades das ferramentas disponíveis:
{tools_summary}

Por favor, gere o conteúdo a seguir e retorne em formato JSON:
1. name: nome do Agente (curto e claro, em chinês)
2. description: breve introdução do Agente (resumo em uma frase)
3. systemPrefix: prompt de sistema detalhado do Agente, seguindo esta estrutura:

# Papel
Descrição detalhada do papel

## Objetivo
Descreva claramente o objetivo concreto e a missão deste Agente

## Habilidades
Com base nas capacidades das ferramentas disponíveis, descreva em detalhes as habilidades que este Agente possui:
### Habilidade 1: Nome
Introdução à habilidade 1 (com base nas capacidades das ferramentas disponíveis)

### Habilidade 2: Nome
Introdução à habilidade 2 (com base nas capacidades das ferramentas disponíveis)

## Restrições
- Restrição 1: use apenas as capacidades de ferramentas fornecidas
- Restrição 2: outras restrições relacionadas

## Requisitos de Saída
- Requisito 1
- Requisito 2

## Outros Requisitos Especiais
- Requisito 1
- Requisito 2

Observações:
1. A seção de habilidades deve ser baseada nas capacidades reais das ferramentas disponíveis e não pode descrever funções impossíveis
2. Garanta que as capacidades do Agente sejam consistentes com as ferramentas disponíveis
3. Certifique-se de que a resposta seja JSON válido contendo os campos name, description e systemPrefix.""",
}

auto_gen_agent_tool_selection_prompt = {
    "zh": """请根据以下Agent配置和可用工具列表，选择最适合的工具：

Agent名称：{name}
Agent描述：{description}
Agent系统提示词：
{systemPrefix}

可用工具列表：
{tools_summary}

请分析Agent的系统提示词和功能需求，选择最相关和必要的工具。
请以JSON数组格式返回选中的工具名称，例如：["tool1", "tool2", "tool3"]

注意：
1. 基于Agent的系统提示词中描述的技能和能力来选择工具
2. 只选择真正需要的工具，避免选择过多无关工具
3. 确保选择的工具名称与可用工具列表中的名称完全一致
4. 返回的必须是有效的JSON数组格式""",
    "en": """Please select the most suitable tools based on the following Agent configuration and available tool list:

Agent name: {name}
Agent description: {description}
Agent system prompt:
{systemPrefix}

Available tool list:
{tools_summary}

Please analyze the Agent system prompt and functional requirements, and select the most relevant and necessary tools.
Return the selected tool names in JSON array format, for example: ["tool1", "tool2", "tool3"]

Notes:
1. Select tools based on the skills and capabilities described in the Agent system prompt
2. Only choose tools that are truly needed, avoid selecting too many irrelevant tools
3. Make sure the selected tool names exactly match the names in the available tool list
4. The response must be a valid JSON array format""",
    "pt": """Por favor, selecione as ferramentas mais adequadas com base na configuração do Agente a seguir e na lista de ferramentas disponíveis:

Nome do Agente: {name}
Descrição do Agente: {description}
Prompt de sistema do Agente:
{systemPrefix}

Lista de ferramentas disponíveis:
{tools_summary}

Analise o prompt de sistema do Agente e os requisitos funcionais, e selecione as ferramentas mais relevantes e necessárias.
Retorne os nomes das ferramentas selecionadas em formato de array JSON, por exemplo: ["tool1", "tool2", "tool3"]

Observações:
1. Selecione as ferramentas com base nas habilidades e capacidades descritas no prompt de sistema do Agente
2. Escolha apenas as ferramentas realmente necessárias, evitando selecionar muitas ferramentas irrelevantes
3. Garanta que os nomes das ferramentas selecionadas correspondam exatamente aos nomes na lista de ferramentas disponíveis
4. A resposta deve ser um array JSON válido""",
}

auto_gen_agent_workflow_generation_prompt = {
    "zh": """请根据以下Agent配置和选定的工具，设计3-5个主要的工作流程：

Agent名称：{name}
Agent描述：{description}
Agent系统提示词：
{systemPrefix}

选定的工具：{selected_tools}

请基于Agent的系统提示词中描述的技能和能力，为每个工作流程设计详细的执行步骤，每个步骤应该说明：
1. 具体要做什么
2. 需要调用哪个工具（如果需要的话）
3. 如何处理结果

请以JSON格式返回，格式如下：
{
  "工作流程1名称": [
    "步骤1：具体描述",
    "步骤2：调用xxx工具获取信息",
    "步骤3：处理和分析结果"
  ],
  "工作流程2名称": [
    "步骤1：具体描述",
    "步骤2：具体描述"
  ]
}

注意：
1. 工作流程要与Agent的系统提示词中描述的技能保持一致
2. 工作流程名称要简洁明了
3. 步骤描述要具体可执行
4. 合理使用选定的工具
5. 返回有效的JSON格式""",
    "en": """Please design 3-5 main workflows based on the following Agent configuration and selected tools:

Agent name: {name}
Agent description: {description}
Agent system prompt:
{systemPrefix}

Selected tools: {selected_tools}

Based on the skills and capabilities described in the Agent system prompt, design detailed execution steps for each workflow. Each step should explain:
1. What specifically to do
2. Which tool to call (if needed)
3. How to handle the result

Return in JSON format as follows:
{
  "Workflow 1 name": [
    "Step 1: specific description",
    "Step 2: call xxx tool to obtain information",
    "Step 3: process and analyze the result"
  ],
  "Workflow 2 name": [
    "Step 1: specific description",
    "Step 2: specific description"
  ]
}

Notes:
1. Workflows must be consistent with the skills described in the Agent system prompt
2. Workflow names should be concise and clear
3. Step descriptions should be concrete and executable
4. Use selected tools reasonably
5. Return valid JSON""",
    "pt": """Por favor, projete de 3 a 5 fluxos de trabalho principais com base na configuração do Agente a seguir e nas ferramentas selecionadas:

Nome do Agente: {name}
Descrição do Agente: {description}
Prompt de sistema do Agente:
{systemPrefix}

Ferramentas selecionadas: {selected_tools}

Com base nas habilidades e capacidades descritas no prompt de sistema do Agente, projete etapas de execução detalhadas para cada fluxo de trabalho. Cada etapa deve explicar:
1. O que fazer especificamente
2. Qual ferramenta chamar (se necessário)
3. Como tratar o resultado

Retorne em formato JSON, da seguinte forma:
{
  "Nome do fluxo 1": [
    "Etapa 1: descrição específica",
    "Etapa 2: chamar a ferramenta xxx para obter informações",
    "Etapa 3: processar e analisar o resultado"
  ],
  "Nome do fluxo 2": [
    "Etapa 1: descrição específica",
    "Etapa 2: descrição específica"
  ]
}

Observações:
1. Os fluxos de trabalho devem ser consistentes com as habilidades descritas no prompt de sistema do Agente
2. Os nomes dos fluxos devem ser concisos e claros
3. As descrições das etapas devem ser concretas e executáveis
4. Use as ferramentas selecionadas de forma razoável
5. Retorne JSON válido""",
}

auto_gen_agent_default_system_prefix = {
    "zh": "你是一个智能助手。",
    "en": "You are a smart assistant.",
    "pt": "Você é um assistente inteligente.",
}

auto_gen_agent_default_basic_config_system_prefix = {
    "zh": """# 角色
你是一个智能助手，根据用户需求提供帮助。

## 目标
根据用户的具体需求描述，提供准确、有效的帮助和解决方案

## 技能
### 技能1: 信息查询
能够查询和检索相关信息

### 技能2: 任务执行
能够执行用户指定的任务

## 限制
- 确保回答准确可靠
- 遵循用户的具体要求

## 输出形式要求
- 回答简洁明了
- 提供具体可行的建议

## 其他特殊要求
- 保持友好的交流方式
- 及时响应用户需求""",
    "en": """# Role
You are a smart assistant that helps users based on their needs.

## Goal
Provide accurate and effective help and solutions according to the user's specific needs

## Skills
### Skill 1: Information Retrieval
Able to query and retrieve relevant information

### Skill 2: Task Execution
Able to execute tasks specified by the user

## Constraints
- Ensure answers are accurate and reliable
- Follow the user's specific requirements

## Output Requirements
- Keep answers concise and clear
- Provide specific and feasible suggestions

## Other Special Requirements
- Maintain a friendly communication style
- Respond to user needs in a timely manner""",
    "pt": """# Papel
Você é um assistente inteligente que ajuda os usuários com base em suas necessidades.

## Objetivo
Fornecer ajuda e soluções precisas e eficazes de acordo com as necessidades específicas do usuário

## Habilidades
### Habilidade 1: Recuperação de Informações
Capaz de consultar e recuperar informações relevantes

### Habilidade 2: Execução de Tarefas
Capaz de executar tarefas especificadas pelo usuário

## Restrições
- Garantir que as respostas sejam precisas e confiáveis
- Seguir os requisitos específicos do usuário

## Requisitos de Saída
- Manter as respostas concisas e claras
- Fornecer sugestões específicas e viáveis

## Outros Requisitos Especiais
- Manter um estilo de comunicação amigável
- Responder às necessidades do usuário de forma oportuna""",
}

system_prompt_optimizer_section_definitions = {
    "role": {
        "description": "角色定义内容（简洁明确的角色描述，说明AI的身份和主要职责）",
        "examples": "例如：你是一个专业的数据分析师、你是一个客户服务助手等",
        "avoid_confusion": "不要包含具体的技能列表或操作指导",
    },
    "skills": {
        "description": "技能列表内容（无序列表格式，每项技能要具体明确，说明AI具备的专业能力）",
        "examples": "例如：数据分析能力、客户沟通技巧、问题解决能力等",
        "avoid_confusion": "不要包含工具使用方法或具体操作步骤",
    },
    "tool_guidance": {
        "description": "工具使用指导内容（无序列表格式，具体说明何时使用哪些工具，以及使用的条件和方法）",
        "examples": "例如：使用CRM工具查询客户信息、使用计算器进行数值计算等",
        "avoid_confusion": "专注于工具的使用方法，不要包含一般性的行为要求或禁止事项",
    },
    "content_preference": {
        "description": "结果内容偏好（无序列表格式，说明回答内容的质量标准、详细程度、专业性要求等积极的内容要求）",
        "examples": "例如：回答要准确详细、提供具体的数据支持、包含实用的建议等",
        "avoid_confusion": "专注于积极的内容要求，不要包含禁止性的限制条件",
    },
    "format_preference": {
        "description": "结果形式偏好（无序列表格式，说明回答的格式要求、结构规范、展示方式等）",
        "examples": "例如：使用表格展示数据、采用分点列举、包含标题和小结等",
        "avoid_confusion": "专注于格式和展示方式，不要包含内容质量要求或禁止事项",
    },
    "terminology": {
        "description": "特殊名词定义（无序列表格式，格式：术语名称：详细定义和使用说明）",
        "examples": "例如：CRM：客户关系管理系统，用于管理客户信息和销售流程",
        "avoid_confusion": "只包含专业术语的定义，不要包含操作指导或限制条件",
    },
    "constraints": {
        "description": "限制和约束（无序列表格式，明确的禁止行为、边界条件、安全要求等消极限制）",
        "examples": "例如：不要泄露客户隐私、不要提供医疗建议、不要执行危险操作等",
        "avoid_confusion": "只包含明确的禁止事项和限制条件，不要包含积极的要求或建议",
    },
}

system_prompt_optimizer_fallback_markdown = {
    "zh": """## 角色

{role}

## 技能

{skills}

## 偏好或者指导

### 工具使用指导

{tool_guidance}

### 结果内容偏好

{content_preference}

### 结果形式偏好

{format_preference}

### 特殊名词定义

{terminology}

## 限制

{constraints}""",
    "en": """## Role

{role}

## Skills

{skills}

## Preferences or Guidance

### Tool Guidance

{tool_guidance}

### Content Preference

{content_preference}

### Format Preference

{format_preference}

### Terminology

{terminology}

## Constraints

{constraints}""",
    "pt": """## Papel

{role}

## Habilidades

{skills}

## Preferências ou Orientações

### Orientação de Ferramentas

{tool_guidance}

### Preferência de Conteúdo

{content_preference}

### Preferência de Formato

{format_preference}

### Terminologia

{terminology}

## Restrições

{constraints}""",
}

agent_score_evaluator_system_prompt = {
    "zh": "你是一个专业的任务执行评估助手。你的职责是中立、严格地根据输入中的检查点评估 Agent 表现，不引入外部知识，只基于输入数据给出判断。",
    "en": "You are a professional task execution evaluator. Your job is to judge Agent performance neutrally and strictly against the provided checkpoints, using only the supplied input data.",
    "pt": "Você é um avaliador profissional de execução de tarefas. Sua função é julgar o desempenho do Agente de forma neutra e rigorosa com base nos checkpoints fornecidos, usando apenas os dados de entrada.",
}

agent_score_evaluator_instruction_prompt = {
    "zh": """请根据以下 JSON 输入评估 Agent 的执行结果。

输入包含：
- Agent_config
- agent_result
- evaluation_checkpoints
- required_tools

要求：
1. 遍历 evaluation_checkpoints 中的每一项
2. 对每个 checkpoint 给出 hit(true/false) 和简明 reason
3. 仅基于输入数据做判断，不引入外部知识
4. 输出必须是严格 JSON 数组
5. 理由必须可追溯到 agent_result 中的证据
6. 若输出格式有要求，只在结果中包含对应结构即可

输出格式：
[
  {
    "checkpoint_id": "CP1",
    "reason": "简明理由",
    "hit": true
  }
]""",
    "en": """Evaluate the Agent result using the JSON input below.

Input includes:
- Agent_config
- agent_result
- evaluation_checkpoints
- required_tools

Requirements:
1. Iterate over every item in evaluation_checkpoints
2. For each checkpoint, output hit (true/false) and a concise reason
3. Judge only from the provided input data; do not use external knowledge
4. Output must be a strict JSON array
5. Reasons must be traceable to evidence in agent_result
6. If a format is required, only ensure the corresponding structure is present

Output format:
[
  {
    "checkpoint_id": "CP1",
    "reason": "concise reason",
    "hit": true
  }
]""",
    "pt": """Avalie o resultado do Agente usando o JSON abaixo.

Entrada inclui:
- Agent_config
- agent_result
- evaluation_checkpoints
- required_tools

Requisitos:
1. Percorra cada item em evaluation_checkpoints
2. Para cada checkpoint, forneça hit (true/false) e um reason conciso
3. Julgue apenas com base nos dados fornecidos; não use conhecimento externo
4. A saída deve ser um array JSON estrito
5. Os motivos devem ser rastreáveis às evidências em agent_result
6. Se houver exigência de formato, basta garantir que a estrutura correspondente esteja presente

Formato de saída:
[
  {
    "checkpoint_id": "CP1",
    "reason": "motivo conciso",
    "hit": true
  }
]""",
}

checkpoint_generation_system_prompt = {
    "zh": """你是一个专业的智能 Agent 能力测评专家。你的任务是基于 Agent 配置、工具集和历史对话上下文，生成高精度、可验证、无幻觉的评估方案。宁可少，也不要错。""",
    "en": """You are a professional Agent capability evaluation expert. Your task is to generate a high-precision, verifiable, hallucination-free evaluation plan based on the Agent configuration, tool set, and conversation context. Prefer fewer checkpoints over wrong ones.""",
    "pt": """Você é um especialista profissional em avaliação de capacidades de Agentes. Sua tarefa é gerar um plano de avaliação de alta precisão, verificável e sem alucinações com base na configuração do Agente, conjunto de ferramentas e contexto da conversa. Prefira menos checkpoints a checkpoints incorretos.""",
}

checkpoint_generation_step1_prompt = {
    "zh": """请基于以下信息，分析历史对话上下文，并模拟理想 Agent 如何回答最新一轮用户提问：

【Agent 配置】
{agent_config}

【可用工具详情】
{tools_description}

【完整对话历史】
{user_messages}

【最新用户提问】
{latest_user_message}

请输出：
1. 历史上下文分析
2. 最新提问理解
3. 任务拆解逻辑
4. 所需工具及参数说明
5. 预期输出结果
6. 预期输出形式
7. 模拟执行过程

要求：只评估最新提问，优先复用历史数据，工具必须来自可用工具列表。""",
    "en": """Based on the information below, analyze the conversation context and simulate how an ideal Agent would answer the latest user question:

Agent config:
{agent_config}

Available tools:
{tools_description}

Full conversation history:
{user_messages}

Latest user question:
{latest_user_message}

Output:
1. History context analysis
2. Understanding of the latest question
3. Task decomposition logic
4. Required tools and parameter explanation
5. Expected output result
6. Expected output format
7. Simulated execution process

Requirement: evaluate only the latest question, prefer reusing history, and tools must come from the available tool list.""",
    "pt": """Com base nas informações abaixo, analise o contexto da conversa e simule como um Agente ideal responderia à última pergunta do usuário:

Configuração do Agente:
{agent_config}

Ferramentas disponíveis:
{tools_description}

Histórico completo da conversa:
{user_messages}

Última pergunta do usuário:
{latest_user_message}

Saída:
1. Análise do contexto histórico
2. Entendimento da última pergunta
3. Lógica de decomposição da tarefa
4. Ferramentas necessárias e explicação dos parâmetros
5. Resultado esperado
6. Formato de saída esperado
7. Processo de execução simulado

Requisito: avalie apenas a última pergunta, prefira reutilizar o histórico e as ferramentas devem vir da lista disponível.""",
}

checkpoint_generation_step2_prompt = {
    "zh": """根据上一步分析，构建用于评测实际 Agent 回答最新提问表现的结构化评分卡。只保留高置信检查点，严格避免模糊或可替代路径。

要求：
1. 仅保留确定性高的检查点
2. 禁止添加模糊依赖
3. 格式检查仅针对关键结论
4. 结论来源必须可追溯
5. 若历史数据可复用，不应要求重复调用工具
6. 检查点仅针对最新一轮用户提问的回答

输出：精简、保守、可验证的检查点列表。""",
    "en": """Based on the previous analysis, build a structured checklist to evaluate how the real Agent answers the latest question. Keep only high-confidence checkpoints and avoid ambiguous or replaceable paths.

Requirements:
1. Keep only deterministic checkpoints
2. Do not add fuzzy dependencies
3. Format checks only for key conclusions
4. Conclusion sources must be traceable
5. If history can be reused, do not require repeated tool calls
6. Checkpoints are only for the latest user question

Output: a concise, conservative, verifiable checklist.""",
    "pt": """Com base na análise anterior, construa uma checklist estruturada para avaliar como o Agente real responde à última pergunta. Mantenha apenas checkpoints de alta confiança e evite caminhos ambíguos ou substituíveis.

Requisitos:
1. Mantenha apenas checkpoints determinísticos
2. Não adicione dependências vagas
3. Verificações de formato apenas para conclusões-chave
4. As fontes das conclusões devem ser rastreáveis
5. Se o histórico puder ser reutilizado, não exija chamadas repetidas de ferramentas
6. Os checkpoints são apenas para a última pergunta do usuário

Saída: uma checklist concisa, conservadora e verificável.""",
}

checkpoint_generation_step3_prompt = {
    "zh": """请严格按照 JSON Schema 输出最终结果，不得添加注释、额外字段或解释性文字。

输出需要包含：
- evaluation_checkpoints
- difficulty_level
- required_tools

checkpoint_id 使用 CP1、CP2... 命名。""",
    "en": """Strictly output the final result according to the JSON Schema. Do not add comments, extra fields, or explanatory text.

Output must include:
- evaluation_checkpoints
- difficulty_level
- required_tools

Use CP1, CP2... naming for checkpoint_id.""",
    "pt": """Produza o resultado final estritamente de acordo com o JSON Schema. Não adicione comentários, campos extras ou texto explicativo.

A saída deve incluir:
- evaluation_checkpoints
- difficulty_level
- required_tools

Use CP1, CP2... para nomear checkpoint_id.""",
}

workflow_extractor_task_prompt = {
    "zh": """请分析以下 agent 对话记录，识别其中包含的主要任务。

对话记录：
{messages_text}

任务抽取要求：
{task_requirements}

要求：
1. 只提取一个主要任务
2. 任务名称按抽象程度输出
3. 返回 JSON：{"task": "任务名称"}""",
    "en": """Analyze the following agent conversation record and identify the main task.

Conversation:
{messages_text}

Task extraction requirements:
{task_requirements}

Requirements:
1. Extract only one main task
2. Output task name according to abstraction level
3. Return JSON: {"task": "task name"}""",
    "pt": """Analise o histórico de conversa do agente abaixo e identifique a tarefa principal.

Conversa:
{messages_text}

Requisitos de extração da tarefa:
{task_requirements}

Requisitos:
1. Extraia apenas uma tarefa principal
2. O nome da tarefa deve seguir o nível de abstração
3. Retorne JSON: {"task": "nome da tarefa"}""",
}

workflow_extractor_steps_prompt = {
    "zh": """请基于以下对话和任务提取工作流步骤。

任务：{task}
对话记录：
{messages_text}

抽象要求：
{abstraction_instruction}

真实工具列表：
{real_tools}

要求：
1. 基于真实工具调用生成步骤
2. 一个工具调用对应一个步骤
3. 返回 JSON：{"workflow_steps": ["步骤1", "步骤2"]}""",
    "en": """Extract workflow steps from the following conversation and task.

Task: {task}
Conversation:
{messages_text}

Abstraction instruction:
{abstraction_instruction}

Real tool list:
{real_tools}

Requirements:
1. Generate steps based on real tool calls
2. One tool call maps to one step
3. Return JSON: {"workflow_steps": ["step1", "step2"]}""",
    "pt": """Extraia as etapas do workflow com base na conversa e na tarefa abaixo.

Tarefa: {task}
Conversa:
{messages_text}

Instrução de abstração:
{abstraction_instruction}

Lista de ferramentas reais:
{real_tools}

Requisitos:
1. Gere etapas com base em chamadas reais de ferramentas
2. Uma chamada de ferramenta corresponde a uma etapa
3. Retorne JSON: {"workflow_steps": ["etapa1", "etapa2"]}""",
}

system_prompt_optimizer_analysis_prompt = {
    "zh": """请分析以下Agent系统指令的内容和结构，识别出其中包含的信息：

当前系统指令：
{prompt}
{optimization_guidance}
请从以下维度进行分析：
1. 角色定义：Agent扮演什么角色
2. 核心技能：Agent具备哪些能力
3. 工作偏好：Agent的工作方式和偏好
4. 工具使用：是否涉及工具使用指导
5. 输出要求：对结果内容和形式的要求
6. 限制条件：Agent需要遵守的限制
7. 特殊术语：是否有特定领域的术语定义
8. 语言问题：表达不清晰或可以改进的地方

请以JSON格式返回分析结果：
{
    "role_info": "角色相关信息",
    "skills_info": "技能相关信息",
    "preferences_info": "偏好相关信息",
    "tool_info": "工具使用相关信息",
    "output_requirements": "输出要求相关信息",
    "constraints_info": "限制条件相关信息",
    "terminology_info": "特殊术语相关信息",
    "language_issues": "语言表达问题和改进建议"
}""",
    "en": """Please analyze the content and structure of the following Agent system prompt and identify the information it contains:

Current system prompt:
{prompt}
{optimization_guidance}
Please analyze from the following dimensions:
1. Role definition: what role the Agent plays
2. Core skills: what capabilities the Agent has
3. Work preferences: the Agent's working style and preferences
4. Tool usage: whether there is tool usage guidance
5. Output requirements: requirements for the content and format of the result
6. Constraints: restrictions the Agent must follow
7. Special terminology: whether there are domain-specific term definitions
8. Language issues: unclear expressions or areas that can be improved

Please return the analysis result in JSON format:
{
    "role_info": "role-related information",
    "skills_info": "skills-related information",
    "preferences_info": "preference-related information",
    "tool_info": "tool usage-related information",
    "output_requirements": "output requirement-related information",
    "constraints_info": "constraint-related information",
    "terminology_info": "special terminology-related information",
    "language_issues": "language expression issues and improvement suggestions"
}""",
    "pt": """Por favor, analise o conteúdo e a estrutura do seguinte prompt de sistema do Agente e identifique as informações que ele contém:

Prompt de sistema atual:
{prompt}
{optimization_guidance}
Analise a partir das seguintes dimensões:
1. Definição de papel: qual papel o Agente desempenha
2. Habilidades principais: quais capacidades o Agente possui
3. Preferências de trabalho: estilo de trabalho e preferências do Agente
4. Uso de ferramentas: se há orientação de uso de ferramentas
5. Requisitos de saída: requisitos para o conteúdo e formato do resultado
6. Restrições: restrições que o Agente deve seguir
7. Terminologia especial: se há definições de termos específicos de domínio
8. Problemas de linguagem: expressões pouco claras ou áreas que podem ser melhoradas

Por favor, retorne o resultado da análise em formato JSON:
{
    "role_info": "informações relacionadas ao papel",
    "skills_info": "informações relacionadas às habilidades",
    "preferences_info": "informações relacionadas às preferências",
    "tool_info": "informações relacionadas ao uso de ferramentas",
    "output_requirements": "informações relacionadas aos requisitos de saída",
    "constraints_info": "informações relacionadas às restrições",
    "terminology_info": "informações relacionadas à terminologia especial",
    "language_issues": "problemas de expressão e sugestões de melhoria"
}""",
}

system_prompt_optimizer_sections_prompt = {
    "zh": """请对以下原始指令进行结构化整理，只能重新组织和改善表述，绝对不能添加任何新内容。

原始指令：
{original_prompt}

分析结果：
{analysis_json}
{optimization_guidance}

严格要求：
1. 只能重新组织原有内容，不得添加任何原始指令中没有明确提到的信息
2. 禁止编造任何内容，包括新的功能、限制、术语、数字、时间限制等
3. 完全保留原始细节，所有具体的名词、数字、规则必须原样保留
4. 不得扩展或推理，不能基于原始内容进行任何推理或扩展

处理规则：
- 如果原始指令中没有某个部分的内容，该部分应该为空或简短
- 只能改善语言表述的清晰度，不能改变含义
- 不能添加任何示例、解释或补充说明
- 不能添加任何原始指令中没有的专业术语或概念

请严格按照原始指令内容整理各个部分：
1. 角色部分：仅重新表述原始指令中的角色描述
2. 技能部分：仅列出原始指令中明确提到的技能（如果没有则简短）
3. 工具使用指导：仅包含原始指令中的工具使用要求（如果没有则为空）
4. 结果内容偏好：仅包含原始指令中的内容要求（如果没有则为空）
5. 结果形式偏好：仅包含原始指令中的格式要求（如果没有则为空）
6. 特殊名词定义：仅包含原始指令中已定义的术语（如果没有则为空）
7. 限制部分：仅包含原始指令中的限制和禁止事项（如果没有则为空）

请以JSON格式返回：
{
    "role": "角色部分内容（仅基于原始指令）",
    "skills": "技能部分内容（仅原始指令中的技能）",
    "tool_guidance": "工具使用指导内容（仅原始指令中的指导，没有则为空）",
    "content_preference": "结果内容偏好内容（仅原始指令中的偏好，没有则为空）",
    "format_preference": "结果形式偏好内容（仅原始指令中的格式要求，没有则为空）",
    "terminology": "特殊名词定义内容（仅原始指令中的定义，没有则为空）",
    "constraints": "限制部分内容（仅原始指令中的限制，没有则为空）"
}""",
    "en": """Please structure the following original instruction, only reorganizing and improving the wording, and absolutely do not add any new content.

Original instruction:
{original_prompt}

Analysis result:
{analysis_json}
{optimization_guidance}

Strict requirements:
1. Only reorganize the original content; do not add any information that is not explicitly mentioned in the original instruction
2. Do not fabricate anything, including new functions, constraints, terms, numbers, or time limits
3. Fully preserve original details; all specific nouns, numbers, and rules must remain unchanged
4. Do not expand or infer; do not perform any reasoning or extension based on the original content

Processing rules:
- If the original instruction has no content for a section, that section should be empty or brief
- Only improve clarity of wording; do not change the meaning
- Do not add examples, explanations, or supplementary notes
- Do not add professional terms or concepts that do not exist in the original instruction

Please strictly organize each section according to the original instruction:
1. Role section: only restate the role description from the original instruction
2. Skills section: only list the skills explicitly mentioned in the original instruction (brief if none)
3. Tool guidance: only include tool usage requirements from the original instruction (empty if none)
4. Content preference: only include content requirements from the original instruction (empty if none)
5. Format preference: only include formatting requirements from the original instruction (empty if none)
6. Terminology: only include terms defined in the original instruction (empty if none)
7. Constraints: only include constraints and prohibitions from the original instruction (empty if none)

Please return in JSON format:
{
    "role": "role section content (based only on the original instruction)",
    "skills": "skills section content (only the skills from the original instruction)",
    "tool_guidance": "tool guidance content (only the guidance from the original instruction, empty if none)",
    "content_preference": "content preference content (only the preference from the original instruction, empty if none)",
    "format_preference": "format preference content (only the format requirements from the original instruction, empty if none)",
    "terminology": "terminology content (only the definitions from the original instruction, empty if none)",
    "constraints": "constraints content (only the constraints from the original instruction, empty if none)"
}""",
    "pt": """Por favor, estruture a seguinte instrução original, apenas reorganizando e melhorando a redação, e absolutamente não adicione nenhum conteúdo novo.

Instrução original:
{original_prompt}

Resultado da análise:
{analysis_json}
{optimization_guidance}

Requisitos rigorosos:
1. Apenas reorganize o conteúdo original; não adicione nenhuma informação que não esteja explicitamente mencionada na instrução original
2. Não fabrique nada, incluindo novas funções, restrições, termos, números ou limites de tempo
3. Preserve totalmente os detalhes originais; todos os substantivos, números e regras específicos devem permanecer inalterados
4. Não expanda nem infira; não faça nenhum raciocínio ou extensão com base no conteúdo original

Regras de processamento:
- Se a instrução original não tiver conteúdo para uma seção, essa seção deve ficar vazia ou curta
- Apenas melhore a clareza da redação; não altere o significado
- Não adicione exemplos, explicações ou observações suplementares
- Não adicione termos profissionais ou conceitos que não existam na instrução original

Por favor, organize estritamente cada seção de acordo com a instrução original:
1. Seção de papel: apenas reescreva a descrição do papel da instrução original
2. Seção de habilidades: apenas liste as habilidades explicitamente mencionadas na instrução original (breve se não houver)
3. Orientação de ferramentas: apenas inclua os requisitos de uso de ferramentas da instrução original (vazio se não houver)
4. Preferência de conteúdo: apenas inclua os requisitos de conteúdo da instrução original (vazio se não houver)
5. Preferência de formato: apenas inclua os requisitos de formatação da instrução original (vazio se não houver)
6. Terminologia: apenas inclua os termos definidos na instrução original (vazio se não houver)
7. Restrições: apenas inclua restrições e proibições da instrução original (vazio se não houver)

Por favor, retorne em formato JSON:
{
    "role": "conteúdo da seção de papel (baseado apenas na instrução original)",
    "skills": "conteúdo da seção de habilidades (somente as habilidades da instrução original)",
    "tool_guidance": "conteúdo de orientação de ferramentas (somente a orientação da instrução original, vazio se não houver)",
    "content_preference": "conteúdo de preferência de conteúdo (somente a preferência da instrução original, vazio se não houver)",
    "format_preference": "conteúdo de preferência de formato (somente os requisitos de formato da instrução original, vazio se não houver)",
    "terminology": "conteúdo de terminologia (somente as definições da instrução original, vazio se não houver)",
    "constraints": "conteúdo de restrições (somente as restrições da instrução original, vazio se não houver)"
}""",
}

system_prompt_optimizer_section_prompt = {
    "zh": """请从原始系统指令中提取并优化"{section_key}"部分的内容。

原始系统指令：
{original_prompt}

{optimization_goal_block}

当前部分定义：
{section_description}

内容示例：
{section_examples}

避免混淆：
{section_avoid_confusion}

{context_info}

优化要求：
1. 内容忠实性：只能使用原始指令中已有的信息，不能添加新的功能、限制或概念
2. 语言优化：可以改善表述方式，使语言更清晰、更专业、更有条理
3. 结构优化：可以重新组织内容结构，使逻辑更清晰
4. 保留细节：所有具体的名词、数字、规则必须原样保留
5. 职责分离：严格按照当前部分的定义提取内容，不要包含其他部分的内容

允许的优化：
- 改善语言表述的清晰度和专业性
- 调整句式结构，使表达更流畅
- 重新组织内容顺序，使逻辑更清晰
- 统一术语使用，保持一致性
- 优化格式，使内容更易读

严格禁止：
- 添加原始指令中没有的新信息
- 编造具体的数字、名称或规则
- 添加新的功能要求或限制条件
- 推理或扩展原始内容的含义
- 包含其他部分应该包含的内容

特别注意：
- 如果原始指令中没有明确的"{section_key}"相关内容，请返回"无"
- 不要将其他部分的内容错误归类到当前部分
- 严格按照部分定义的职责范围提取内容

重要输出要求：
- 直接输出优化后的内容，不要添加任何说明文字
- 不要包含"以下是优化后的..."、"内容如下："等描述性前缀
- 不要包装在JSON对象中
- 不要添加任何解释或说明
- 只输出纯粹的内容本身

示例：
错误输出：以下是优化后的"{section_key}"内容：
- **具体内容**

正确输出：
- **具体内容**""",
    "en": """Please extract and optimize the content of the "{section_key}" section from the original system prompt.

Original system prompt:
{original_prompt}

{optimization_goal_block}

Current section definition:
{section_description}

Content examples:
{section_examples}

Avoid confusion:
{section_avoid_confusion}

{context_info}

Optimization requirements:
1. Content fidelity: only use information already present in the original instruction; do not add new functions, constraints, or concepts
2. Language improvement: wording may be improved to be clearer, more professional, and more structured
3. Structural improvement: the content structure may be reorganized for clearer logic
4. Preserve details: all specific nouns, numbers, and rules must remain unchanged
5. Separation of responsibilities: strictly extract content according to the definition of the current section and do not include content from other sections

Allowed improvements:
- Improve clarity and professionalism of the wording
- Adjust sentence structure to make the expression smoother
- Reorganize content order to make logic clearer
- Unify terminology usage and keep consistency
- Improve formatting to make content easier to read

Strictly forbidden:
- Adding new information not present in the original instruction
- Fabricating specific numbers, names, or rules
- Adding new functional requirements or constraints
- Reasoning about or extending the meaning of the original content
- Including content that should belong to other sections

Special notes:
- If the original instruction does not clearly contain content related to "{section_key}", return "none"
- Do not misclassify content from other sections into the current section
- Strictly extract content within the responsibility scope of the section definition

Important output requirements:
- Output only the optimized content directly, without any explanatory text
- Do not include prefixes such as "Here is the optimized..." or "Content:"
- Do not wrap it in a JSON object
- Do not add any explanations
- Output only the content itself

Example:
Wrong output: Here is the optimized "{section_key}" content:
- **Specific content**

Correct output:
- **Specific content**""",
    "pt": """Por favor, extraia e otimize o conteúdo da seção "{section_key}" do prompt de sistema original.

Prompt de sistema original:
{original_prompt}

{optimization_goal_block}

Definição da seção atual:
{section_description}

Exemplos de conteúdo:
{section_examples}

Evitar confusão:
{section_avoid_confusion}

{context_info}

Requisitos de otimização:
1. Fidelidade ao conteúdo: use apenas informações já presentes na instrução original; não adicione novas funções, restrições ou conceitos
2. Melhoria de linguagem: a redação pode ser melhorada para ficar mais clara, profissional e estruturada
3. Melhoria estrutural: a estrutura do conteúdo pode ser reorganizada para uma lógica mais clara
4. Preservar detalhes: todos os substantivos, números e regras específicos devem permanecer inalterados
5. Separação de responsabilidades: extraia estritamente o conteúdo de acordo com a definição da seção atual e não inclua conteúdo de outras seções

Melhorias permitidas:
- Melhorar a clareza e o profissionalismo da redação
- Ajustar a estrutura das frases para tornar a expressão mais fluida
- Reorganizar a ordem do conteúdo para deixar a lógica mais clara
- Unificar o uso da terminologia e manter a consistência
- Melhorar a formatação para facilitar a leitura

Estritamente proibido:
- Adicionar novas informações não presentes na instrução original
- Fabricar números, nomes ou regras específicos
- Adicionar novos requisitos funcionais ou restrições
- Raciocinar sobre ou expandir o significado do conteúdo original
- Incluir conteúdo que deveria pertencer a outras seções

Observações especiais:
- Se a instrução original não contiver claramente conteúdo relacionado a "{section_key}", retorne "none"
- Não classifique incorretamente conteúdo de outras seções na seção atual
- Extraia estritamente o conteúdo dentro do escopo de responsabilidade da definição da seção

Requisitos importantes de saída:
- Produza apenas o conteúdo otimizado diretamente, sem qualquer texto explicativo
- Não inclua prefixos como "Aqui está o conteúdo otimizado..." ou "Conteúdo:"
- Não envolva em um objeto JSON
- Não adicione explicações
- Produza apenas o próprio conteúdo

Exemplo:
Saída errada: Aqui está o conteúdo otimizado da seção "{section_key}":
- **Conteúdo específico**

Saída correta:
- **Conteúdo específico**""",
}

user_input_optimizer_prompt = {
    "zh": """你是一个“用户意图整理与任务成型助手”。

你的任务不是简单润色，而是基于最近对话上下文，准确理解用户真正想让 agent 做什么，并将当前输入整理成一个更完整、更明确、更可执行的正式请求。

你的输出应当帮助后续 agent 立即进入执行，而不是还需要再次猜测用户意图。

请遵守以下规则：
1. 严格保留用户原始意图，不要杜撰用户没有表达过的新需求。
2. 如果上下文已经明确了对象、文件、代码位置、目标、限制条件、偏好、验收标准、输出形式，请自然补全到请求里。
3. 如果用户表达模糊，你可以根据上下文把隐含意图说清楚，但只能做高置信度补全，不能擅自扩展任务范围。
4. 让请求尽量包含这些关键信息中的已知部分：
   - 要做什么
   - 为什么做 / 目标是什么
   - 作用对象是什么（文件、模块、页面、功能、数据、环境等）
   - 约束或注意事项是什么
   - 用户期望最终输出什么结果
5. 如果用户其实是在请求 agent 继续上一个任务、修复某个问题、补齐某项实现、调整某个行为，要把这种“后续动作意图”明确表达出来。
6. 如果用户已经说得很清楚，只做轻微增强，让表达更完整、更利于执行。
7. 保持用户原本使用的语言和语气，不要切换语言。
8. 不要输出解释、分析过程、前言、标题、项目符号或备注。
9. 只输出一段可直接发送给 agent 的“优化后用户请求正文”。

最近对话上下文：
{history_text}

当前用户输入：
{current_input}""",
    "en": """You are a "user intent organization and task shaping assistant".

Your task is not simple polishing. Based on the recent conversation context, accurately understand what the user really wants the agent to do, and turn the current input into a more complete, clearer, and more executable formal request.

Your output should help the downstream agent begin execution immediately instead of having to guess the user's intent again.

Follow these rules:
1. Strictly preserve the user's original intent and do not invent new needs the user never expressed.
2. If the context already makes the object, file, code location, goal, constraints, preferences, acceptance criteria, or output format clear, naturally fill them into the request.
3. If the user is vague, you may clarify the implied intent based on context, but only with high confidence and without expanding the task scope.
4. Try to include the known parts of these key items:
   - What to do
   - Why / the goal
   - What it affects (files, modules, pages, features, data, environment, etc.)
   - Constraints or notes
   - What final result the user expects
5. If the user is actually asking the agent to continue a previous task, fix something, complete an implementation, or adjust behavior, explicitly express that continuation intent.
6. If the user is already clear, only make light enhancements so the request is more complete and more executable.
7. Keep the user's original language and tone; do not switch languages.
8. Do not output explanations, analysis, prefaces, headings, bullets, or remarks.
9. Output only one block of "optimized user request body" that can be sent directly to the agent.

Recent conversation context:
{history_text}

Current user input:
{current_input}""",
    "pt": """Você é um "assistente de organização da intenção do usuário e estruturação da tarefa".

Sua tarefa não é uma simples revisão. Com base no contexto recente da conversa, entenda com precisão o que o usuário realmente quer que o agente faça e transforme a entrada atual em uma solicitação formal mais completa, clara e executável.

Sua saída deve ajudar o agente subsequente a iniciar a execução imediatamente, sem precisar adivinhar novamente a intenção do usuário.

Siga estas regras:
1. Preserve estritamente a intenção original do usuário e não invente novas necessidades que o usuário nunca expressou.
2. Se o contexto já deixar claro o objeto, arquivo, localização do código, objetivo, restrições, preferências, critérios de aceitação ou formato de saída, preencha-os naturalmente na solicitação.
3. Se o usuário estiver vago, você pode esclarecer a intenção implícita com base no contexto, mas apenas com alta confiança e sem expandir o escopo da tarefa.
4. Tente incluir as partes conhecidas destes itens-chave:
   - O que fazer
   - Por que / qual é o objetivo
   - O que será afetado (arquivos, módulos, páginas, funcionalidades, dados, ambiente etc.)
   - Restrições ou observações
   - Qual resultado final o usuário espera
5. Se o usuário estiver realmente pedindo ao agente para continuar uma tarefa anterior, corrigir algo, completar uma implementação ou ajustar um comportamento, expresse explicitamente essa intenção de continuidade.
6. Se o usuário já estiver claro, faça apenas melhorias leves para que a solicitação fique mais completa e mais executável.
7. Mantenha o idioma e o tom originais do usuário; não troque de idioma.
8. Não produza explicações, análises, prefácios, títulos, marcadores ou observações.
9. Produza apenas um bloco de "corpo da solicitação otimizada do usuário" que possa ser enviado diretamente ao agente.

Contexto recente da conversa:
{history_text}

Entrada atual do usuário:
{current_input}""",
}

agent_abilities_user_prompt = {
    "zh": """你是一个「Agent 能力卡片」生成助手。

请根据以下信息，生成该 Agent 在界面里展示的能力卡片：每张卡片对应一项用户可一键发起的真实任务（用户点击卡片后，会把其中一段文字直接填入聊天输入框发送给 Agent）。

数量：**必须恰好 {abilities_count} 条**；`items` 数组长度必须等于 {abilities_count}，不得多也不得少。

Agent 语言：{language}
Agent 名称：{agent_name}
Agent 描述：{agent_description}

可用工具：
{tools_line}

可用技能：
{skills_line}

可用工作流：
{workflows_line}

上下文信息：
{context_summary}

字段含义与约束：
1. 能力项须与上述工具/技能/工作流一致，真实可执行；勿夸大或编造。
2. id：kebab-case，稳定且在列表内唯一。
3. title：卡片上的短标题（几个词），概括「做什么」。
4. description：1～2 句，仅用于卡片展示——写「价值 + 适用场景」，可用第二人称「帮你…」；**不要**写成输入框要发的全文。**必须与 promptText 明显不同**：不得共用同一段长句或仅换说法复述；promptText **禁止**照抄、扩写 description 的主干。
5. promptText：**必须**是终端用户口吻的**一整段可直接发送**的自然语言（可用「请…」「帮我…」或直述任务）。除下列约束外，单独发送即可让 Agent 有明确下一步。
   - **可执行 / 不悬空指代**：默认用户**只发这一条**、且未在界面里额外选文件。涉及具体文件/表格时，须写清如何取得（上传、粘贴路径、工作区路径，或「若本会话里已有打开文件则用之，否则提示我上传」等**可操作**说法）。禁止单独使用「这个/该」文件却无来源。
   - **一键开局（预设能力）**：这是「点一下就把全文发出去」的场景；应让 Agent **带合理默认立刻开工**（如调研默认可用公开资料、通用时间口径；具体默认值可写进一句内）。**禁止**以「请先向我确认主题/范围/地区/时段…再开始」「若需要我补充…请先问我」等**把球踢回用户**为主收尾；**禁止**半句主要篇幅用来索要用户先答填空。确需信息时，用**句内默认**（如「先按××领域做桌面调研」）或允许执行中再简短追问，勿把「先确认」当成第一步。
   - **单一主线**：一个清晰目标；避免无数据出处的并列清单。多产出用一句可执行流程串联。
   - **具体性硬性清单**：promptText 必须像一份「现成订单」，**至少**包含下列 4 类槽位，且**全部以具体名词出现**（不是空类别、不是「某个/特定」等占位词）：
       (a) **对象**——具体的网址（含 https://…、或站点名 + 关键路径）/ 文件名 + 后缀（如 `Q3-销售.xlsx`）/ 行业 + 细分赛道 + 公司名 / 收件人或邮件主题片段，等等；
       (b) **范围与口径**——版本/页面/工作表/字段/账号；时间窗口写出**具体年份、季度或月份**（如「2024 全年」「近 90 天」），不要只写「最近」；地域写出**国家/省份/城市**；
       (c) **要执行的动作链**——3～6 个明确动词步骤（打开 → 登录 → 提取 → 比对 → 汇总 → 反馈），步骤之间不留空白等待；
       (d) **交付物形态**——例如「输出 Markdown 表格，列：A/B/C」「写 200 字结论 + 3 条行动建议」「Top-10 异常行 + 原因猜测」「中文回复邮件草稿，不超过 150 字」。
     若 Agent 描述/工具/上下文已暗示了真实对象（账号、网址、文件、领域），**必须**写入；否则你**必须**直接编出一个**与能力一致、合理且足够具体**的默认例题（如「打开 https://www.bilibili.com/ 搜索『AI 数字人』并抓取首屏前 10 条视频的标题/UP 主/播放量到 Markdown 表」），不要把决定权交回用户。
   - **禁忌写法**（出现任一即视为不合格，需要换写法）：
       · 「围绕一个我接下来/稍后会提供的主题」「某个目标网站」「目标文件」「相关数据」「关键信息」作为主语；
       · 通篇只有方法论（「先梳理框架，再整理结论…」）而不点名做什么；
       · 「请先与我确认/补充范围、地区、时段、目标网址、文件…再开始」当主收尾；
       · 与 title/description 高度同义复述、缺槽位 (a)(b)(c)(d) 任何一项。
   - **长度**：80～180 个汉字（中文）或 60～140 词（英/葡），力求紧凑、信息密度高，**不要**铺垫客套。
   - 不得只是功能名、标签；不得出现「生成能力列表」「你是助手」等元指令。
6. title、description、promptText 均使用与 Agent 语言一致。
7. 仅输出一个 JSON 对象：顶层只含键 items，其值长度恰好为 {abilities_count} 的对象数组；每项含 id、title、description、promptText。不要使用 Markdown 代码围栏，不要输出解释或其它文字。""",
    "en": """You generate "Agent ability cards" for a product UI.

From the information below, produce ability cards this Agent can show in the app. Each card is one real task a user can start with one click (the user sends one field’s text straight into the chat input).

Count: output **exactly** {abilities_count} cards — the `items` array length must be {abilities_count}, neither more nor fewer.

Agent language: {language}
Agent name: {agent_name}
Agent description: {agent_description}

Available tools:
{tools_line}

Available skills:
{skills_line}

Available workflows:
{workflows_line}

Context:
{context_summary}

Field meanings and rules:
1. Items must match the tools/skills/workflows above and be honestly executable; do not invent.
2. id: kebab-case, stable and unique within the list.
3. title: short headline for the card (a few words) — what the user gets done.
4. description: one or two sentences **only for the card** — value + when to use it; may use "we help you ...". **Must differ clearly from promptText**: not the same paragraph rephrased; promptText must not expand description verbatim.
5. promptText: **must** be one ready-to-send user message (imperative or "Please ..."). The Agent must get a **clear next step** from this alone, plus the rules below.
   - **Actionable / no dangling references**: User sends **only** this line and has **not** picked a file. For spreadsheets, say how data is obtained (upload, path, workspace, or "use an open file in this session if any, else tell me to upload") — never bare "this file" with no source.
   - **One-shot preset**: This text is pasted and sent in one click; the Agent should **start immediately** with sensible defaults (e.g. research from public sources; state defaults in the message if needed). **Do not** end by demanding the user **first** confirm scope/topic/region/timeframe, or "ask me before you start", or "if you need X from me, check with me first" as the main clause. Do not make "please confirm with me" the first step. Prefer in-message defaults ("start with an overview of …") or brief follow-up only if blocked mid-run.
   - **Single through-line**: one goal; avoid unfocused comma lists; chain outputs in one fluent instruction.
   - **Specificity checklist (mandatory)**: promptText must read like a finished work order and contain **at least all four** slots, each filled with concrete nouns (no placeholders like "a topic / some site / the relevant data"):
       (a) **Object** — explicit URL (include `https://…` or site + path), filename + extension (e.g. `Q3-sales.xlsx`), industry + sub-market + named company, recipient or mail subject snippet, etc.;
       (b) **Scope / qualifiers** — version, page, sheet, field, account; time window with **named year/quarter/month** (e.g. "2024 full year", "last 90 days") not just "recent"; region as **country/province/city**;
       (c) **Action chain** — 3–6 concrete verbs in order (open → log in → extract → compare → summarize → reply), no gaps that wait for the user;
       (d) **Deliverable shape** — e.g. "Markdown table, columns A/B/C", "200-word conclusion + 3 actions", "top-10 anomalous rows with likely causes", "draft Chinese reply email under 150 chars".
     If the Agent description / tools / context imply a real object (account, URL, file, domain), **use it**. Otherwise you **must** invent a plausible, concrete default order yourself (e.g. "Open https://www.bilibili.com/ , search 『AI 数字人』, extract title/uploader/views of the top 10 results into a Markdown table"). Do not bounce the decision back to the user.
   - **Forbidden patterns** (any of these makes the item invalid — rewrite):
       · "around a topic I will provide later", "the target site", "the target file", "the relevant data", "key information" used as the subject;
       · methodology-only text ("first build a framework, then summarize…") without naming what is analyzed;
       · ending with "please confirm with me the scope / region / period / target URL / file before starting" as the main clause;
       · near-paraphrase of title/description, or missing any of slots (a)(b)(c)(d).
   - **Length**: 60–140 words (English / Portuguese), 80–180 Chinese characters; dense and direct, no pleasantries.
   - No bare labels; no meta chat about cards or the assistant.
6. title, description, and promptText must follow the Agent language.
7. Output one JSON object only: top-level key `items` whose value is an array of **exactly** {abilities_count} objects, each with keys id, title, description, promptText. No markdown fences, no prose before or after.""",
    "pt": """Você gera "cartões de capacidade" do Agent para a interface.

Com as informações abaixo, produza cartões que o Agent possa exibir: cada cartão é uma tarefa real que o usuário inicia com um clique (um campo vira o texto enviado no chat).

Quantidade: gere **exatamente** {abilities_count} cartões — o array `items` deve ter comprimento {abilities_count}, nem mais nem menos.

Idioma do Agent: {language}
Nome do Agent: {agent_name}
Descrição do Agent: {agent_description}

Ferramentas disponíveis:
{tools_line}

Habilidades disponíveis:
{skills_line}

Fluxos de trabalho disponíveis:
{workflows_line}

Contexto:
{context_summary}

Significado dos campos e regras:
1. Itens devem ser coerentes com ferramentas/habilidades/fluxos acima e executáveis; não invente.
2. id: kebab-case, estável e único na lista.
3. title: título curto no cartão (poucas palavras) — o que o usuário faz.
4. description: uma ou duas frases **só no cartão** — valor + quando usar; **deve** ser claramente diferente do promptText (não o mesmo parágrafo reescrito).
5. promptText: **deve** ser uma única mensagem pronta para enviar (imperativo ou "Por favor ..."). O Agent precisa de um **próximo passo claro** só com ela.
   - **Executável / sem referências vagas**: o usuário envia **só** essa linha e não escolheu arquivo. Para planilhas: diga como obter dados (upload, caminho, workspace, ou arquivo já aberto na sessão); nunca "este arquivo" sem fonte.
   - **Preset de um clique**: o Agent deve **começar na hora** com padrões razoáveis (pesquisa com fontes públicas; defaults podem ir na própria frase). **Proibido** terminar exigindo que o usuário **primeiro** confirme escopo/tema/região/prazo, ou "pergunte-me antes de começar" como ideia principal. Prefira defaults na mensagem ou pergunta curta só se travar no meio.
   - **Um fio condutor**: um objetivo; evite listas soltas; encadeie numa frase fluente.
   - **Checklist de especificidade (obrigatório)**: promptText deve parecer uma ordem pronta com **as quatro** lacunas preenchidas com substantivos concretos (nada de "um tema/algum site/os dados relevantes"):
       (a) **Objeto** — URL explícita (com `https://…` ou site + caminho), nome de arquivo + extensão (ex.: `Q3-vendas.xlsx`), setor + submercado + empresa nomeada, destinatário ou assunto de e-mail;
       (b) **Escopo/qualificadores** — versão, página, planilha, campo, conta; janela temporal com **ano/trimestre/mês explícito** (ex.: "2024 completo", "últimos 90 dias"); região como **país/estado/cidade**;
       (c) **Cadeia de ações** — 3 a 6 verbos em ordem (abrir → entrar → extrair → comparar → resumir → responder), sem buracos que esperam o usuário;
       (d) **Forma da entrega** — ex.: "tabela Markdown com colunas A/B/C", "conclusão de 200 palavras + 3 ações", "top-10 linhas anômalas com causa provável", "rascunho de e-mail em chinês até 150 caracteres".
     Se a descrição/ferramentas/contexto do Agent sugerirem objeto real (conta, URL, arquivo, domínio), **use-o**. Senão **invente** uma ordem plausível e concreta você mesmo (ex.: "Abra https://www.bilibili.com/ , pesquise 『AI 数字人』 e extraia título/UP/visualizações dos 10 primeiros vídeos para uma tabela Markdown"). Não devolva a decisão ao usuário.
   - **Padrões proibidos** (qualquer um invalida — reescreva):
       · "em torno de um tema que vou fornecer", "o site alvo", "o arquivo alvo", "os dados relevantes" como sujeito principal;
       · só metodologia ("primeiro estruture um quadro, depois resuma…") sem nomear o que analisar;
       · terminar com "antes de começar, confirme comigo escopo/região/período/URL/arquivo" como cláusula principal;
       · paráfrase próxima de title/description, ou falta de qualquer lacuna (a)(b)(c)(d).
   - **Tamanho**: 60–140 palavras; denso e direto, sem cortesias.
   - Sem rótulos; sem meta-instruções.
6. title, description e promptText no idioma do Agent.
7. Saída: apenas um objeto JSON com a chave de topo `items` contendo **exatamente** {abilities_count} objetos (cada um com id, title, description, promptText). Sem cercas markdown, sem texto extra.""",
}
