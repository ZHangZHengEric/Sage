"""
Sage Multi-Agent Demo

智能多智能体协作演示应用
主要优化：代码结构、错误处理、用户体验、性能
"""


import argparse
import asyncio
import json
import logging
import os
import sys
import time
import traceback
import uuid

# 抑制Streamlit的ScriptRunContext警告（在bare mode下可以忽略）
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from _example_support import (
    add_project_root,
    ensure_python_version,
    exit_for_missing_dependency,
    maybe_show_help,
    script_dir,
)

EXAMPLES_DIR = script_dir(__file__)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Sage Multi-Agent Interactive Chat',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  streamlit run examples/sage_demo.py -- --default_llm_api_key YOUR_API_KEY --default_llm_api_base_url URL --default_llm_model_name gpt-4.1
        """
    )

    parser.add_argument('--default_llm_api_key', required=True,
                        help='默认LLM API Key')
    parser.add_argument('--default_llm_api_base_url', required=True,
                        help='默认LLM API Base')
    parser.add_argument('--default_llm_model_name', required=True,
                        help='默认LLM API Model')
    parser.add_argument('--default_llm_max_tokens', default=4096, type=int,
                        help='默认LLM API Max Tokens')
    parser.add_argument('--default_llm_temperature', default=0.3, type=float,
                        help='默认LLM API Temperature')
    parser.add_argument('--default_llm_max_model_len', default=54000, type=int,
                        help='默认LLM 最大上下文')
    parser.add_argument('--default_llm_top_p', default=0.9, type=float,
                        help='默认LLM Top P')
    parser.add_argument('--default_llm_presence_penalty', default=0.0, type=float,
                        help='默认LLM Presence Penalty')

    parser.add_argument("--context_history_ratio", type=float, default=0.2,
                        help='上下文预算管理器：历史消息的比例（0-1之间）')
    parser.add_argument("--context_active_ratio", type=float, default=0.3,
                        help='上下文预算管理器：活跃消息的比例（0-1之间）')
    parser.add_argument("--context_max_new_message_ratio", type=float, default=0.5,
                        help='上下文预算管理器：新消息的比例（0-1之间）')
    parser.add_argument("--context_recent_turns", type=int, default=0,
                        help='上下文预算管理器：限制最近的对话轮数，0表示不限制')

    parser.add_argument('--host', default='0.0.0.0',
                        help='Server Host')
    parser.add_argument('--port', default=8501, type=int,
                        help='Server Port')

    parser.add_argument('--mcp_config', default=str(EXAMPLES_DIR / 'mcp_setting.json'),
                        help='MCP配置文件路径')
    parser.add_argument('--workspace', default='sage_demo_workspace',
                        help='工作空间目录')
    parser.add_argument('--logs_dir', default='logs',
                        help='日志目录')
    parser.add_argument('--skills_path', default=None,
                        help='技能文件夹路径')
    parser.add_argument('--preset_running_config', default=str(EXAMPLES_DIR / 'preset_running_config.json'),
                        help='预设配置，system_context，以及workflow，与接口中传过来的合并使用')
    parser.add_argument('--memory_root', default=None,
                        help='记忆存储根目录（已废弃，请使用 --memory_type）')
    parser.add_argument('--memory_type', default='session',
                        help='记忆类型: session | user')

    return parser


maybe_show_help(build_argument_parser)
ensure_python_version(__file__)
project_root = add_project_root(__file__)

try:
    import streamlit as st
    from openai import AsyncOpenAI
except ModuleNotFoundError as exc:
    exit_for_missing_dependency(__file__, exc)

from sagents.context.messages.message_manager import MessageManager
from sagents.sagents import SAgent
from sagents.tool import ToolManager, ToolProxy
from sagents.skill import SkillManager, SkillProxy
from sagents.utils.logger import logger

warnings.filterwarnings("ignore", message=".*missing ScriptRunContext.*")
logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)


# 设置页面配置 - 必须在任何其他streamlit调用之前
st.set_page_config(
    page_title="Sage Multi-Agent Framework",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)




class ComponentManager:
    """组件管理器 - 负责初始化和管理核心组件"""

    def __init__(self, api_key: str, model_name: Optional[str] = None, base_url: Optional[str] = None,
                 max_tokens: Optional[int] = None, temperature: Optional[float] = None,
                 max_model_len: Optional[int] = None, top_p: Optional[float] = None,
                 presence_penalty: Optional[float] = None,
                 workspace: Optional[str] = None, memory_type: Optional[str] = "session",
                 mcp_config: Optional[str] = None,
                 preset_running_config: Optional[str] = None, logs_dir: Optional[str] = None,
                 skills_path: Optional[str] = None,
                 context_history_ratio: Optional[float] = None,
                 context_active_ratio: Optional[float] = None,
                 context_max_new_message_ratio: Optional[float] = None,
                 context_recent_turns: Optional[int] = None,
                 session_root: Optional[str] = None,
                 agent_id: Optional[str] = None,
                 virtual_workspace: Optional[str] = None,
                 sandbox_type: Optional[str] = "local"):
        logger.debug(f"使用配置 - 模型: {model_name}, 温度: {temperature}")
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_model_len = max_model_len
        self.top_p = top_p
        self.presence_penalty = presence_penalty
        self.workspace = workspace or "workspace"
        self.memory_type = memory_type
        self.context_history_ratio = float(context_history_ratio) if context_history_ratio is not None else None
        self.context_active_ratio = float(context_active_ratio) if context_active_ratio is not None else None
        self.context_max_new_message_ratio = float(context_max_new_message_ratio) if context_max_new_message_ratio is not None else None
        self.context_recent_turns = context_recent_turns
        self.mcp_config = mcp_config
        self.preset_running_config = preset_running_config
        self.logs_dir = logs_dir
        self.skills_path = skills_path
        self.session_root = session_root
        self.agent_id = agent_id or "demo_agent"
        self.virtual_workspace = virtual_workspace or workspace or "/sage-workspace"
        self.sandbox_type = sandbox_type

        # 处理preset_running_config（参考sage_server.py的实现）
        self.preset_config_dict = {}
        self.system_prefix = "You are a helpful AI assistant."
        self.preset_system_context = None
        self.preset_available_workflows = None
        self.preset_available_tools = None
        self.preset_max_loop_count = None

        # 构建context_budget_config字典
        self.context_budget_config: Dict[str, Any] = {
            'max_model_len': self.max_model_len
        }
        if self.context_history_ratio is not None:
            self.context_budget_config['history_ratio'] = self.context_history_ratio
        if self.context_active_ratio is not None:
            self.context_budget_config['active_ratio'] = self.context_active_ratio
        if self.context_max_new_message_ratio is not None:
            self.context_budget_config['max_new_message_ratio'] = self.context_max_new_message_ratio
        if self.context_recent_turns is not None:
            self.context_budget_config['recent_turns'] = self.context_recent_turns

        if preset_running_config and os.path.exists(preset_running_config):
            try:
                with open(preset_running_config, 'r', encoding='utf-8') as f:
                    self.preset_config_dict = json.load(f)
                    logger.debug(f"加载预设配置: {preset_running_config}")

                    # 设置system_prefix
                    if "system_prefix" in self.preset_config_dict:
                        self.system_prefix = self.preset_config_dict['system_prefix']
                        logger.debug(f"使用预设system_prefix: {self.system_prefix}")
                    elif "systemPrefix" in self.preset_config_dict:
                        self.system_prefix = self.preset_config_dict['systemPrefix']
                        logger.debug(f"使用预设systemPrefix: {self.system_prefix}")

                    # 设置system_context
                    if "system_context" in self.preset_config_dict:
                        self.preset_system_context = self.preset_config_dict['system_context']
                        logger.debug("使用预设system_context")
                    elif "systemContext" in self.preset_config_dict:
                        self.preset_system_context = self.preset_config_dict['systemContext']
                        logger.debug("使用预设systemContext")

                    # 设置available_workflows
                    if "available_workflows" in self.preset_config_dict:
                        self.preset_available_workflows = self.preset_config_dict['available_workflows']
                        logger.debug("使用预设available_workflows")
                    elif "availableWorkflows" in self.preset_config_dict:
                        self.preset_available_workflows = self.preset_config_dict['availableWorkflows']
                        logger.debug("使用预设availableWorkflows")

                    # 设置available_tools
                    if "available_tools" in self.preset_config_dict:
                        self.preset_available_tools = self.preset_config_dict['available_tools']
                        logger.debug("使用预设available_tools")
                    elif "availableTools" in self.preset_config_dict:
                        self.preset_available_tools = self.preset_config_dict['availableTools']
                        logger.debug("使用预设availableTools")

                    # 设置max_loop_count
                    if "max_loop_count" in self.preset_config_dict:
                        self.preset_max_loop_count = self.preset_config_dict['max_loop_count']
                        logger.debug(f"使用预设max_loop_count: {self.preset_max_loop_count}")
                    elif "maxLoopCount" in self.preset_config_dict:
                        self.preset_max_loop_count = self.preset_config_dict['maxLoopCount']
                        logger.debug(f"使用预设maxLoopCount: {self.preset_max_loop_count}")

            except Exception as e:
                logger.warning(f"加载预设配置失败: {e}")
                self.preset_config_dict = {}

        # 初始化组件变量
        self._tool_manager: Optional[Union[ToolManager, ToolProxy]] = None
        self._skill_manager: Optional[Union[SkillManager, SkillProxy]] = None
        self._controller: Optional[SAgent] = None
        self._model: Optional[AsyncOpenAI] = None

    async def initialize(self) -> tuple[Union[ToolManager, ToolProxy], Optional[Union[SkillManager, SkillProxy]], SAgent]:
        """异步初始化所有组件"""
        try:
            logger.info(f"初始化组件，模型: {self.model_name}")

            # 异步初始化工具管理器
            self._tool_manager = await self._init_tool_manager()
            
            # 初始化技能管理器
            self._skill_manager = self._init_skill_manager()

            # 初始化模型和控制器
            self._model = self._init_model()
            self._controller = self._init_controller()

            logger.info("所有组件初始化成功")
            return self._tool_manager, self._skill_manager, self._controller

        except Exception as e:
            logger.error(f"组件初始化失败: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    async def _init_tool_manager(self) -> Union[ToolManager, ToolProxy]:
        """异步初始化工具管理器"""
        logger.debug("初始化工具管理器")

        # 设置MCP配置路径环境变量（参考sage_server.py的实现）

        # 创建工具管理器实例，但不自动发现工具
        tool_manager = ToolManager(is_auto_discover=False)

        # 手动进行基础工具发现
        tool_manager.discover_tools_from_path()

        # 设置 MCP 配置路径
        if self.mcp_config:
            logger.debug(f"设置MCP配置路径: {self.mcp_config}")
            await tool_manager._discover_mcp_tools(mcp_setting_path=self.mcp_config)

        # 如果有preset_available_tools配置，使用ToolProxy进行工具过滤
        if self.preset_available_tools:
            logger.info(f"使用工具代理，可用工具: {self.preset_available_tools}")
            tool_proxy = ToolProxy(tool_manager, self.preset_available_tools)
            logger.info(f"工具代理初始化完成，过滤后可用工具数量: {len(self.preset_available_tools)}")
            return tool_proxy

        return tool_manager

    def _init_skill_manager(self) -> Optional[Union[SkillManager, SkillProxy]]:
        """初始化技能管理器"""
        logger.debug("初始化技能管理器")
        try:
            skill_dirs = [self.skills_path] if self.skills_path else None
            return SkillManager(skill_dirs=skill_dirs)
        except Exception as e:
            logger.error(f"技能管理器初始化失败: {str(e)}")
            # 技能管理器初始化失败不应阻止整个应用启动，记录日志即可
            return None

    def _init_model(self) -> AsyncOpenAI:
        """初始化模型"""
        logger.debug(f"初始化模型，base_url: {self.base_url}")
        try:
            return AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
        except Exception as e:
            logger.error(f"模型初始化失败: {str(e)}")
            raise

    def _init_controller(self) -> SAgent:
        """初始化控制器"""
        try:
            # session_root_space 独立于 agent_workspace
            if self.session_root:
                 session_root_space = os.path.abspath(self.session_root)
            else:
                 session_root_space = os.path.join(os.path.dirname(os.path.abspath(self.workspace)), "demo_sessions")
            os.makedirs(session_root_space, exist_ok=True)
            
            controller = SAgent(
                session_root_space=session_root_space,
                enable_obs=True,
                sandbox_type=self.sandbox_type
            )
            return controller

        except Exception as e:
            logger.error(f"控制器初始化失败: {str(e)}")
            logger.error(traceback.format_exc())
            raise


def convert_messages_for_show(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """转换消息格式用于显示"""
    # logger.debug(f"转换 {len(messages)} 条消息用于显示")
    new_messages = []

    for message in messages:
        if not message.get('content'):
            continue

        new_message = {
            'message_id': message.get('message_id', str(uuid.uuid4())),
            'role': 'assistant' if message['role'] != 'user' else 'user',
            'content': message.get('content')
        }
        new_messages.append(new_message)

    return new_messages


def create_user_message(content: str) -> Dict[str, Any]:
    """创建用户消息"""
    return {
        "role": "user",
        "content": content,
        "type": "normal",
        "message_id": str(uuid.uuid4())
    }


class StreamingHandler:
    """流式处理器 - 处理实时消息流"""

    def __init__(self, controller: SAgent, component_manager: Optional[ComponentManager] = None):
        self.controller = controller
        self.component_manager = component_manager
        self._current_stream: Optional[Any] = None
        self._current_stream_id: Optional[str] = None

    async def process_stream(self,
                             messages: List[Dict[str, Any]],
                             tool_manager: Union[ToolManager, ToolProxy],
                             skill_manager: Optional[Union[SkillManager, SkillProxy]] = None,
                             session_id: Optional[str] = None,
                             use_deepthink: bool = True,
                             agent_mode: str = "simple",
                             context_budget_config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """处理消息流"""
        logger.debug("开始处理流式响应")

        new_messages = []

        # 准备preset配置参数
        system_context = None
        available_workflows = None
        max_loop_count = 10  # 默认值

        if self.component_manager:
            system_context = self.component_manager.preset_system_context
            available_workflows = self.component_manager.preset_available_workflows
            # 如果配置中有指定，则使用配置的值
            if self.component_manager.preset_max_loop_count is not None:
                max_loop_count = self.component_manager.preset_max_loop_count

        # 准备模型配置
        model_config = {
            "model": self.component_manager.model_name,
            "temperature": self.component_manager.temperature,
            "max_tokens": self.component_manager.max_tokens,
            "max_model_len": self.component_manager.max_model_len,
            "top_p": self.component_manager.top_p,
            "presence_penalty": self.component_manager.presence_penalty
        }
        
        # 准备模型客户端
        model_client = AsyncOpenAI(
            api_key=self.component_manager.api_key,
            base_url=self.component_manager.base_url
        )

        try:
            async for chunk in self.controller.run_stream(
                session_id=session_id,
                input_messages=messages,
                tool_manager=tool_manager,
                skill_manager=skill_manager,
                model=model_client,
                model_config=model_config,
                system_prefix=self.component_manager.system_prefix,
                host_workspace=self.component_manager.workspace,
                virtual_workspace=self.component_manager.virtual_workspace,
                default_memory_type=self.component_manager.memory_type,
                user_id="default_user",
                agent_id=self.component_manager.agent_id,
                deep_thinking=use_deepthink,
                max_loop_count=max_loop_count,
                agent_mode=agent_mode,
                system_context=system_context,
                available_workflows=available_workflows,
                context_budget_config=context_budget_config
            ):
                # 将message chunk类型的chunks 转化成字典
                chunks_dict = [msg.to_dict() for msg in chunk]
                new_messages.extend(chunks_dict)
                await self._update_display(messages, new_messages)

        except Exception as e:
            logger.error(traceback.format_exc())
            error_response = {
                "role": "assistant",
                "content": f"流式处理出错: {str(e)}",
                "message_id": str(uuid.uuid4()),
            }
            new_messages.append(error_response)

        return new_messages

    async def _update_display(self, base_messages: List[Dict], new_messages: List[Dict]):
        """更新显示内容"""
        merged_messages = MessageManager.merge_new_messages_to_old_messages(new_messages, base_messages.copy())
        merged_messages_dict = [msg.to_dict() for msg in merged_messages]
        display_messages = convert_messages_for_show(merged_messages_dict)

        # 找到最新的助手消息
        latest_assistant_msg = None
        for msg in reversed(display_messages):
            if msg['role'] in ['assistant', 'tool']:
                latest_assistant_msg = msg
                break

        if latest_assistant_msg:
            msg_id = latest_assistant_msg.get('message_id')

            # 处理新的消息流
            if msg_id != self._current_stream_id:
                logger.debug(f"检测到新消息流: {msg_id}")
                self._current_stream_id = msg_id
                self._current_stream = st.chat_message('assistant').empty()

            # 更新显示内容
            if self._current_stream:
                self._current_stream.write(latest_assistant_msg['content'])


def setup_ui(config: Dict):
    """设置用户界面"""
    st.title("🧠 Sage Multi-Agent Framework")
    st.markdown("**智能多智能体协作平台**")

    # 侧边栏设置
    with st.sidebar:
        st.header("⚙️ 设置")

        # 智能体模式选项
        agent_mode_options = {
            "simple": "Simple (基础模式)",
            "fibre": "Fibre (多智能体协作)",
            "multi": "Multi (多智能体 - 旧版)" # 保留兼容
        }
        agent_mode = st.selectbox(
            '🤖 智能体模式',
            options=list(agent_mode_options.keys()),
            format_func=lambda x: agent_mode_options[x],
            index=1 if config.get('agent_mode') == 'fibre' else 0
        )
        
        use_deepthink = st.toggle('🧠 启用深度思考',
                                  value=config.get('use_deepthink', True))

        session_root = st.text_input("Session Root Directory", value="demo_sessions", help="会话存储根目录")
        
        # 内存设置

        # 系统信息
        st.subheader("📊 系统信息")
        st.info(f"**模型**: {config.get('model_name', '未配置')}")
        st.info(f"**温度**: {config.get('temperature', '未配置')}")
        st.info(f"**最大标记**: {config.get('max_tokens', '未配置')}")
        st.info(f"**环境**: {config.get('environment', '未配置')}")

        # 工具列表
        if st.session_state.get('tool_manager'):
            display_tools(st.session_state.tool_manager)

        # 清除历史按钮
        if st.button("🗑️ 清除对话历史", type="secondary"):
            clear_history()

    return agent_mode, use_deepthink, session_root


def display_tools(tool_manager: Union[ToolManager, ToolProxy]):
    """显示可用工具"""
    st.subheader("🛠️ 可用工具")
    tools = tool_manager.list_tools_simplified()

    if tools:
        for tool_info in tools:
            with st.expander(f"🔧 {tool_info['name']}", expanded=False):
                st.write(tool_info['description'])
    else:
        st.info("暂无可用工具")


def clear_history():
    """清除对话历史"""
    logger.info("用户清除对话历史")
    st.session_state.conversation = []
    st.session_state.inference_conversation = []
    # 更新 session_id
    st.session_state.session_id = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime()) + '_' + str(uuid.uuid4())[:4]
    logger.info(f"更新会话ID: {st.session_state.session_id}")
    st.rerun()


def init_session_state():
    """初始化会话状态"""
    if 'conversation' not in st.session_state:
        st.session_state.conversation = []
    if 'inference_conversation' not in st.session_state:
        st.session_state.inference_conversation = []
    if 'components_initialized' not in st.session_state:
        st.session_state.components_initialized = False
    if 'session_id' not in st.session_state:
        st.session_state.session_id = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime()) + '_' + str(uuid.uuid4())[:4]
        logger.info(f"初始化会话ID: {st.session_state.session_id}")


def display_conversation_history():
    """显示对话历史"""
    for msg in st.session_state.conversation:
        if msg['role'] == 'user':
            with st.chat_message("user"):
                st.write(msg['content'])
        elif msg['role'] == 'assistant':
            with st.chat_message("assistant"):
                st.write(msg['content'])


def process_user_input(user_input: str, tool_manager: Union[ToolManager, ToolProxy], controller: SAgent):
    """处理用户输入"""
    logger.info(f"处理用户输入: {user_input[:50]}{'...' if len(user_input) > 50 else ''}")

    # 创建用户消息
    user_msg = create_user_message(user_input)

    # 添加到对话历史
    st.session_state.conversation.append(user_msg)
    st.session_state.inference_conversation.append(user_msg)

    # 显示用户消息
    with st.chat_message("user"):
        st.write(user_input)

    # 处理响应
    with st.spinner("🤔 正在思考..."):
        try:
            generate_response(tool_manager, controller)
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"生成响应时出错: {str(e)}")
            with st.chat_message("assistant"):
                st.error(f"抱歉，处理您的请求时出现了错误: {str(e)}")


def generate_response(tool_manager: Union[ToolManager, ToolProxy], controller: SAgent):
    """生成智能体响应"""
    component_manager = st.session_state.get('component_manager', None)
    streaming_handler = StreamingHandler(controller, component_manager)

    context_budget_config = component_manager.context_budget_config if component_manager else None

    # 获取skill_manager
    skill_manager = st.session_state.get('skill_manager', None)

    # 处理流式响应
    new_messages = asyncio.run(streaming_handler.process_stream(
        st.session_state.inference_conversation.copy(),
        tool_manager,
        skill_manager=skill_manager,
        session_id=st.session_state.session_id,
        use_deepthink=st.session_state.get('use_deepthink', True),
        agent_mode=st.session_state.get('agent_mode', 'simple'),
        context_budget_config=context_budget_config
    ))

    # 合并消息
    if new_messages:
        merged_messages = MessageManager.merge_new_messages_to_old_messages(
            new_messages, st.session_state.inference_conversation
        )
        merged_messages_dict = [msg.to_dict() for msg in merged_messages]
        st.session_state.inference_conversation = merged_messages_dict

        # 更新显示对话
        display_messages = convert_messages_for_show(merged_messages_dict)
        st.session_state.conversation = display_messages

        logger.info("响应生成完成")


def run_web_demo(api_key: str, model_name: Optional[str] = None, base_url: Optional[str] = None,
                 max_tokens: Optional[int] = None, temperature: Optional[float] = None,
                 max_model_len: Optional[int] = None, top_p: Optional[float] = None,
                 presence_penalty: Optional[float] = None,
                 workspace: Optional[str] = None, memory_type: Optional[str] = "session",
                 mcp_config: Optional[str] = None,
                 preset_running_config: Optional[str] = None, logs_dir: Optional[str] = None,
                 skills_path: Optional[str] = None,
                 host: Optional[str] = None, port: Optional[int] = None,
                 context_history_ratio: Optional[float] = None,
                 context_active_ratio: Optional[float] = None,
                 context_max_new_message_ratio: Optional[float] = None,
                 context_recent_turns: Optional[int] = None):
    """运行 Streamlit web 界面"""
    logger.info("启动 Streamlit web 演示")

    # 设置Streamlit服务器配置（通过环境变量）
    if port:
        os.environ['STREAMLIT_SERVER_PORT'] = str(port)
        logger.info(f"设置Streamlit端口为: {port}")
    if host:
        os.environ['STREAMLIT_SERVER_ADDRESS'] = host
        logger.info(f"设置Streamlit主机为: {host}")

    # 显示服务器信息
    actual_host = host or '0.0.0.0'
    actual_port = port or 8501
    logger.info(f"Streamlit服务器将在 http://{actual_host}:{actual_port} 启动")

    # 初始化会话状态
    init_session_state()
    config = {
        'api_key': api_key,
        'model_name': model_name,
        'base_url': base_url,
        'max_tokens': max_tokens,
        'temperature': temperature,
        'max_model_len': max_model_len,
        'top_p': top_p,
        'presence_penalty': presence_penalty,
        'workspace': workspace,
        'memory_type': memory_type,
        'mcp_config': mcp_config,
        'preset_running_config': preset_running_config,
        'logs_dir': logs_dir,
        'context_history_ratio': context_history_ratio,
        'context_active_ratio': context_active_ratio,
        'context_max_new_message_ratio': context_max_new_message_ratio,
        'context_recent_turns': context_recent_turns
    }
    # 设置界面（此时能获取到正确的配置）
    agent_mode, use_deepthink, session_root = setup_ui(config)

    # 存储设置到会话状态
    st.session_state.agent_mode = agent_mode
    st.session_state.use_deepthink = use_deepthink

    # 初始化组件（只执行一次）
    if not st.session_state.components_initialized:
        try:
            with st.spinner("正在初始化系统组件..."):
                component_manager = ComponentManager(
                api_key=api_key,
                model_name=model_name,
                base_url=base_url,
                max_tokens=max_tokens,
                temperature=temperature,
                max_model_len=max_model_len,
                top_p=top_p,
                presence_penalty=presence_penalty,
                workspace=workspace,
                memory_type=memory_type,
                mcp_config=mcp_config,
                preset_running_config=preset_running_config,
                logs_dir=logs_dir,
                skills_path=skills_path,
                context_history_ratio=context_history_ratio,
                context_active_ratio=context_active_ratio,
                context_max_new_message_ratio=context_max_new_message_ratio,
                context_recent_turns=context_recent_turns,
                session_root=session_root,
            )
                tool_manager, skill_manager, controller = asyncio.run(component_manager.initialize())
                st.session_state.tool_manager = tool_manager
                st.session_state.skill_manager = skill_manager
                st.session_state.controller = controller 
                st.session_state.component_manager = component_manager
                st.session_state.components_initialized = True
                st.session_state.config_updated = True  # 标记配置已更新
            st.success("系统初始化完成！")
            # 打印已注册工具，便于调试
            print("已注册工具：", [t['name'] for t in tool_manager.list_tools_simplified()])
            # 初始化完成后重新运行，确保UI显示更新后的配置
            if skill_manager:
                print("已注册技能：", skill_manager.list_skills())
            st.rerun()
        except Exception as e:
            # 其他异常
            st.error(f"系统初始化失败: {str(e)}")

            st.warning("**技术详情:**")
            st.code(traceback.format_exc())

            st.stop()

    # 显示历史对话
    display_conversation_history()

    # 用户输入
    user_input = st.chat_input("💬 请输入您的问题...")

    if user_input and user_input.strip():
        process_user_input(
            user_input.strip(),
            st.session_state.tool_manager,
            st.session_state.controller
        )


def parse_arguments() -> Dict[str, Any]:
    """解析命令行参数"""
    parser = build_argument_parser()
    args = parser.parse_args()

    # 处理workspace路径
    if args.workspace:
        args.workspace = os.path.abspath(args.workspace)
    
    # 设置 MEMORY_ROOT_PATH 环境变量
    memory_root_path = os.path.join(os.path.dirname(os.path.abspath(args.workspace)), 'memory')
    os.environ.setdefault('MEMORY_ROOT_PATH', memory_root_path)
        
    # 处理 memory_root 兼容性
    if args.memory_root:
        os.environ["MEMORY_ROOT_PATH"] = args.memory_root
        print("WARNING: memory_root 参数已废弃，请使用 memory_type 参数。已自动设置 MEMORY_ROOT_PATH 环境变量。")

    return {
        'api_key': args.default_llm_api_key,
        'model_name': args.default_llm_model_name,
        'base_url': args.default_llm_api_base_url,
        'max_tokens': args.default_llm_max_tokens,
        'temperature': args.default_llm_temperature,
        'max_model_len': args.default_llm_max_model_len,
        'top_p': args.default_llm_top_p,
        'presence_penalty': args.default_llm_presence_penalty,
        'context_history_ratio': args.context_history_ratio,
        'context_active_ratio': args.context_active_ratio,
        'context_max_new_message_ratio': args.context_max_new_message_ratio,
        'context_recent_turns': args.context_recent_turns,
        'host': args.host,
        'port': args.port,
        'mcp_config': args.mcp_config,
        'workspace': args.workspace,
        'logs_dir': args.logs_dir,
        'skills_path': args.skills_path,
        'preset_running_config': args.preset_running_config,
        'memory_type': args.memory_type
    }


def main():
    """主函数"""
    try:
        # 解析配置
        config = parse_arguments()
        logger.info(f"启动应用，模型: {config['model_name']}")

        # 运行 Web 演示
        run_web_demo(
            api_key=config['api_key'],
            model_name=config['model_name'],
            base_url=config['base_url'],
            max_tokens=config['max_tokens'],
            temperature=config['temperature'],
            max_model_len=config['max_model_len'],
            top_p=config['top_p'],
            presence_penalty=config['presence_penalty'],
            workspace=config['workspace'],
            memory_type=config['memory_type'],
            mcp_config=config['mcp_config'],
            preset_running_config=config['preset_running_config'],
            logs_dir=config['logs_dir'],
            skills_path=config['skills_path'],
            host=config['host'],
            port=config['port'],
            context_history_ratio=config['context_history_ratio'],
            context_active_ratio=config['context_active_ratio'],
            context_max_new_message_ratio=config['context_max_new_message_ratio'],
            context_recent_turns=config['context_recent_turns']
        )

    except Exception as e:
        logger.error(f"应用启动失败: {str(e)}")
        logger.error(traceback.format_exc())

        st.error(f"应用启动失败: {str(e)}")

        with st.expander("🔍 查看技术详情", expanded=False):
            st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
