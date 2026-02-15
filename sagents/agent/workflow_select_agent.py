from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, AsyncGenerator, Optional
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.utils.prompt_manager import PromptManager
import json
import uuid


class WorkflowSelectAgent(AgentBase):
    def __init__(self, model: Any, model_config: Optional[Dict[str, Any]] = None, system_prefix: str = ""):
        if model_config is None:
            model_config = {}
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "WorkflowSelectAgent"
        self.agent_description = "工作流选择智能体，专门负责根据用户需求选择最合适的工作流"
        logger.debug("WorkflowSelectAgent 初始化完成")

    async def run_stream(self, session_context: SessionContext, tool_manager: Optional[ToolManager] = None, session_id: Optional[str] = None) -> AsyncGenerator[List[MessageChunk], None]:
        message_manager = session_context.message_manager

        # 提取最近的对话历史
        if 'task_rewrite' in session_context.audit_status:
            recent_message_str = session_context.audit_status['task_rewrite']
        else:
            history_messages = message_manager.extract_all_context_messages(recent_turns=1)
            # 根据 active_budget 压缩消息
            budget_info = message_manager.context_budget_manager.budget_info
            if budget_info:
                history_messages = MessageManager.compress_messages(history_messages, max(budget_info.get('active_budget', 8000),2000))
            recent_message_str = MessageManager.convert_messages_to_str(history_messages)

        # 使用WorkflowManager格式化工作流列表
        workflow_list = session_context.workflow_manager.format_workflow_list()

        # 使用PromptManager获取模板，传入语言参数
        workflow_select_template = PromptManager().get_agent_prompt_auto("workflow_select_template", language=session_context.get_language())
        prompt = workflow_select_template.format(
            conversation_history=recent_message_str,
            workflow_list=workflow_list,
            agent_description=self.system_prefix,
        )

        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id, language=session_context.get_language()),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.GUIDE.value
            )
        ]
        all_content = ''
        async for llm_repsonse_chunk in self._call_llm_streaming(messages=llm_request_message,
                                                                 session_id=session_id,
                                                                 step_name="workflow_select"):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                all_content += llm_repsonse_chunk.choices[0].delta.content

        try:
            # 提取JSON部分
            logger.debug(f"WorkflowSelector: 原始LLM响应: {all_content}")
            json_start = all_content.find('{')
            json_end = all_content.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_content = all_content[json_start:json_end]
                result = json.loads(json_content)
                logger.debug(f"WorkflowSelector: 提取的JSON内容: {json_content}")
                has_matching = result.get('has_matching_workflow', False)
                selected_workflow_index = result.get('selected_workflow_index', 0)

                logger.info(f"WorkflowSelector: LLM分析结果 - 匹配: {has_matching}, 工作流索引: {selected_workflow_index}")
                if has_matching and selected_workflow_index >= 0:
                    selected_workflow = session_context.workflow_manager.get_workflow_by_index(selected_workflow_index)
                    if selected_workflow:
                        logger.info(f"WorkflowSelector: 工作流名称: {selected_workflow.name}")
                        selected_workflow_name = selected_workflow.name
                        guidance = session_context.workflow_manager.format_workflows_for_context([selected_workflow_name])
                        session_context.add_and_update_system_context({'workflow_guidance': guidance})
                else:
                    logger.info("WorkflowSelector: 未找到合适的工作流")
            else:
                logger.error("WorkflowSelector: 无法从LLM响应中提取JSON内容")

        except json.JSONDecodeError as e:
            logger.error(f"WorkflowSelector: JSON解析失败: {str(e)}")
            logger.error(f"WorkflowSelector: 原始响应: {all_content}")
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=f"WorkflowSelector: 无法从LLM响应中提取JSON内容，原始响应: {all_content}",
                message_id=str(uuid.uuid4()),
                message_type=MessageType.GUIDE.value
            )]
