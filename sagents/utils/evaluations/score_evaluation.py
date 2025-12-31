import json
from string import Template

from .base_agent_processor import BaseAgentProcessor
from ..logger import logger

class AgentScoreEvaluator(BaseAgentProcessor):
    def __init__(
        self,
        api_key: str,
        base_url: str,
    ):
        super().__init__(api_key, base_url)

    async def evaluate(
        self,
        agent_result: str,
        agent_config: str,
        checkpoint: str,
        model_name: str,
    ) -> str:
        system_prompt = """
  你是一个专业的任务执行评估助手，负责对 Agent 在处理用户查询时的表现进行客观、细致的评估。你的任务是根据提供的用户问题、Agent 的执行过程与结果、以及预设的评估检查点（evaluation_checkpoints），逐项判断 Agent 是否正确完成了每个关键步骤。

  你需要：
  - 严格依据 `evaluation_checkpoints` 中列出的 `hit_point` 和 `judgement_standard` 进行判断；
  - 每个检查点独立判断，输出“是”或“否”；
  - 提供简明、准确的理由说明判断依据；
  - 不引入外部知识，仅基于输入数据进行分析；
  - 输出格式必须结构化，便于程序解析。

  请保持中立、严谨、不推测，只根据已有信息做出逻辑判断。
        """
        instruction_prompt = """
  请根据以下 JSON 格式输入的内容，对 Agent 的执行结果进行评估：

  输入包含：
  - `Agent_config`: Agent配置，包含system，调用工具范围，设置固定要求，工作流等信息；
  - `agent_result`: Agent 执行后的结果，包括其思考过程、工具调用记录及最终回复；
  - `evaluation_checkpoints`: 一系列评估检查点（CP1, CP2, ...），每个包含：
    - `checkpoint_id`: 检查点编号；
    - `hit_point`: 需要命中的行为或能力；
    - `judgement_standard`: 判断该行为是否达成的标准；
  - `required_tools`: 必须使用的工具列表（用于辅助验证）。

  你的任务是：
  1. 遍历 `evaluation_checkpoints` 中的每一项；
  2. 对每个 `hit_point`，结合 `judgement_standard` 分析 `agent_result` 的内容；
  3. 判断 Agent 是否成功命中该点，回答“是”或“否”；
  4. 给出判断理由，引用 `agent_result` 中的具体证据（如工具调用、参数、返回值等）；
  5. 最终输出一个结构化的评估结果数组。

  输出格式如下（严格使用 JSON）：

  [
    {
      "checkpoint_id": "CP1",
      "reason": "检测到 search_customers_with_filters_on_salesmate 被调用且返回客户列表，证据为....",
      "hit": true | false,
    },
    ...
  ]

  注意：
  - 所有布尔值使用 `true` / `false`（小写）；
  - 理由必须具体、准确，直接引用 `agent_result` 中的内容作为证据；
  - 如果工具未调用、参数错误或结果未正确使用，则视为未命中；
  - 对于时间范围、客户 ID 提取、信息格式等细节，需精确匹配标准；
  - 如果工具首次未调用成功，但后续重新调用成功，则视为命中；
  - 若有输出格式相关的checkpoint，例如以表格形式呈现，则仅需输出结果中包含表格及字段即可，为包含关系，不需要完全匹配。

  我的输入：

  【Agent_config】:
  ${agent_config}

  【agent_result】:
  ${agent_result}

  【evaluation_information】：
  ${checkpoint}
        """

        template = Template(instruction_prompt)
        instruction_prompt = template.substitute(
            agent_config=agent_config,
            agent_result=agent_result,
            checkpoint=checkpoint
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": instruction_prompt}
        ]

        response = await self.call_qianxun(messages, model_name=model_name)
        parsed_response = self.parse_json_response(response)
        
        final_result_str = ""
        if isinstance(parsed_response, (dict, list)):
            final_response = {"evaluation_result": parsed_response}
            final_result_str = json.dumps(final_response, ensure_ascii=False)
        elif isinstance(parsed_response, str):
            final_result_str = parsed_response
        else:
            final_result_str = str(parsed_response)
            
        logger.info("evaluation response: " + final_result_str)
        return final_result_str









