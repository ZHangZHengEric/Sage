import json
from string import Template

from .base_agent_processor import BaseAgentProcessor
from ..logger import logger
from sagents.utils.prompt_manager import PromptManager

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
        language: str = "en",
    ) -> str:
        system_prompt = PromptManager().get_prompt(
            "agent_score_evaluator_system_prompt",
            agent="common_util",
            language=language,
        )
        instruction_prompt = PromptManager().get_prompt(
            "agent_score_evaluator_instruction_prompt",
            agent="common_util",
            language=language,
        )

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






