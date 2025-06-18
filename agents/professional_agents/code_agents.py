from agents.agent.agent_controller import AgentController
from agents.tool.tool_manager import ToolManager
from agents.agent.agent_base import AgentBase
from typing import List, Dict, Any, Optional, Generator
from agents.utils.logger import logger

class CodeAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any]):
        self.agent_description = """这是一个专门用于代码或者软件开发的助手和工具。
当需要完成代码编写或者软件开发任务时，你可以使用这个助手。他会更加的专业和准确。
"""
        system_prefix = """你是一个代码或者软件开发助手，你需要根据用户需求，生成清晰可执行的代码。

你需要遵循以下规则：
1. 输出的代码必须是完整的，不能有任何缺失或者错误。
2. 输出的代码必须是可执行的，不能有任何语法错误或者逻辑错误。
3. 输出的代码必须是符合用户需求的，不能有任何多余的功能。
4. 当代码文件较长时，可以通过search_and_replace工具，对代码进行搜索和替换更多的内容，以满足用户需求。
5. 不要创建太多的代码版本，尽可能的修改已有的代码，以满足用户需求。
"""
        self.controller = AgentController(model, model_config, system_prefix=system_prefix)
        self.tool_manager = ToolManager(is_auto_discover=False)
        self.deep_thinking: bool = False
        self.summary: bool = False
        self.max_loop_count: int = 10
        self.deep_research: bool = True
        
    def _create_filtered_tool_manager(self, original_tool_manager: Optional[Any] = None) -> ToolManager:
        """
        创建一个过滤掉自己的tool_manager副本，避免自调用
        
        Args:
            original_tool_manager: 原始的tool_manager
            
        Returns:
            ToolManager: 过滤后的tool_manager
        """
        if original_tool_manager is None:
            return self.tool_manager
            
        # 创建新的tool_manager实例
        filtered_tool_manager = ToolManager(is_auto_discover=False)
        
        # 复制所有工具，但排除自己
        agent_name = self.__class__.__name__
        for tool_name, tool_spec in original_tool_manager.tools.items():
            if tool_name != agent_name:
                filtered_tool_manager.tools[tool_name] = tool_spec
            else:
                logger.info(f"CodeAgent: 过滤掉自调用工具: {tool_name}")
                
        logger.info(f"CodeAgent: 创建过滤后的tool_manager，原有{len(original_tool_manager.tools)}个工具，过滤后{len(filtered_tool_manager.tools)}个工具")
        return filtered_tool_manager
        
    def run_stream(self, messages: List[Dict],
                    tool_manager: Optional[Any] = None,
                    session_id: Any | None = None,
                    system_context: Optional[Dict[str, Any]] = None) -> Generator[List[Dict[str, Any]], None, None]:
        # 创建过滤后的tool_manager，避免自调用
        filtered_tool_manager = self._create_filtered_tool_manager(tool_manager)
        
        chunk_iter = self.controller.run_stream(
            input_messages=messages,
            tool_manager=filtered_tool_manager,
            session_id=session_id,
            deep_thinking=self.deep_thinking,
            summary=self.summary,
            max_loop_count=self.max_loop_count,
            deep_research=self.deep_research,
            system_context=system_context
        )
        
        # 直接返回流式结果，不做任何处理
        for chunk in chunk_iter:
            yield chunk
