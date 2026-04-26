import json
from typing import List, Dict, Any

from .base_agent_processor import BaseAgentProcessor
from ..logger import logger
from sagents.utils.prompt_manager import PromptManager

class CheckpointGenerationAgent(BaseAgentProcessor):
    def __init__(
        self,
        api_key: str,
        base_url: str,
    ):
        super().__init__(api_key, base_url)     

    async def task_generation(self, prompt: str, messages: List[Dict[str, Any]], model_name: str):
        messages.append({"role": "user", "content": prompt})
        response = await self.call_qianxun(messages, model_name=model_name)
        messages.append({"role": "assistant", "content": response})
        return response

    def system_prompt(self, system: str, messages: List[Dict[str, Any]]):
        messages.append({"role": "system", "content": system})
        
    async def workflow(self, user_messages: list, agent_config: str, tools_description: str, model_name: str, language: str = "en"):
        messages: List[Dict[str, Any]] = []

        self.system_prompt(system=PromptManager().get_prompt(
            "checkpoint_generation_system_prompt",
            agent="common_util",
            language=language,
        ), messages=messages)

        await self.task_generation(
            prompt=PromptManager().get_prompt(
                "checkpoint_generation_step1_prompt",
                agent="common_util",
                language=language,
            ).format(
                agent_config=agent_config,
                tools_description=tools_description,
                user_messages=user_messages,
                latest_user_message=user_messages[-1],
            ),
            messages=messages,
            model_name=model_name,
        )

        await self.task_generation(
            prompt=PromptManager().get_prompt(
                "checkpoint_generation_step2_prompt",
                agent="common_util",
                language=language,
            ),
            messages=messages,
            model_name=model_name,
        )

        three_response = await self.task_generation(
            prompt=PromptManager().get_prompt(
                "checkpoint_generation_step3_prompt",
                agent="common_util",
                language=language,
            ),
            messages=messages,
            model_name=model_name,
        )


        three_response = self.parse_json_response(three_response)
        if isinstance(three_response, dict):
            three_response["messages"] = user_messages
            three_response = json.dumps(three_response, ensure_ascii=False)
        elif isinstance(three_response, str):
            three_response = three_response + f"\nmessages: {user_messages}"
            
        logger.info("workflow messages: " + json.dumps(messages, ensure_ascii=False, indent=4))
        
        logger.info("workflow result: " + three_response)

        return three_response
