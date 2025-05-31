from pandas.compat import F
from agents.agent.agent_controller import AgentController
from agents.tool.tool_manager import ToolManager
from agents.agent.agent_base import AgentBase
from typing import List, Dict, Any, Optional, Generator

class CodeAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any]):
        self.agent_description = """这是一个专门用于代码或者软件开发的助手。
当需要完成代码编写或者软件开发任务时，你可以使用这个助手。他会更加的专业和准确。
"""
        system_prefix = """你是一个代码或者软件开发助手，你需要根据用户需求，生成清晰可执行的代码。

你需要遵循以下规则：
1. 输出的代码必须是完整的，不能有任何缺失或者错误。
2. 输出的代码必须是可执行的，不能有任何语法错误或者逻辑错误。
3. 输出的代码必须是符合用户需求的，不能有任何多余的功能。
"""
        self.controller = AgentController(model, model_config, system_prefix=system_prefix)
        self.tool_manager = ToolManager(is_auto_discover=False)

    def run_stream(self, messages: List[Dict],
                    session_id: Any | None = None,
                    deep_thinking: bool = True,
                    summary: bool = True,
                    max_loop_count: int = 10,
                    deep_research: bool = True) -> Generator[List[Dict[str, Any]], None, None]:
        chunk_iter = self.controller.run_stream(input_messages=messages,tool_manager=self.tool_manager,session_id=session_id,deep_thinking=deep_thinking,summary=summary,max_loop_count=max_loop_count,deep_research=deep_research)
        for chunk in chunk_iter:
            yield chunk
