"""
Sage Stream Service

基于 Sage 框架的智能体流式服务
提供简洁的 HTTP API 和 Server-Sent Events (SSE) 实时通信
不做任何的配置以及设置的缓存，所有的配置都通过接口传入
"""

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
import uuid
import warnings
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Union

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel
# 添加 Sage 项目路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sagents.session_runtime import get_global_session_manager
from sagents.sagents import SAgent
from sagents.tool import ToolManager, ToolProxy
from sagents.skill import SkillManager, SkillProxy
from sagents.utils.auto_gen_agent import AutoGenAgentFunc
from sagents.utils.logger import logger
from sagents.utils.system_prompt_optimizer import SystemPromptOptimizer
from sagents.utils.evaluations.checkpoint_generation import CheckpointGenerationAgent
from sagents.utils.evaluations.score_evaluation import AgentScoreEvaluator


parser = argparse.ArgumentParser(description="Sage Stream Service")
# 新格式参数（推荐使用）
parser.add_argument("--default_llm_api_key", help="默认LLM API Key")
parser.add_argument("--default_llm_api_base_url", help="默认LLM API Base")
parser.add_argument("--default_llm_model_name", help="默认LLM API Model")
parser.add_argument("--default_llm_max_tokens", default=4096, type=int, help="默认LLM API Max Tokens")
parser.add_argument("--default_llm_temperature", default=0.2, type=float, help="默认LLM API Temperature")
parser.add_argument("--default_llm_max_model_len", default=54000, type=int, help="默认LLM 最大上下文")
parser.add_argument("--default_llm_top_p", default=0.9, type=float, help="默认LLM Top P")
parser.add_argument("--default_llm_presence_penalty", default=0.0, type=float, help="默认LLM Presence Penalty")

parser.add_argument("--host", default="0.0.0.0", help="Server Host")
parser.add_argument("--port", default=8001, type=int, help="Server Port")

parser.add_argument("--mcp-config", default="mcp_setting.json", help="MCP配置文件路径")
parser.add_argument("--workspace", default="agent_workspace", help="工作空间目录")
parser.add_argument("--skills-path", default=None, help="技能目录路径")
parser.add_argument("--logs-dir", default="logs", help="日志目录")
parser.add_argument("--preset_running_config", default="", help="预设配置，system_context，以及workflow，与接口中传过来的合并使用")
parser.add_argument("--memory_root", default=None, help="记忆存储根目录（已废弃，请使用 --memory_type）")
parser.add_argument("--memory_type", default="session", help="记忆类型: session | user")
parser.add_argument("--session-root", default=None, help="会话存储根目录，默认为 agent_workspace 同级目录下的 server_sessions")
parser.add_argument("--daemon", action="store_true", help="以守护进程模式运行")
parser.add_argument("--pid-file", default="sage_stream.pid", help="PID文件路径")
parser.add_argument("--context_history_ratio", type=float, default=0.2,
                    help='上下文预算管理器：历史消息的比例（0-1之间）')
parser.add_argument("--context_active_ratio", type=float, default=0.3,
                    help='上下文预算管理器：活跃消息的比例（0-1之间）')
parser.add_argument("--context_max_new_message_ratio", type=float, default=0.5,
                    help='上下文预算管理器：新消息的比例（0-1之间）')
parser.add_argument("--context_recent_turns", type=int, default=0,
                    help='上下文预算管理器：限制最近的对话轮数，0表示不限制')


server_args = parser.parse_args()

# 验证必需参数
required_args = ['default_llm_api_key', 'default_llm_api_base_url', 'default_llm_model_name']
missing_args = [arg for arg in required_args if getattr(server_args, arg) is None]
if missing_args:
    raise ValueError(f"必需参数缺失: 请提供 {', '.join(['--' + arg for arg in missing_args])}")

# 处理 default_llm_max_model_len 逻辑
if server_args.default_llm_max_model_len is None:
    server_args.default_llm_max_model_len = 54000
elif server_args.default_llm_max_model_len < 8000:
    server_args.default_llm_max_model_len = 54000

if server_args.workspace:
    server_args.workspace = os.path.abspath(server_args.workspace)
os.environ['PREFIX_FILE_WORKSPACE'] = server_args.workspace if server_args.workspace.endswith('/') else server_args.workspace+'/'

# 设置 MEMORY_ROOT_PATH 环境变量
memory_root_path = os.path.join(os.path.dirname(os.path.abspath(server_args.workspace)), 'memory')
os.environ.setdefault('MEMORY_ROOT_PATH', memory_root_path)

# 处理 memory_root 兼容性
if server_args.memory_root:
    os.environ["MEMORY_ROOT_PATH"] = server_args.memory_root
    logger.warning("memory_root 参数已废弃，请使用 memory_type 参数。已自动设置 MEMORY_ROOT_PATH 环境变量。")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    await initialize_system(server_args)
    yield
    # 关闭时清理
    await cleanup_system()

