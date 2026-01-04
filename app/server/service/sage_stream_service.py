"""
Sage流式服务处理器
"""

import asyncio
import json
import os
import time
import traceback
import uuid
from typing import Any, Dict, Optional, Union

from openai import AsyncOpenAI

from sagents.sagents import SAgent
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_proxy import ToolProxy
from sagents.utils.logger import logger


class SageStreamService:
    """
    Sage 流式服务类

    提供基于 Sage 框架的智能体流式服务功能
    """

    def __init__(self, model: Optional[AsyncOpenAI] = None,
                 model_config: Optional[Dict[str, Any]] = None,
                 tool_manager: Optional[Union[ToolManager, ToolProxy]] = None,
                 preset_running_config: Optional[Dict[str, Any]] = None,
                 workspace: Optional[str] = None,
                 memory_root: Optional[str] = None,
                 max_model_len: Optional[int] = None):
        """
        初始化服务

        Args:
            model: AsyncOpenAI 客户端实例
            model_config: 模型配置字典
            tool_manager: 工具管理器实例
        """
        self.preset_running_config = preset_running_config
        # 设置system_prefix
        if "system_prefix" in self.preset_running_config:
            self.preset_system_prefix = self.preset_running_config['system_prefix']
        elif "systemPrefix" in self.preset_running_config:
            self.preset_system_prefix = self.preset_running_config['systemPrefix']
        else:
            self.preset_system_prefix = None

        # 设置system_context
        if "system_context" in self.preset_running_config:
            self.preset_system_context = self.preset_running_config['system_context']
        elif "systemContext" in self.preset_running_config:
            self.preset_system_context = self.preset_running_config['systemContext']
        else:
            self.preset_system_context = None

        # 设置available_workflows
        if "available_workflows" in self.preset_running_config:
            self.preset_available_workflows = self.preset_running_config['available_workflows']
        elif "availableWorkflows" in self.preset_running_config:
            self.preset_available_workflows = self.preset_running_config['availableWorkflows']
        else:
            self.preset_available_workflows = None

        # 设置available_tools
        if "available_tools" in self.preset_running_config:
            self.preset_available_tools = self.preset_running_config['available_tools']
        elif "availableTools" in self.preset_running_config:
            self.preset_available_tools = self.preset_running_config['availableTools']
        else:
            self.preset_available_tools = None

        # 设置max_loop_count
        if "max_loop_count" in self.preset_running_config:
            self.preset_max_loop_count = self.preset_running_config['max_loop_count']
        elif "maxLoopCount" in self.preset_running_config:
            self.preset_max_loop_count = self.preset_running_config['maxLoopCount']
        else:
            self.preset_max_loop_count = None

        #         "deepThinking": false,
        #   "multiAgent": false,
        # 设置deepThinking
        if "deepThinking" in self.preset_running_config:
            self.preset_deep_thinking = self.preset_running_config['deepThinking']
        elif "deepThinking" in self.preset_running_config:
            self.preset_deep_thinking = self.preset_running_config['deepThinking']
        else:
            self.preset_deep_thinking = None
        # 设置multiAgent
        if "multiAgent" in self.preset_running_config:
            self.preset_multi_agent = self.preset_running_config['multiAgent']
        elif "multiAgent" in self.preset_running_config:
            self.preset_multi_agent = self.preset_running_config['multiAgent']
        else:
            self.preset_multi_agent = None

        # 设置max_model_len
        if max_model_len:
            self.default_llm_max_model_len = max_model_len
        else:
            self.default_llm_max_model_len = 54000

        # 统一打印汇总日志
        summary = {
            "system_prefix": self.preset_system_prefix,
            "system_context": self.preset_system_context,
            "available_workflows": self.preset_available_workflows,
            "available_tools": self.preset_available_tools,
            "max_loop_count": self.preset_max_loop_count,
            "deepThinking": self.preset_deep_thinking,
            "multiAgent": self.preset_multi_agent,
            "max_model_len": self.default_llm_max_model_len,
        }
        logger.debug(f"预设配置汇总: {summary}")

        # workspace 有可能是相对路径
        if workspace:
            workspace = os.path.abspath(workspace)

        # 创建 Sage AgentController 实例
        self.sage_controller = SAgent(
            model=model,
            model_config=model_config,
            system_prefix=self.preset_system_prefix,
            workspace=workspace if workspace.endswith('/') else workspace+'/',
            memory_root=memory_root,
        )
        self.tool_manager = tool_manager
        if self.preset_available_tools:
            if isinstance(self.tool_manager, ToolManager):
                self.tool_manager = ToolProxy(self.tool_manager, self.preset_available_tools)

    async def process_stream(self, messages, session_id=None, user_id=None, deep_thinking=None,
                             max_loop_count=None, multi_agent=None, more_suggest=False,
                             system_context: Dict = None,
                             available_workflows: Dict = None,
                             force_summary: bool = False):
        """处理流式聊天请求"""
        logger.info(f"🚀 SageStreamService.process_stream 开始，会话ID: {session_id}")
        logger.info(f"📝 参数: deep_thinking={deep_thinking}, multi_agent={multi_agent}, messages_count={len(messages)}, max_loop_count={max_loop_count}")
        if isinstance(deep_thinking, str):
            if deep_thinking == 'auto':
                deep_thinking = None
            if deep_thinking == 'off':
                deep_thinking = False
            if deep_thinking == 'on':
                deep_thinking = True
        if isinstance(multi_agent, str):
            if multi_agent == 'auto':
                multi_agent = None
            if multi_agent == 'off':
                multi_agent = False
            if multi_agent == 'on':
                multi_agent = True

        # 如果 self.preset_system_context 不是空，将self.preset_system_context 的内容，更新到 system_context，不是赋值，要检查一下system_context 是不是空
        if self.preset_system_context:
            if system_context:
                system_context.update(self.preset_system_context)
            else:
                system_context = self.preset_system_context
        # 如果 self.preset_available_workflows 不是空，将self.preset_available_workflows 的内容，更新到 available_workflows，不是赋值
        if self.preset_available_workflows:
            if available_workflows:
                available_workflows.update(self.preset_available_workflows)
            else:
                available_workflows = self.preset_available_workflows

        try:
            logger.info("🔄 准备调用 sage_controller.run_stream...")

            # 直接调用异步的 run_stream 方法
            stream_result = self.sage_controller.run_stream(
                input_messages=messages,
                tool_manager=self.tool_manager,
                session_id=session_id,
                user_id=user_id,
                deep_thinking=deep_thinking if deep_thinking is not None else self.preset_deep_thinking,
                max_loop_count=max_loop_count if max_loop_count is not None else self.preset_max_loop_count,
                multi_agent=multi_agent if multi_agent is not None else self.preset_multi_agent,
                more_suggest=more_suggest,
                system_context=system_context,
                available_workflows=available_workflows,
                force_summary=force_summary
            )

            logger.info("✅ run_stream 调用成功，开始处理结果...")

            # 处理返回的异步生成器
            chunk_count = 0
            async for chunk in stream_result:
                chunk_count += 1
                # logger.info(f"📦 处理第 {chunk_count} 个块，包含 {len(chunk)} 条消息")

                # 直接使用消息的原始内容，不重新整理格式
                for message in chunk:
                    # 深拷贝原始消息，保持所有字段
                    result = message.to_dict()

                    # 只添加必要的会话信息
                    result['session_id'] = session_id
                    result['timestamp'] = time.time()

                    # 处理大内容的特殊情况
                    content = result.get('content', '')
                    show_content = result.get('show_content', '')

                    # 清理show_content中的base64图片数据，避免JSON过大，但保留content中的base64
                    if isinstance(show_content, str) and 'data:image' in show_content:
                        try:
                            # 如果show_content是JSON字符串，解析并清理
                            if show_content.strip().startswith('{'):
                                show_content_data = json.loads(show_content)
                                if isinstance(show_content_data, dict) and 'results' in show_content_data:
                                    if isinstance(show_content_data['results'], list):
                                        for item in show_content_data['results']:
                                            if isinstance(item, dict) and 'image' in item:
                                                if item['image'] and isinstance(item['image'], str) and item['image'].startswith('data:image'):
                                                    item['image'] = '[BASE64_IMAGE_REMOVED_FOR_DISPLAY]'
                                result['show_content'] = json.dumps(show_content_data, ensure_ascii=False)
                            else:
                                # 如果不是JSON，直接使用正则表达式清理
                                import re
                                result['show_content'] = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', '[BASE64_IMAGE_REMOVED_FOR_DISPLAY]', show_content)
                        except (json.JSONDecodeError, Exception) as e:
                            logger.warning(f"清理 show_content 失败: {e}")
                            # 如果清理失败，使用正则表达式移除base64数据
                            import re
                            result['show_content'] = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', '[BASE64_IMAGE_REMOVED_FOR_DISPLAY]', show_content)

                    # 特殊处理工具调用结果，避免JSON嵌套问题
                    if result.get('role') == 'tool' and isinstance(content, str):
                        try:
                            # 尝试解析content中的JSON数据
                            if content.strip().startswith('{'):
                                parsed_content = json.loads(content)

                                # 检查是否是嵌套的JSON结构
                                if isinstance(parsed_content, dict) and 'content' in parsed_content:
                                    inner_content = parsed_content['content']
                                    if isinstance(inner_content, str) and inner_content.strip().startswith('{'):
                                        try:
                                            # 解析内层JSON，这通常是实际的工具结果
                                            tool_data = json.loads(inner_content)

                                            # 清理工具结果中的大数据，避免JSON过大
                                            if isinstance(tool_data, dict) and 'results' in tool_data:
                                                if isinstance(tool_data['results'], list):
                                                    for item in tool_data['results']:
                                                        if isinstance(item, dict):
                                                            # 限制文本字段长度，但保留所有字段
                                                            for field in ['snippet', 'description', 'content']:
                                                                if field in item and isinstance(item[field], str):
                                                                    if len(item[field]) > 1000:
                                                                        item[field] = item[field][:1000] + '...[TRUNCATED]'

                                            # 直接使用解析后的数据
                                            result['content'] = tool_data
                                        except json.JSONDecodeError:
                                            # 内层解析失败，使用外层数据
                                            result['content'] = parsed_content
                                    else:
                                        # 内层不是JSON字符串，直接使用
                                        result['content'] = parsed_content
                                else:
                                    # 不是嵌套结构，直接使用
                                    result['content'] = parsed_content

                        except json.JSONDecodeError as e:
                            logger.warning(f"解析工具结果JSON失败: {e}")
                            # 保持原始字符串
                            pass

                    # 直接yield原始消息，不进行复杂的序列化处理
                    yield result
                    await asyncio.sleep(0.01)  # 避免过快发送

                # 在每个块之后让出控制权，避免阻塞事件循环
                await asyncio.sleep(0)

            logger.info(f"🏁 流式处理完成，总共处理了 {chunk_count} 个块", session_id)

        except GeneratorExit:
            logger.warning(
                "🔍 GeneratorExit 客户端断开连接， 详情: 客户端在流式处理过程中断开了连接"
            )
            raise
        except Exception as e:
            logger.error(
                f"❌ 流式处理异常，异常类型：「{type(e).__name__}」，详情: {traceback.format_exc()}",
                session_id
            )
            error_result = {
                'type': 'error',
                'content': f"处理失败: {str(e)}",
                'role': 'assistant',
                'message_id': str(uuid.uuid4()),
                'session_id': session_id,
                'show_content': f"处理失败: {str(e)}"
            }
            yield error_result

    # 会话管理方法
    def interrupt_session(self, session_id: str, message: str = "用户请求中断") -> bool:
        """中断指定会话"""
        return self.sage_controller.interrupt_session(session_id, message)

    def save_session(self, session_id: str) -> bool:
        """保存会话状态"""
        return self.sage_controller.save_session(session_id)

    def get_session_status(self, session_id: str):
        """获取会话状态"""
        return self.sage_controller.get_session_status(session_id)

    def list_active_sessions(self):
        """列出所有活跃会话"""
        return self.sage_controller.list_active_sessions()
