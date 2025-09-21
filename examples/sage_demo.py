"""
Sage Multi-Agent Demo

智能多智能体协作演示应用
主要优化：代码结构、错误处理、用户体验、性能
"""

import os
import sys
import json
import uuid
import argparse
import traceback
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass

# 抑制Streamlit的ScriptRunContext警告（在bare mode下可以忽略）
import warnings
import logging
warnings.filterwarnings("ignore", message=".*missing ScriptRunContext.*")
logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)

import streamlit as st
from openai import OpenAI

# 设置页面配置 - 必须在任何其他streamlit调用之前
st.set_page_config(
    page_title="Sage Multi-Agent Framework",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 项目路径配置
project_root = Path(os.path.realpath(__file__)).parent.parent
sys.path.insert(0, str(project_root))

import sagents
print("sagents loaded from:", sagents.__file__)

from sagents.sagents import SAgent
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_proxy import ToolProxy
from sagents.context.messages.message_manager import MessageManager
from sagents.utils.logger import logger
from openai import OpenAI



class ComponentManager:
    """组件管理器 - 负责初始化和管理核心组件"""
    
    def __init__(self, api_key: str, model_name: str = None, base_url: str = None, 
                 max_tokens: int = None, temperature: float = None,
                 workspace: str = None, memory_root: str = None, mcp_config: str = None,
                 preset_running_config: str = None, logs_dir: str = None):
        logger.debug(f"使用配置 - 模型: {model_name}, 温度: {temperature}")
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.workspace = workspace or "workspace"
        self.memory_root = memory_root
        self.mcp_config = mcp_config
        self.preset_running_config = preset_running_config
        self.logs_dir = logs_dir
        
        # 处理preset_running_config（参考sage_server.py的实现）
        self.preset_config_dict = {}
        self.system_prefix = "You are a helpful AI assistant."
        self.preset_system_context = None
        self.preset_available_workflows = None
        self.preset_available_tools = None
        self.preset_max_loop_count = None
        
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
                        logger.debug(f"使用预设system_context")
                    elif "systemContext" in self.preset_config_dict:
                        self.preset_system_context = self.preset_config_dict['systemContext']
                        logger.debug(f"使用预设systemContext")
                    
                    # 设置available_workflows
                    if "available_workflows" in self.preset_config_dict:
                        self.preset_available_workflows = self.preset_config_dict['available_workflows']
                        logger.debug(f"使用预设available_workflows")
                    elif "availableWorkflows" in self.preset_config_dict:
                        self.preset_available_workflows = self.preset_config_dict['availableWorkflows']
                        logger.debug(f"使用预设availableWorkflows")
                    
                    # 设置available_tools
                    if "available_tools" in self.preset_config_dict:
                        self.preset_available_tools = self.preset_config_dict['available_tools']
                        logger.debug(f"使用预设available_tools")
                    elif "availableTools" in self.preset_config_dict:
                        self.preset_available_tools = self.preset_config_dict['availableTools']
                        logger.debug(f"使用预设availableTools")
                    
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
        self._controller: Optional[SAgent] = None
        self._model: Optional[OpenAI] = None
        
    async def initialize(self) -> tuple[Union[ToolManager, ToolProxy], SAgent]:
        """异步初始化所有组件"""
        try:
            logger.info(f"初始化组件，模型: {self.model_name}")
            
            # 异步初始化工具管理器
            self._tool_manager = await self._init_tool_manager()
            
            # 初始化模型和控制器
            self._model = self._init_model()
            self._controller = self._init_controller()
            
            logger.info("所有组件初始化成功")
            return self._tool_manager, self._controller
            
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
        tool_manager._auto_discover_tools()
        
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
    
    def _init_model(self) -> OpenAI:
        """初始化模型"""
        logger.debug(f"初始化模型，base_url: {self.base_url}")
        try:
            return OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
        except Exception as e:
            logger.error(f"模型初始化失败: {str(e)}")
            raise 
    
    def _init_controller(self) -> SAgent:
        """初始化控制器"""
        try:
            model_config = {
                "model": self.model_name,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens
            }
            
            # 使用preset_running_config中的system_prefix（参考sage_server.py的实现）
            controller = SAgent(
                self._model, 
                model_config, 
                system_prefix=self.system_prefix,
                workspace=self.workspace,
                memory_root=self.memory_root
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
        if not message.get('show_content'):
            continue
            
        new_message = {
            'message_id': message.get('message_id', str(uuid.uuid4())),
            'role': 'assistant' if message['role'] != 'user' else 'user',
            'content': message.get('show_content')
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
    
    def __init__(self, controller: SAgent, component_manager: ComponentManager = None):
        self.controller = controller
        self.component_manager = component_manager
        self._current_stream = None
        self._current_stream_id = None
    
    def process_stream(self, 
                      messages: List[Dict[str, Any]], 
                      tool_manager: Union[ToolManager, ToolProxy],
                      session_id: Optional[str] = None,
                      use_deepthink: bool = True,
                      use_multi_agent: bool = True) -> List[Dict[str, Any]]:
        """处理消息流"""
        logger.debug("开始处理流式响应")
        
        new_messages = []
        
        # 准备preset配置参数
        system_context = None
        available_workflows = None
        max_loop_count = None
        
        if self.component_manager:
            system_context = self.component_manager.preset_system_context
            available_workflows = self.component_manager.preset_available_workflows
            max_loop_count = self.component_manager.preset_max_loop_count
        
        try:
            for chunk in self.controller.run_stream(
                messages,
                tool_manager,
                session_id=session_id,
                deep_thinking=use_deepthink,
                multi_agent=use_multi_agent,
                max_loop_count=max_loop_count,
                system_context=system_context,
                available_workflows=available_workflows
            ):
                # 将message chunk类型的chunks 转化成字典
                chunks_dict = [msg.to_dict() for msg in chunk]
                new_messages.extend(chunks_dict)
                self._update_display(messages, new_messages)
                
        except Exception as e:
            logger.error(traceback.format_exc())            
            error_response = {
                "role": "assistant",
                "content": f"流式处理出错: {str(e)}",
                "message_id": str(uuid.uuid4()),
            }
            new_messages.append(error_response)
        
        return new_messages
    
    def _update_display(self, base_messages: List[Dict], new_messages: List[Dict]):
        """更新显示内容"""
        merged_messages = MessageManager.merge_new_messages_to_old_messages(new_messages,base_messages.copy() )
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
        
        # 多智能体选项
        use_multi_agent = st.toggle('🤖 启用多智能体推理', 
                                   value=config.get('use_multi_agent', True))
        use_deepthink = st.toggle('🧠 启用深度思考', 
                                 value=config.get('use_deepthink', True))
        
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
    
    return use_multi_agent, use_deepthink


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
    st.rerun()


def init_session_state():
    """初始化会话状态"""
    if 'conversation' not in st.session_state:
        st.session_state.conversation = []
    if 'inference_conversation' not in st.session_state:
        st.session_state.inference_conversation = []
    if 'components_initialized' not in st.session_state:
        st.session_state.components_initialized = False


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
    
    # 处理流式响应
    new_messages = streaming_handler.process_stream(
        st.session_state.inference_conversation.copy(),
        tool_manager,
        session_id=None,
        use_deepthink=st.session_state.get('use_deepthink', True),
        use_multi_agent=st.session_state.get('use_multi_agent', True)
    )
    
    # 合并消息
    if new_messages:
        merged_messages = MessageManager.merge_new_messages_to_old_messages(
            new_messages,st.session_state.inference_conversation 
        )
        merged_messages_dict = [msg.to_dict() for msg in merged_messages]
        st.session_state.inference_conversation = merged_messages_dict
        
        # 更新显示对话
        display_messages = convert_messages_for_show(merged_messages_dict)
        st.session_state.conversation = display_messages
        
        logger.info("响应生成完成")

def run_web_demo(api_key: str, model_name: str = None, base_url: str = None, 
                 max_tokens: int = None, temperature: float = None,
                 workspace: str = None, memory_root: str = None, mcp_config: str = None,
                 preset_running_config: str = None, logs_dir: str = None, 
                 host: str = None, port: int = None):
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
        'workspace': workspace,
        'memory_root': memory_root,
        'mcp_config': mcp_config,
        'preset_running_config': preset_running_config,
        'logs_dir': logs_dir
    }
    # 设置界面（此时能获取到正确的配置）
    use_multi_agent, use_deepthink = setup_ui(config)
    
    # 存储设置到会话状态
    st.session_state.use_multi_agent = use_multi_agent
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
                    workspace=workspace,
                    memory_root=memory_root,
                    mcp_config=mcp_config,
                    preset_running_config=preset_running_config,
                    logs_dir=logs_dir
                )
                tool_manager, controller = asyncio.run(component_manager.initialize())
                st.session_state.tool_manager = tool_manager
                st.session_state.controller = controller
                st.session_state.component_manager = component_manager
                st.session_state.components_initialized = True
                st.session_state.config_updated = True  # 标记配置已更新
            st.success("系统初始化完成！")
            # 打印已注册工具，便于调试
            print("已注册工具：", [t['name'] for t in tool_manager.list_tools_simplified()])
            # 初始化完成后重新运行，确保UI显示更新后的配置
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
    parser = argparse.ArgumentParser(
        description='Sage Multi-Agent Interactive Chat',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  python sage_demo.py --default_llm_api_key YOUR_API_KEY
  python sage_demo.py --default_llm_api_key YOUR_API_KEY --default_llm_model_name gpt-4
        """
    )
    
    # 与 sage_server.py 保持一致的参数
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
    parser.add_argument('--host', default='0.0.0.0',
                       help='Server Host')
    parser.add_argument('--port', default=8001, type=int,
                       help='Server Port')
    
    parser.add_argument('--mcp_config', default='mcp_setting.json',
                       help='MCP配置文件路径')
    parser.add_argument('--workspace', default='sage_demo_workspace',
                       help='工作空间目录')
    parser.add_argument('--logs_dir', default='logs',
                       help='日志目录')
    parser.add_argument('--preset_running_config', default='',
                       help='预设配置，system_context，以及workflow，与接口中传过来的合并使用')
    parser.add_argument('--memory_root', default=None,
                       help='记忆存储根目录（可选）')
    
    
    
    args = parser.parse_args()
    
    # 处理workspace路径
    if args.workspace:
        args.workspace = os.path.abspath(args.workspace)
    
    return {
        'api_key': args.default_llm_api_key,
        'model_name': args.default_llm_model_name,
        'base_url': args.default_llm_api_base_url,
        'max_tokens': args.default_llm_max_tokens,
        'temperature': args.default_llm_temperature,
        'host': args.host,
        'port': args.port,
        'mcp_config': args.mcp_config,
        'workspace': args.workspace,
        'logs_dir': args.logs_dir,
        'preset_running_config': args.preset_running_config,
        'memory_root': args.memory_root
    }


def main():
    """主函数"""
    try:
        # 解析配置
        config = parse_arguments()
        logger.info(f"启动应用，模型: {config['model_name']}")
        
        # 运行 Web 演示
        run_web_demo(
            config['api_key'],
            config['model_name'],
            config['base_url'],
            config['max_tokens'],
            config['temperature'],
            config['workspace'],
            config['memory_root'],
            config['mcp_config'],
            config['preset_running_config'],
            config['logs_dir'],
            config['host'],
            config['port']
        )
        
            
    except Exception as e:
        logger.error(f"应用启动失败: {str(e)}")
        logger.error(traceback.format_exc())
        
        st.error(f"应用启动失败: {str(e)}")
        
        with st.expander("🔍 查看技术详情", expanded=False):
            st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