# 设置配置文件路径环境变量
os.environ['SAGE_MCP_CONFIG_PATH'] = server_args.mcp_config
# FastAPI 应用
app = FastAPI(
    title="Sage Stream Service",
    description="基于 Sage 框架的智能体流式服务",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 核心服务类
class SageStreamService:
    """
    基于 Sage 框架的流式服务
    提供智能体对话的流式处理能力
    """
    
    def __init__(self, model: Optional[AsyncOpenAI] = None, 
                        model_config: Optional[Dict[str, Any]] = None, 
                        tool_manager: Optional[Union[ToolManager, ToolProxy]] = None, 
                        skill_manager: Optional[Union[SkillManager, SkillProxy]] = None,
                        preset_running_config: Optional[Dict[str, Any]] = None,
                        workspace: Optional[str] = None,
                        memory_type: Optional[str] = "session",
                        context_budget_config: Optional[Dict[str, Any]] = None,
                        agent_id: Optional[str] = None,
                        virtual_workspace: Optional[str] = None):
        """
        初始化服务
        
        Args:
            model: OpenAI 客户端实例
            model_config: 模型配置字典
            tool_manager: 工具管理器实例
        """
        self.preset_running_config = preset_running_config or {}
        # 设置system_prefix
        if "system_prefix" in self.preset_running_config:
            self.preset_system_prefix = self.preset_running_config['system_prefix']
            logger.debug(f"使用预设system_prefix: {self.preset_system_prefix}")
        elif "systemPrefix" in self.preset_running_config:
            self.preset_system_prefix = self.preset_running_config['systemPrefix']
            logger.debug(f"使用预设systemPrefix: {self.preset_system_prefix}")
        else:
            self.preset_system_prefix = None
            logger.debug("未使用预设system_prefix")
        
        # 设置system_context
        if "system_context" in self.preset_running_config:
            self.preset_system_context = self.preset_running_config['system_context']
            logger.debug("使用预设system_context")
        elif "systemContext" in self.preset_running_config:
            self.preset_system_context = self.preset_running_config['systemContext']
            logger.debug("使用预设systemContext")
        else:
            self.preset_system_context = None
            logger.debug("未使用预设system_context")
        
        # 设置available_workflows
        if "available_workflows" in self.preset_running_config:
            self.preset_available_workflows = self.preset_running_config['available_workflows']
            logger.debug("使用预设available_workflows")
        elif "availableWorkflows" in self.preset_running_config:
            self.preset_available_workflows = self.preset_running_config['availableWorkflows']
            logger.debug("使用预设availableWorkflows")
        else:
            self.preset_available_workflows = None
            logger.debug("未使用预设available_workflows")
        
        # 设置available_tools
        if "available_tools" in self.preset_running_config:
            self.preset_available_tools = self.preset_running_config['available_tools']
            logger.debug("使用预设available_tools")
        elif "availableTools" in self.preset_running_config:
            self.preset_available_tools = self.preset_running_config['availableTools']
            logger.debug("使用预设availableTools")
        else:
            self.preset_available_tools = None
            logger.debug("未使用预设available_tools")
        
        # 设置max_loop_count
        if "max_loop_count" in self.preset_running_config:
            self.preset_max_loop_count = self.preset_running_config['max_loop_count']
            logger.debug(f"使用预设max_loop_count: {self.preset_max_loop_count}")
        elif "maxLoopCount" in self.preset_running_config:
            self.preset_max_loop_count = self.preset_running_config['maxLoopCount']
            logger.debug(f"使用预设maxLoopCount: {self.preset_max_loop_count}")
        else:
            self.preset_max_loop_count = None
            logger.debug("未使用预设max_loop_count")

#         "deepThinking": false,
#   "multiAgent": false,
        # 设置deepThinking
        if "deepThinking" in self.preset_running_config:
            self.preset_deep_thinking = self.preset_running_config['deepThinking']
            logger.debug(f"使用预设deepThinking: {self.preset_deep_thinking}")
        elif "deepThinking" in self.preset_running_config:
            self.preset_deep_thinking = self.preset_running_config['deepThinking']
            logger.debug(f"使用预设deepThinking: {self.preset_deep_thinking}")
        else:
            self.preset_deep_thinking = None
            logger.debug("未使用预设deepThinking")

        # 设置agent_mode
        if "agent_mode" in self.preset_running_config:
            self.preset_agent_mode = self.preset_running_config['agent_mode']
            logger.debug(f"使用预设agent_mode: {self.preset_agent_mode}")
        elif "agentMode" in self.preset_running_config:
            self.preset_agent_mode = self.preset_running_config['agentMode']
            logger.debug(f"使用预设agentMode: {self.preset_agent_mode}")
        else:
            self.preset_agent_mode = None
            logger.debug("未使用预设agent_mode")

        # 设置context_budget_config
        self.context_budget_config = context_budget_config
        
        # 设置 agent_id 和 virtual_workspace
        self.agent_id = agent_id or "server_agent"
        self.virtual_workspace = virtual_workspace or workspace or "/sage-workspace"

        # workspace 有可能是相对路径
        if workspace:
            workspace = os.path.abspath(workspace)
        else:
            workspace = os.path.abspath("agent_workspace")

        # 创建 Sage AgentController 实例
        # session_root_space 独立于 agent_workspace
        self.agent_workspace = workspace
        
        # 优先使用命令行参数指定的 session_root，否则使用默认值
        if server_args.session_root:
             self.session_root_space = os.path.abspath(server_args.session_root)
        else:
             self.session_root_space = os.path.join(os.path.dirname(os.path.abspath(workspace)), "server_sessions")
             
        os.makedirs(self.session_root_space, exist_ok=True)
        
        self.sage_controller = SAgent(
            session_root_space=self.session_root_space,
            enable_obs=True,
            sandbox_type='local'
        )
        self.tool_manager = tool_manager
        if self.preset_available_tools:
            if isinstance(self.tool_manager, ToolManager):
                self.tool_manager = ToolProxy(self.tool_manager, self.preset_available_tools)    
        
        self.skill_manager = skill_manager
        
        logger.info("SageStreamService 初始化完成")
    
    async def process_stream(self, messages, session_id=None, user_id=None, deep_thinking=None, 
                           max_loop_count=None, agent_mode=None, more_suggest=False,
                            system_context: Optional[Dict] = None, 
                           available_workflows: Optional[Dict] = None,
                           force_summary: bool=False,
                           custom_agents: Optional[List[Dict[str, Any]]] = None):
        """处理流式聊天请求"""
        logger.info(f"🚀 SageStreamService.process_stream 开始，会话ID: {session_id}")
        logger.info(f"📝 参数: deep_thinking={deep_thinking}, agent_mode={agent_mode}, messages_count={len(messages)}")
        if isinstance(deep_thinking, str):
            if deep_thinking == 'auto':
                deep_thinking = None
            if deep_thinking == 'off':
                deep_thinking = False
            if deep_thinking == 'on':
                deep_thinking = True
        
        
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
            
            # 直接调用同步的 run_stream 方法
            stream_result = self.sage_controller.run_stream(
                session_id=session_id,
                input_messages=messages,
                tool_manager=self.tool_manager,
                skill_manager=self.skill_manager,
                model=self.model,
                model_config=self.model_config,
                system_prefix=self.preset_system_prefix,
                host_workspace=self.agent_workspace,
                virtual_workspace=self.virtual_workspace,
                default_memory_type=self.memory_type,
                user_id=user_id,
                agent_id=self.agent_id,
                deep_thinking=deep_thinking if deep_thinking is not None else self.preset_deep_thinking,
                max_loop_count = max_loop_count if max_loop_count is not None else self.preset_max_loop_count ,
                agent_mode=agent_mode if agent_mode is not None else self.preset_agent_mode,
                # more_suggest = more_suggest,
                system_context=system_context,
                available_workflows=available_workflows,
                force_summary=force_summary,
                context_budget_config=self.context_budget_config,
                custom_sub_agents=custom_agents
            )
            
            logger.info("✅ run_stream 调用成功，开始处理结果...")
            
            # 处理返回的生成器
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
            
            logger.info(f"🏁 流式处理完成，总共处理了 {chunk_count} 个块")
                
        except GeneratorExit:
            logger.warning(f"🔌 process_stream: 客户端断开连接，会话ID: {session_id}")
            logger.warning("🔍 GeneratorExit 详情: 客户端在流式处理过程中断开了连接")
            logger.warning(f"📋 GeneratorExit 堆栈跟踪: {traceback.format_exc()}")
            # 重新抛出GeneratorExit，让上层处理
            raise
        except Exception as e:
            logger.error(f"❌ 流式处理异常: {e}")
            logger.error(f"🔍 异常类型: {type(e).__name__}")
            logger.error(f"📋 异常详情: {traceback.format_exc()}")
            error_result = {
                'type': 'error',
                'content': f"处理失败: {str(e)}",
                'role': 'assistant',
                'message_id': str(uuid.uuid4()),
                'session_id': session_id,
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

# 全局变量
default_stream_service: Optional[SageStreamService] = None
all_active_sessions_service_map: Dict[str, Dict[str, Any]] = {}
tool_manager: Optional[ToolManager] = None
default_model_client: Optional[AsyncOpenAI] = None


async def initialize_tool_manager():
    """异步初始化工具管理器"""
    # 创建工具管理器实例，但不自动发现工具
    manager = ToolManager.get_instance(is_auto_discover=False)

    # 手动进行基础工具发现
    manager.discover_tools_from_path()

    # 设置 MCP 配置路径
    manager._mcp_setting_path = os.environ.get('SAGE_MCP_CONFIG_PATH', 'mcp_setting.json')

    # 异步发现 MCP 工具
    await manager._discover_mcp_tools(mcp_setting_path=manager._mcp_setting_path)

    return manager

async def initialize_system(server_args):
    """初始化系统"""
    global default_stream_service, tool_manager, skill_manager, default_model_client
    
    logger.info("正在初始化 Sage Stream Service...")
    
    try:
        # 初始化模型客户端
        if server_args.default_llm_api_key:
            logger.info(f"默认 API 密钥: {server_args.default_llm_api_key}...")
            logger.info(f"默认 API 基础 URL: {server_args.default_llm_api_base_url}...")
            default_model_client = AsyncOpenAI(
                api_key=server_args.default_llm_api_key,
                base_url=server_args.default_llm_api_base_url
            )
            default_model_client.model = server_args.default_llm_model_name
            logger.info(f"默认模型客户端初始化成功: {server_args.default_llm_model_name}")
        else:
            logger.warning("未配置默认 API 密钥，某些功能可能不可用")
        
        # 初始化工具管理器
        try:
            tool_manager = await initialize_tool_manager()
            logger.info("工具管理器初始化成功")
        except Exception as e:
            logger.warning(f"工具管理器初始化失败: {e}")
            logger.error(traceback.format_exc())
            tool_manager = None
        
        # 初始化技能管理器
        try:
            skill_dirs = [server_args.skills_path] if server_args.skills_path else None
            skill_manager = SkillManager(skill_dirs=skill_dirs)
            logger.info("技能管理器初始化成功")
        except Exception as e:
            logger.warning(f"技能管理器初始化失败: {e}")
            logger.error(traceback.format_exc())
            skill_manager = None

        # 初始化流式服务
        if default_model_client:
            # 从配置中构建模型配置字典
            model_config_dict = {
                'model': server_args.default_llm_model_name,
                'max_tokens': server_args.default_llm_max_tokens,
                'temperature': server_args.default_llm_temperature,
                'top_p': server_args.default_llm_top_p,
                'presence_penalty': server_args.default_llm_presence_penalty
            }

            if server_args.preset_running_config:
                if os.path.exists(server_args.preset_running_config):
                    with open(server_args.preset_running_config, 'r') as f:
                        preset_running_config = json.load(f)
                else:
                    preset_running_config = {}
            else:
                preset_running_config = {}

            # 构建context_budget_config字典
            # max_model_len统一使用default_llm_max_model_len
            context_budget_config = {
                'max_model_len': server_args.default_llm_max_model_len
            }
            if server_args.context_history_ratio is not None:
                context_budget_config['history_ratio'] = server_args.context_history_ratio
            if server_args.context_active_ratio is not None:
                context_budget_config['active_ratio'] = server_args.context_active_ratio
            if server_args.context_max_new_message_ratio is not None:
                context_budget_config['max_new_message_ratio'] = server_args.context_max_new_message_ratio
            if server_args.context_recent_turns is not None:
                context_budget_config['recent_turns'] = server_args.context_recent_turns
            
            logger.info(f"使用context_budget_config: {context_budget_config}")

            default_stream_service = SageStreamService(
                model=default_model_client,
                model_config=model_config_dict,
                tool_manager=tool_manager,
                skill_manager=skill_manager,
                preset_running_config=preset_running_config,
                workspace=server_args.workspace,
                memory_type=server_args.memory_type,
                context_budget_config=context_budget_config
            )
            logger.info("默认 SageStreamService 初始化成功")
        else:
            logger.warning("模型客户端未配置，流式服务不可用")
            
    except Exception as e:
        logger.error(f"系统初始化失败: {e}")
        logger.error(traceback.format_exc())

def add_cors_headers(response):
    """添加 CORS 头"""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"

async def cleanup_system():
    """清理系统资源"""
    global default_stream_service, tool_manager, default_model_client
    
    logger.info("正在清理系统资源...")
    
    try:
        if tool_manager:
            # 清理工具管理器资源
            logger.info("清理工具管理器资源")
            
        default_stream_service = None
        tool_manager = None
        default_model_client = None
        
        logger.info("系统资源清理完成")
    except Exception as e:
        logger.error(f"系统资源清理失败: {e}")

# Pydantic 模型定义
class ChatMessage(BaseModel):
    role: Optional[str] = None
    content: Optional[Any] = None
    message_id: Optional[str] = None
    type: Optional[str] = "normal"
    tool_calls: Optional[List[Dict[str, Any]]] = None
    type: Optional[str] = None
    # 添加历史对话中可能存在的字段
    message_type: Optional[str] = None
    timestamp: Optional[Union[float, str]] = None
    chunk_id: Optional[str] = None
    is_final: Optional[bool] = None
    is_chunk: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None

class CustomSubAgentConfig(BaseModel):
    name: str
    system_prompt: Optional[str] = None
    description: Optional[str] = None
    available_tools: Optional[List[str]] = None
    available_skills: Optional[List[str]] = None
    available_workflows: Optional[Dict[str, List[str]]] = None
    system_context: Optional[Dict[str, Any]] = None

class StreamRequest(BaseModel):
    messages: List[ChatMessage]
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    deep_thinking: Optional[Union[bool, str]] = None
    max_loop_count: int = 10
    multi_agent: Optional[Union[bool, str]] = None
    agent_mode: Optional[str] = None # fibre, simple, multi
    summary : bool =True  # 过时字段
    deep_research: bool = True # 过时字段，与multi_agent一致
    more_suggest: bool = False
    force_summary: bool = False
    system_context: Optional[Dict[str, Any]] = None
    available_workflows: Optional[Dict[str, List[str]]] = None
    llm_model_config: Optional[Dict[str, Any]] = None
    system_prefix: Optional[str] = None
    available_tools: Optional[List[str]] = None
    available_skills: Optional[List[str]] = None # Added for skill restriction
    custom_sub_agents: Optional[List[CustomSubAgentConfig]] = None # Added for custom agents
    
    def __init__(self, **data):
        # 处理字段兼容性
        if 'deep_research' in data and 'multi_agent' not in data:
            data['multi_agent'] = data['deep_research']
            warnings.warn("deep_research字段已过时，请使用multi_agent", DeprecationWarning)
        
        if 'summary' in data:
            warnings.warn("summary字段已过时，将被忽略", DeprecationWarning)
            
        super().__init__(**data)


def get_local_ip() -> str:
    """
    获取本机的实际IP地址
    """
    import socket
    try:
        # 创建一个UDP socket连接到外部地址来获取本机IP
        # 这里使用8.8.8.8作为目标，但实际不会发送数据
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            return local_ip
    except Exception as e:
        logger.warning(f"无法获取本机IP地址，使用localhost: {e}")
        return "localhost"


def generate_curl_command(request: StreamRequest, host: str = "localhost", port: int = 8001) -> str:
    """
    根据StreamRequest生成对应的curl命令
    """
    import json
    
    # 构建请求体
    request_data = request.dict()
    
    # 构建curl命令
    curl_command = f"""curl -X POST "http://{host}:{port}/api/stream" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(request_data, ensure_ascii=False, indent=2)}'"""
    
    return curl_command


def save_curl_command_to_session(curl_command: str, session_id: str, workspace_root: str):
    """
    将curl命令保存到指定session的工作空间文件夹中
    """
    import os
    from datetime import datetime
    
    try:
        # 构建session文件夹路径
        session_folder = os.path.join(workspace_root, session_id)
        
        # 确保session文件夹存在
        os.makedirs(session_folder, exist_ok=True)
        
        # 生成带时间戳的文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        curl_file_path = os.path.join(session_folder, f"curl_command_{timestamp}.txt")
        
        # 保存curl命令到文件
        with open(curl_file_path, 'w', encoding='utf-8') as f:
            f.write(curl_command)
        
        logger.info(f"Curl command saved to: {curl_file_path}")
        return curl_file_path
        
    except Exception as e:
        logger.error(f"Failed to save curl command: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


class ConfigRequest(BaseModel):
    api_key: str
    model_name: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    max_tokens: Optional[int] = 4096
    temperature: Optional[float] = 0.7

class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    type: str  # 工具类型：basic, mcp, agent
    source: str  # 工具来源

class SystemStatus(BaseModel):
    status: str
    service_name: str = "SageStreamService"
    tools_count: int
    active_sessions: int
    version: str = "1.0"

class InterruptRequest(BaseModel):
    message: str = "用户请求中断"

class AutoGenAgentRequest(BaseModel):
    """自动生成Agent配置的请求模型"""
    agent_description: str  # Agent描述
    available_tools: Optional[List[str]] = None  # 可选的工具名称列表，如果提供则只使用这些工具

class AutoGenAgentResponse(BaseModel):
    """自动生成Agent响应"""
    success: bool
    message: str
    agent_config: Optional[Dict[str, Any]] = None

class SystemPromptOptimizeRequest(BaseModel):
    """系统提示词优化请求"""
    original_prompt: str  # 原始系统提示词
    optimization_goal: Optional[str] = None  # 优化目标（可选）

class SystemPromptOptimizeResponse(BaseModel):
    """系统提示词优化响应"""
    success: bool
    message: str
    optimized_prompt: Optional[str] = None  # 优化后的提示词
    optimization_details: Optional[Dict[str, Any]] = None  # 优化详情


class ScoreEvaluationRequest(StreamRequest):
    """评估打分请求"""
    checkpoints: list| dict

@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "service": "ReagentStreamService"
    }

@app.get("/api/tools", response_model=List[ToolInfo])
async def get_tools(response: Response):
    """获取可用工具列表"""
    add_cors_headers(response)
    
    try:
        tools = []
        
        if tool_manager:
            available_tools = tool_manager.list_tools_with_type()
            
            for tool_info in available_tools:
                tools.append(ToolInfo(
                    name=tool_info.get("name", ""),
                    description=tool_info.get("description", ""),
                    parameters=tool_info.get("parameters", {}),
                    type=tool_info.get("type", "basic"),
                    source=tool_info.get("source", "internal")
                ))
        
        return tools
    except Exception as e:
        logger.error(f"获取工具列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取工具列表失败: {str(e)}")

@app.post("/api/stream")
async def stream_chat(request: StreamRequest):
    """流式聊天接口"""
    if not default_stream_service:
        raise HTTPException(status_code=503, detail="服务未配置或不可用")
    # 记录请求开始时间，用于首token耗时统计
    api_request_start_time = time.time()

    logger.info(f"Server: 请求参数: {request}")
    # 生成会话ID
    # llm_model_config={'model': '', 'maxTokens': '', 'temperature': ''}
    # 如果是value 是空，删除key
    if request.llm_model_config:
        request.llm_model_config = {k: v for k, v in request.llm_model_config.items() if v is not None and v != ''}

    # 清洗 system_prefix，如果等于前端旧版默认值，则置为 None，以便触发后端的增强默认 Prompt
    if request.system_prefix == 'You are a helpful AI assistant.':
        logger.info("检测到默认 system_prefix，已自动清除以启用后端增强 Prompt")
        request.system_prefix = None

    session_id = request.session_id or str(uuid.uuid4())
    logger.info(f"📥 API请求开始: 会话ID: {session_id}, 开始时间戳: {api_request_start_time:.3f}")
    
    # 生成并保存curl命令到session文件夹
    try:
        # 如果host是0.0.0.0，则使用本机实际IP地址
        actual_host = get_local_ip() if server_args.host == "0.0.0.0" else server_args.host
        curl_command = generate_curl_command(request, actual_host, server_args.port)
        save_curl_command_to_session(curl_command,session_id , server_args.workspace)
        logger.info(f"已保存curl命令到session {session_id}")
    except Exception as e:
        logger.error(f"保存curl命令失败: {e}")
        import traceback
        traceback.print_exc()
    # 判断是否要初始化新的 sage service 还是使用默认的
    # 取决于是否需要自定义模型以及 agent 的system prefix ，以及对tool 的工具是否有限制
    if request.llm_model_config or request.system_prefix or request.available_tools or request.available_skills:
        llm_config_dict = request.llm_model_config or {}
        # 根据model config 初始化新的模型客户端
        logger.info(f"初始化新的模型客户端，模型配置api_key :{llm_config_dict.get('api_key', server_args.default_llm_api_key)}")
        logger.info(f"初始化新的模型客户端，模型配置base_url :{llm_config_dict.get('base_url', server_args.default_llm_api_base_url)}")
        logger.info(f"初始化新的模型客户端，模型配置model :{llm_config_dict.get('model', server_args.default_llm_model_name)}")
        model_client = AsyncOpenAI(
            api_key=llm_config_dict.get('api_key', server_args.default_llm_api_key),
            base_url=llm_config_dict.get('base_url', server_args.default_llm_api_base_url),
        )
        llm_model_config = {
            'model': llm_config_dict.get('model', server_args.default_llm_model_name)
        }
        
        # 只有在有有效的max_tokens值时才添加该键，避免None值导致错误
        max_tokens_value = llm_config_dict.get('max_tokens', server_args.default_llm_max_tokens)
        max_model_len = llm_config_dict.get('max_model_len', server_args.default_llm_max_model_len)
        if max_tokens_value is not None:
            llm_model_config['max_tokens'] = int(max_tokens_value)
            
        # 只有在有有效的temperature值时才添加该键，避免None值导致错误
        temperature_value = llm_config_dict.get('temperature', server_args.default_llm_temperature)
        if temperature_value is not None:
            llm_model_config['temperature'] = float(temperature_value)
        
        top_p_value = llm_config_dict.get('top_p', server_args.default_llm_top_p)
        if top_p_value is not None:
            llm_model_config['top_p'] = float(top_p_value)
        
        presence_penalty_value = llm_config_dict.get('presence_penalty', server_args.default_llm_presence_penalty)
        if presence_penalty_value is not None:
            llm_model_config['presence_penalty'] = float(presence_penalty_value)
        
        
        
        logger.info(f"初始化模型客户端，模型配置: {llm_model_config}")

        if request.available_tools is not None:
            logger.info(f"初始化工具代理，可用工具: {request.available_tools}")
            start_tool_proxy = time.time()
            # 如果request.multi_agent 是true，要确保request.available_tools没有 complete_task 这个工具
            if request.multi_agent and 'complete_task' in request.available_tools:
                request.available_tools.remove('complete_task')
            tool_proxy = ToolProxy(tool_manager,request.available_tools)
            end_tool_proxy = time.time()
            logger.info(f"初始化工具代理耗时: {end_tool_proxy - start_tool_proxy} 秒")
        else:
            tool_proxy = tool_manager

        if request.available_skills is not None:
            logger.info(f"初始化技能代理，可用技能: {request.available_skills}")
            start_skill_proxy = time.time()
            skill_proxy = SkillProxy(skill_manager, request.available_skills)
            end_skill_proxy = time.time()
            logger.info(f"初始化技能代理耗时: {end_skill_proxy - start_skill_proxy} 秒")
        else:
            skill_proxy = skill_manager

        start_stream_service = time.time()
        # 构建context_budget_config字典
        # max_model_len统一使用请求中的max_model_len（如果提供）或default_llm_max_model_len
        context_budget_config = {
            'max_model_len': max_model_len
        }
        if server_args.context_history_ratio is not None:
            context_budget_config['history_ratio'] = server_args.context_history_ratio
        if server_args.context_active_ratio is not None:
            context_budget_config['active_ratio'] = server_args.context_active_ratio
        if server_args.context_max_new_message_ratio is not None:
            context_budget_config['max_new_message_ratio'] = server_args.context_max_new_message_ratio
        if server_args.context_recent_turns is not None:
            context_budget_config['recent_turns'] = server_args.context_recent_turns
        
        # 初始化新的 sage service
        stream_service = SageStreamService(
            model=model_client,
            model_config=llm_model_config,
            tool_manager=tool_proxy,
            skill_manager=skill_proxy,
            preset_running_config={
                "system_prefix": request.system_prefix
            },
            workspace=server_args.workspace,
            memory_type=server_args.memory_type,
            context_budget_config=context_budget_config
        )
        end_stream_service = time.time()
        logger.info(f"初始化流式服务耗时: {end_stream_service - start_stream_service} 秒")
        all_active_sessions_service_map[session_id] = {
            'stream_service': stream_service,
            'session_id': session_id,
            "is_default": False
        }
    else:
        logger.info(f"使用默认的流式服务，会话ID: {session_id}")
        # 使用默认的 sage service
        stream_service = default_stream_service
        # 记录会话ID
        all_active_sessions_service_map[session_id] = {
            'stream_service': stream_service,
            'session_id': session_id,
            "is_default": True
        }

    async def generate_stream(stream_service):
        """生成SSE流"""
        try:
            # 直接转换消息格式，不进行内容调整
            messages = []
            for msg in request.messages:
                # 保持原始消息的所有字段
                message_dict = msg.model_dump()
                # 如果有content 一定要转化成str
                if message_dict.get('content'):
                    message_dict['content'] = str(message_dict['content'])
                messages.append(message_dict)
            
            logger.info(f"开始流式处理，会话ID: {session_id}")
            
            # 打印请求体内容
            logger.info(f"请求体内容: {request}")
            
            # 添加流处理计数器和连接状态跟踪
            stream_counter = 0
            last_activity_time = time.time()
            # 首个token返回耗时标记
            first_token_logged = False
            
            # 处理流式响应，传递所有参数
            async for result in stream_service.process_stream(
                messages=messages, 
                session_id=session_id,
                user_id=request.user_id,
                deep_thinking=request.deep_thinking,
                max_loop_count=request.max_loop_count,
                multi_agent=request.multi_agent,
                agent_mode=request.agent_mode,
                more_suggest=request.more_suggest,
                system_context=request.system_context,
                available_workflows=request.available_workflows,
                force_summary=request.force_summary,
                custom_sub_agents=[agent.model_dump() for agent in request.custom_sub_agents] if request.custom_sub_agents else None
            ):
                # 更新流处理计数器和活动时间
                stream_counter += 1
                current_time = time.time()
                time_since_last = current_time - last_activity_time
                last_activity_time = current_time
                
                # 每100个结果记录一次连接状态
                if stream_counter % 100 == 0:
                    logger.info(f"📊 流处理状态 - 会话: {session_id}, 计数: {stream_counter}, 间隔: {time_since_last:.3f}s")
                
                # 处理大JSON的分块传输
                try:
                    json_str = json.dumps(result, ensure_ascii=False)
                    json_size = len(json_str)
                    
                    # 对于超大JSON，使用分块发送确保完整性
                    if json_size > 32768:  # 32KB以上使用分块发送
                        logger.info(f"🔄 大JSON分块发送: {json_size} 字符")
                        
                        # 分块发送大JSON
                        chunk_size = 8192  # 8KB per chunk
                        total_chunks = (json_size + chunk_size - 1) // chunk_size
                        
                        # 发送分块开始标记
                        start_marker = {
                            'type': 'chunk_start',
                            'message_id': result.get('message_id', 'unknown'),
                            'total_size': json_size,
                            'total_chunks': total_chunks,
                            'chunk_size': chunk_size,
                            'original_type': result.get('type', 'unknown')
                        }
                        # 首个token耗时日志（首次yield前）
                        if not first_token_logged:
                            first_latency = time.time() - api_request_start_time
                            logger.info(f"⏱️ 首token响应耗时: {first_latency:.3f}s，会话ID: {session_id}")
                            first_token_logged = True
                        yield json.dumps(start_marker, ensure_ascii=False) + "\n"
                        await asyncio.sleep(0.01)  # 延迟确保前端准备好
                        
                        for i in range(total_chunks):
                            start = i * chunk_size
                            end = min(start + chunk_size, json_size)
                            chunk_data = json_str[start:end]
                            
                            # 创建分块消息
                            chunk_message = {
                                'type': 'json_chunk',
                                'message_id': result.get('message_id', 'unknown'),  # 添加message_id字段
                                'chunk_id': f"{result.get('message_id', 'unknown')}_{i}",
                                'chunk_index': i,
                                'total_chunks': total_chunks,
                                'chunk_data': chunk_data,
                                'chunk_size': len(chunk_data),
                                'is_final': i == total_chunks - 1,
                                'checksum': hash(chunk_data) % 1000000
                            }
                            # 首个token耗时日志（首次yield前）
                            if not first_token_logged:
                                first_latency = time.time() - api_request_start_time
                                logger.info(f"⏱️ 首token响应耗时: {first_latency:.3f}s，会话ID: {session_id}")
                                first_token_logged = True
                            yield json.dumps(chunk_message, ensure_ascii=False) + "\n"
                            await asyncio.sleep(0.005)  # 适中延迟确保顺序
                        
                        # 发送分块结束标记
                        end_marker = {
                            'type': 'chunk_end',
                            'message_id': result.get('message_id', 'unknown'),
                            'total_chunks': total_chunks,
                            'expected_size': json_size,
                            'original_type': result.get('type', 'unknown')
                        }
                        yield json.dumps(end_marker, ensure_ascii=False) + "\n"
                        
                        logger.info(f"✅ 完成分块发送: {total_chunks} 块")
                    else:
                        # 小JSON直接发送
                        # 首个token耗时日志（首次yield前）
                        if not first_token_logged:
                            first_latency = time.time() - api_request_start_time
                            logger.info(f"⏱️ 首token响应耗时: {first_latency:.3f}s，会话ID: {session_id}")
                            first_token_logged = True
                        yield json.dumps(result, ensure_ascii=False) + "\n"
                        
                except Exception as e:
                    logger.error(f"JSON序列化失败: {e}")
                    # 创建错误响应
                    error_data = {
                        'type': 'error',
                        'message_id': result.get('message_id', 'error'),
                        'content': f'数据处理错误: {str(e)}',
                        'original_size': len(str(result)),
                        'error': True
                    }
                    # 首个token耗时日志（首次yield前）
                    if not first_token_logged:
                        first_latency = time.time() - api_request_start_time
                        logger.info(f"⏱️ 首token响应耗时: {first_latency:.3f}s，会话ID: {session_id}")
                        first_token_logged = True
                    yield json.dumps(error_data, ensure_ascii=False) + "\n"
                    
                await asyncio.sleep(0.01)  # 避免过快发送
            # 发送流结束标记
            end_data = {
                'type': 'stream_end',
                'session_id': session_id,
                'timestamp': time.time(),
                'total_stream_count': stream_counter
            }
            # token_usage 现在通过特殊的 MessageChunk 在 run_stream 的 finally 块中返回
            # 这里不再需要额外处理 token_usage
            total_duration = time.time() - (last_activity_time - time_since_last if 'time_since_last' in locals() else last_activity_time)
            logger.info(f"✅ 完成流式处理: 会话 {session_id}, 总计 {stream_counter} 个流结果, 耗时 {total_duration:.3f}s")
            logger.info(f"✅ 流结束数据: {end_data}")
            yield json.dumps(end_data, ensure_ascii=False) + "\n"
        
        except GeneratorExit as ge:
            import sys
            disconnect_msg = f"🔌 [GENERATOR_EXIT] 客户端断开连接，生成器被关闭 - 会话ID: {session_id}, 时间: {time.time()}"
            logger.error(disconnect_msg)
            logger.error(f"🔍 [GENERATOR_EXIT] GeneratorExit详情: {type(ge).__name__} - {str(ge)}")
            logger.error(f"📋 [GENERATOR_EXIT] 堆栈跟踪: {traceback.format_exc()}")
            logger.error(f"📊 [GENERATOR_EXIT] 流处理统计: 已处理 {stream_counter if 'stream_counter' in locals() else 0} 个流结果")
            # 强制刷新日志缓冲区
            sys.stdout.flush()
            sys.stderr.flush()
            
        except Exception as e:
            logger.error(f"流式处理异常: {e}")
            logger.error(traceback.format_exc())
            error_data = {
                'type': 'error',
                'message': str(e),
                'session_id': session_id
            }
            yield json.dumps(error_data, ensure_ascii=False) + "\n"
        finally:
            logger.info('server generate_stream finally save info and delete')
            # 清理会话资源
            if session_id in all_active_sessions_service_map:
                stream_service = all_active_sessions_service_map[session_id]['stream_service']
                if stream_service:
                    if stream_service.save_session(session_id):
                        logger.info(f"会话 {session_id} 状态已保存")
                    else:
                        logger.error(f"会话 {session_id} 保存失败，已经保存")
                del all_active_sessions_service_map[session_id]
                logger.info(f"会话 {session_id} 资源已清理")
    
    return StreamingResponse(
        generate_stream(stream_service),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
    )

@app.post("/api/sessions/{session_id}/interrupt")
async def interrupt_session(session_id: str, request: Optional[InterruptRequest] = None):
    """中断指定会话"""
    session_info = all_active_sessions_service_map.get(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail="会话不存在")

    stream_service = session_info['stream_service']

    if not stream_service:
        raise HTTPException(status_code=503, detail="服务未配置或不可用")
    try:
        message = request.message if request else "用户请求中断"
        success = stream_service.interrupt_session(session_id, message)
        
        if success:
            logger.info(f"会话 {session_id} 中断成功")
            return {
                "status": "success",
                "message": f"会话 {session_id} 已中断",
                "session_id": session_id
            }
        else:
            return {
                "status": "not_found",
                "message": f"会话 {session_id} 不存在或已结束",
                "session_id": session_id
            }
    except Exception as e:
        logger.error(f"中断会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"中断会话失败: {str(e)}")

# 获取指定seesion id 的当前的任务管理器中的任务状态信息
@app.post("/api/sessions/{session_id}/tasks_status")
async def get_session_status(session_id: str):
    """获取指定会话的状态"""
    session_info = all_active_sessions_service_map.get(session_id)
    if not session_info:
        return {
            "status": "not_found",
            "message": f"会话 {session_id} 已完成或者不存在",
            "session_id": session_id,
            "tasks_status": None
        }
    stream_service = session_info['stream_service']
    tasks_status = stream_service.sage_controller.get_tasks_status(session_id)
    tasks_status['tasks']
    logger.info(f"获取会话 {session_id} 任务数量：{len(tasks_status['tasks'])}")
    return {
        "status": "success",
        "message": f"会话 {session_id} 状态获取成功",
        "session_id": session_id,
        "tasks_status": tasks_status
    }


@app.post("/api/sessions/{session_id}/file_workspace")
async def get_file_workspace(session_id: str):
    session_info = all_active_sessions_service_map.get(session_id)
    if not session_info:
        return {
            "status": "success",
            "message": f"会话 {session_id} 已完成或者不存在",
            "session_id": session_id,
            "files": []
        }
    try:
        session_manager = get_global_session_manager()
        session_context = session_manager.get(session_id).session_context
    except Exception:
        return {
            "status": "success",
            "message": f"会话 {session_id} 已完成或者不存在",
            "session_id": session_id,
            "files": []
        }
    # 这个会话的工作空间的，绝对路径
    workspace_path = session_context.agent_workspace
    
    if not os.path.exists(workspace_path):
        return {
            "status": "success",
            "message": "工作空间为空",
            "session_id": session_id,
            "files": []
        }
    
    files = []
    try:
        for root, dirs, filenames in os.walk(workspace_path):
            for filename in filenames:
                file_path = os.path.join(root, filename)
                # 计算相对于工作空间的路径
                relative_path = os.path.relpath(file_path, workspace_path)
                file_stat = os.stat(file_path)
                files.append({
                    "name": filename,
                    "path": relative_path,
                    "size": file_stat.st_size,
                    "modified_time": file_stat.st_mtime,
                    "is_directory": False
                })
            
            for dirname in dirs:
                dir_path = os.path.join(root, dirname)
                relative_path = os.path.relpath(dir_path, workspace_path)
                files.append({
                    "name": dirname,
                    "path": relative_path,
                    "size": 0,
                    "modified_time": os.stat(dir_path).st_mtime,
                    "is_directory": True
                })
        logger.info(f"获取会话 {session_id} 工作空间文件数量：{len(files)}")
        return {
            "status": "success",
            "message": "获取文件列表成功",
            "session_id": session_id,
            "files": files,
            "agent_workspace": session_context.agent_workspace
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"获取文件列表失败: {str(e)}",
            "session_id": session_id,
            "files": []
        }

# 指定agent workspace 以及file 进行下载
@app.get("/api/sessions/file_workspace/download")
async def download_file(request: Request):
    """下载工作空间中的指定文件"""
    file_path = request.query_params.get("file_path")
    workspace_path = request.query_params.get("workspace_path")
    
    if not file_path or not workspace_path:
        raise HTTPException(status_code=400, detail="缺少必要的参数: file_path 或 workspace_path")
    
    # 构建完整的文件路径
    full_file_path = os.path.join(workspace_path, file_path)
    
    # 安全检查：确保文件路径在工作空间内
    if not os.path.abspath(full_file_path).startswith(os.path.abspath(workspace_path)):
        raise HTTPException(status_code=403, detail="访问被拒绝：文件路径超出工作空间范围")
    
    # 检查文件是否存在
    if not os.path.exists(full_file_path):
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")
    
    # 检查是否为文件（不是目录）
    if not os.path.isfile(full_file_path):
        raise HTTPException(status_code=400, detail=f"路径不是文件: {file_path}")
    
    try:
        # 返回文件内容
        return FileResponse(
            path=full_file_path,
            filename=os.path.basename(file_path),
            media_type='application/octet-stream'
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载文件失败: {str(e)}")

class ExecToolRequest(BaseModel):
    tool_name: str
    tool_params: Dict[str, Any]

@app.post("/api/tools/exec")
async def exec_tool(request: ExecToolRequest):
    """执行工具"""
    logger.info(f"执行工具请求: {request}")
    try:
        if not tool_manager:
            logger.error("工具管理器未初始化")
            return {"status": "error", "message": "工具管理器未初始化"}

        # 检测工具是否存在
        if request.tool_name not in tool_manager.tools.keys():
            logger.error(f"执行工具失败: {request.tool_name}")
            return {"status": "error", "message": "工具不存在"}

        tool_response = tool_manager.run_tool(
                tool_name=request.tool_name,
                session_context=None,
                session_id="",
                **request.tool_params
            )
        if tool_response:
            logger.info(f"执行工具成功: {request.tool_name}")
            return {"status": "success", "message": "工具执行成功", "data": tool_response}
        else:
            logger.error(f"执行工具失败: {request.tool_name}")
            return {"status": "error", "message": "工具执行失败"}
    except Exception as e:
        logger.error(f"执行工具失败: {e}")
        raise HTTPException(status_code=500, detail=f"执行工具失败: {str(e)}")


class MCPServerRequest(BaseModel):
    name: str
    streaming_http_url: Optional[str] = None
    sse_url: Optional[str] = None
    api_key: Optional[str] = None
    disabled: bool = False

@app.post("/api/agent/auto-generate", response_model=AutoGenAgentResponse)
async def auto_generate_agent(request: AutoGenAgentRequest):
    """
    自动生成Agent配置的API接口
    
    根据Agent描述和工具管理器自动生成Agent配置
    """
    start_time = time.time()
    logger.info(f"开始处理Agent自动生成请求，描述长度: {len(request.agent_description)}")
    
    try:
        # 使用服务器默认的LLM客户端
        global default_model_client, tool_manager
        
        if default_model_client is None:
            logger.error("默认LLM客户端未初始化")
            return AutoGenAgentResponse(
                success=False,
                message="默认LLM客户端未初始化"
            )
        
        if tool_manager is None:
            logger.error("工具管理器未初始化")
            return AutoGenAgentResponse(
                success=False,
                message="工具管理器未初始化"
            )
        
        logger.info(f"使用模型: {server_args.default_llm_model_name}")
        logger.info(f"可用工具数量: {len(tool_manager.tools)}")
        
        # 创建AutoGenAgentFunc实例
        auto_gen_agent = AutoGenAgentFunc()
        
        # 根据是否提供工具列表决定使用ToolManager还是ToolProxy
        if request.available_tools:
            logger.info(f"使用指定的工具列表: {request.available_tools}")
            # 创建ToolProxy，只包含指定的工具
            tool_proxy = ToolProxy(tool_manager, request.available_tools)
            tool_manager_or_proxy = tool_proxy
        else:
            logger.info("使用完整的工具管理器")
            tool_manager_or_proxy = tool_manager
        
        # 生成Agent配置，使用服务器默认配置
        logger.info("开始调用AutoGenAgentFunc生成配置")
        agent_config = await auto_gen_agent.generate_agent_config(
            agent_description=request.agent_description,
            tool_manager=tool_manager_or_proxy,
            llm_client=default_model_client,
            model=server_args.default_llm_model_name
        )
        
        if agent_config is None:
            logger.error("AutoGenAgentFunc返回None")
            return AutoGenAgentResponse(
                success=False,
                message="生成Agent配置失败"
            )
        
        elapsed_time = time.time() - start_time
        logger.info(f"Agent配置生成成功，耗时: {elapsed_time:.2f}秒")
        
        return AutoGenAgentResponse(
            success=True,
            message="Agent配置生成成功",
            agent_config=agent_config
        )
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error(f"自动生成Agent配置失败，耗时: {elapsed_time:.2f}秒，错误: {str(e)}")
        logger.error(traceback.format_exc())
        return AutoGenAgentResponse(
            success=False,
            message=f"生成失败: {str(e)}"
        )

@app.post("/api/mcp/add")
async def add_mcp_server(request: MCPServerRequest, response: Response):
    """添加MCP server到tool manager"""
    add_cors_headers(response)
    
    try:
        global tool_manager, default_stream_service
        
        if not tool_manager:
            raise HTTPException(status_code=503, detail="工具管理器未初始化")
        
        logger.info(f"开始添加MCP server: {request.name}")
        
        # 添加新的MCP server配置
        server_config: Dict[str, Any] = {
            "disabled": request.disabled
        }
        if request.streaming_http_url:
            server_config["streaming_http_url"] = request.streaming_http_url
        if request.sse_url:
            server_config["sse_url"] = request.sse_url
        if request.api_key:
            server_config["api_key"] = request.api_key
        
        # 添加新的MCP server到工具管理器
        success = tool_manager.register_mcp_server(request.name, server_config)
        if success:
            # 读取现有的MCP配置
            mcp_config_path = server_args.mcp_config
            if os.path.exists(mcp_config_path):
                with open(mcp_config_path, 'r', encoding='utf-8') as f:
                    mcp_config = json.load(f)
            else:
                mcp_config = {"mcpServers": {}}
            
            mcp_config["mcpServers"][request.name] = server_config
            
            # 保存更新后的配置
            with open(mcp_config_path, 'w', encoding='utf-8') as f:
                json.dump(mcp_config, f, indent=4, ensure_ascii=False)

            # 之后要通过这个接口获取到注册情况的详细信息，那些tool 注册成功了，那些tool没有成功。        
        
            return {
                "status": "success",
                "message": f"MCP server {request.name} 添加成功",
                "server_name": request.name,
                "timestamp": time.time()
            }
        else:
            return {
                "status": "error",
                "message": f"MCP server {request.name} 添加失败",
                "server_name": request.name,
                "timestamp": time.time()
            }
        
    except Exception as e:
        logger.error(f"添加MCP server失败: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"添加MCP server失败: {str(e)}")

@app.post("/api/system-prompt/optimize", response_model=SystemPromptOptimizeResponse)
async def optimize_system_prompt(request: SystemPromptOptimizeRequest, response: Response):
    """优化系统提示词"""
    try:
        # 检查是否有默认的模型客户端
        if not default_model_client:
            add_cors_headers(response)
            return SystemPromptOptimizeResponse(
                success=False,
                message="系统未配置默认LLM模型，无法进行提示词优化"
            )
        
        # 创建SystemPromptOptimizer实例
        optimizer = SystemPromptOptimizer()
        
        # 执行优化
        result = await asyncio.to_thread(
            optimizer.optimize_system_prompt,
            request.original_prompt,
            default_model_client,
            server_args.default_llm_model_name,
            request.optimization_goal
        )
        
        # 提取优化后的提示词
        optimized_prompt = result.get('optimized_prompt', '')
        
        add_cors_headers(response)
        return SystemPromptOptimizeResponse(
            success=True,
            message="系统提示词优化成功",
            optimized_prompt=optimized_prompt,
            optimization_details={
                "original_length": len(request.original_prompt),
                "optimized_length": len(optimized_prompt),
                "optimization_goal": request.optimization_goal
            }
        )
        
    except Exception as e:
        logger.error(f"系统提示词优化失败: {str(e)}")
        logger.error(traceback.format_exc())
        add_cors_headers(response)
        return SystemPromptOptimizeResponse(
            success=False,
            message=f"系统提示词优化失败: {str(e)}"
        )

def get_agent_config_tools(availableTools):
    tools = []
    for tool_name in availableTools:
        for tool in tool_manager.list_tools():
            if tool['name'] == tool_name:
                tools.append(tool)
    return tools

@app.post("/api/evaluations/checkpoint_generation")
async def generate_checkpoints(request: StreamRequest, response: Response):
    """调用CheckpointGenerationAgent生成评估检查点"""
    add_cors_headers(response)
    if not request.messages:
        raise HTTPException(status_code=400, detail="user_messages不能为空")
    
    llm_config = request.llm_model_config or {}
    api_key = llm_config.get("api_key") or server_args.default_llm_api_key
    base_url = llm_config.get("base_url") or server_args.default_llm_api_base_url
    model_name = llm_config.get("model") or server_args.default_llm_model_name
    
    if not api_key or not base_url or not model_name:
        raise HTTPException(status_code=400, detail="缺少必要的模型配置（api_key/base_url/model_name）")
    
    checkpoint_agent = CheckpointGenerationAgent(
        api_key=api_key,
        base_url=base_url,
    )
    try:
        result = await checkpoint_agent.workflow(
            user_messages=[
                            {"role": msg.role, "content": msg.content}
                            for msg in request.messages
                        ],
            agent_config=json.dumps(request.model_dump(), ensure_ascii=False),
            tools_description=json.dumps(get_agent_config_tools(request.available_tools), ensure_ascii=False),
            model_name=model_name,
        )
        return {
            "status": "success",
            "data": json.loads(result),
            "total_tokens": checkpoint_agent.get_total_tokens()
        }
    except json.JSONDecodeError:
        logger.warning(f"检查点生成结果不是有效的JSON格式: {result}")
        raise HTTPException(status_code=400, detail="检查点生成结果不是有效的JSON格式，请重新请求")
    except Exception as e:
        logger.error(f"生成检查点失败: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"生成检查点失败: {str(e)}")  


@app.post("/api/evaluations/score")
async def evaluate_agent_result(request: ScoreEvaluationRequest, response: Response):
    """调用AgentScoreEvaluator对Agent结果进行打分"""
    add_cors_headers(response)
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages不能为空")
    
    llm_config = request.llm_model_config or {}
    api_key = llm_config.get("api_key") or server_args.default_llm_api_key
    base_url = llm_config.get("base_url") or server_args.default_llm_api_base_url
    model_name = llm_config.get("model") or server_args.default_llm_model_name
    
    if not api_key or not base_url or not model_name:
        raise HTTPException(status_code=400, detail="缺少必要的模型配置（api_key/base_url/model_name）")
    
    evaluator = AgentScoreEvaluator(
        api_key=api_key,
        base_url=base_url,
    )
    
    try:
        evaluation_result = await evaluator.evaluate(
            agent_result=[
                            {"role": msg.role, "content": msg.content}
                            for msg in request.messages
                        ],
            agent_config=json.dumps(request.model_dump(), ensure_ascii=False),
            checkpoint=json.dumps(request.checkpoints, ensure_ascii=False),
            model_name=model_name,
        )
        return {
            "status": "success",
            "data": json.loads(evaluation_result),
            "total_tokens": evaluator.get_total_tokens()
        }
    except json.JSONDecodeError:
        logger.warning(f"评估结果不是有效的JSON格式: {evaluation_result}")
        raise HTTPException(status_code=400, detail="评估结果不是有效的JSON格式，请重新请求")

    except Exception as e:
        logger.error(f"评估Agent结果失败: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"评估Agent结果失败: {str(e)}")


try:
    from fastapi.middleware.wsgi import WSGIMiddleware
    from wsgidav.wsgidav_app import WsgiDAVApp

    # 配置文件存储路径
    STORAGE_PATH = os.environ.get("HOST_WEBDAV_SERVER_ROOT") or './'
    os.makedirs(STORAGE_PATH, exist_ok=True)

    # 配置 WsgiDAV
    config = {
        "provider_mapping": {"/": STORAGE_PATH},
        "simple_dc": {"user_mapping": {"*": {"admin": {"password": "password"}}}},
        "verbose": 1,
        "lock_storage": True,
        "property_manager": True,
    }

    # 创建 WsgiDAV 应用
    webdav_app = WsgiDAVApp(config)


    # 将 WebDAV 挂载到 /webdav 路径
    if os.environ.get("ENABLE_DEBUG_WEBDAV"):
        app.mount("/webdav", WSGIMiddleware(webdav_app))
except Exception as e:
    logger.warning(f"WebDAV 挂载失败: {str(e)}, 请检查ENABLE_DEBUG_WEBDAV环境变量是否设置为True")


if __name__ == "__main__":
    # 创建必要的目录
    os.makedirs(server_args.logs_dir, exist_ok=True)
    os.makedirs(server_args.workspace, exist_ok=True)
    
    # 守护进程模式
    if server_args.daemon:
        import daemon
        import daemon.pidfile
        
        context = daemon.DaemonContext(
            working_directory=os.getcwd(),
            umask=0o002,
            pidfile=daemon.pidfile.TimeoutPIDLockFile(server_args.pid_file),
        )
        
        with context:
            uvicorn.run(
                app,
                host=server_args.host,
                port=server_args.port,
                log_level="debug",
                reload=False
            )
    else:
        uvicorn.run(
            app,
            host=server_args.host,
            port=server_args.port,
            log_level="debug",
            reload=False
        )
