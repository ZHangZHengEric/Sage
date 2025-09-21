"""
Sage Stream Service

基于 Sage 框架的智能体流式服务
提供简洁的 HTTP API 和 Server-Sent Events (SSE) 实时通信
不做任何的配置以及设置的缓存，所有的配置都通过接口传入
"""

from ctypes import Union
from math import log
import os
import sys
import json
import uuid
import asyncio
import traceback
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, AsyncGenerator, Union
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, status, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from pydantic import BaseModel
import uvicorn

# 添加 Sage 项目路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
print(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sagents.sagents import SAgent
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_proxy import ToolProxy
from sagents.utils.logger import logger
from openai import OpenAI
from sagents.context.session_context import SessionStatus,get_session_context


import argparse

parser = argparse.ArgumentParser(description="Sage Stream Service")
parser.add_argument("--default_llm_api_key", required=True, help="默认LLM API Key")
parser.add_argument("--default_llm_api_base_url", required=True, help="默认LLM API Base")
parser.add_argument("--default_llm_model_name", required=True, help="默认LLM API Model")
parser.add_argument("--default_llm_max_tokens", default=4096, type=int, help="默认LLM API Max Tokens")
parser.add_argument("--default_llm_temperature", default=0.3, type=float, help="默认LLM API Temperature")
parser.add_argument("--host", default="0.0.0.0", help="Server Host")
parser.add_argument("--port", default=8001, type=int, help="Server Port")

parser.add_argument("--mcp-config", default="mcp_setting.json", help="MCP配置文件路径")
parser.add_argument("--workspace", default="sage_demo_workspace", help="工作空间目录")
parser.add_argument("--logs-dir", default="logs", help="日志目录")
parser.add_argument("--preset_running_config", default="", help="预设配置，system_context，以及workflow，与接口中传过来的合并使用")
parser.add_argument("--memory_root", default=None, help="记忆存储根目录（可选）")
parser.add_argument("--daemon", action="store_true", help="以守护进程模式运行")
parser.add_argument("--pid-file", default="sage_stream.pid", help="PID文件路径")

server_args = parser.parse_args()
if server_args.workspace:
    server_args.workspace = os.path.abspath(server_args.workspace)
os.environ['PREFIX_FILE_WORKSPACE'] = server_args.workspace if server_args.workspace.endswith('/') else server_args.workspace+'/'

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
    Sage 流式服务类
    
    提供基于 Sage 框架的智能体流式服务功能
    """
    
    def __init__(self, model: Optional[OpenAI] = None, 
                        model_config: Optional[Dict[str, Any]] = None, 
                        tool_manager: Optional[Union[ToolManager, ToolProxy]] = None, 
                        preset_running_config: Optional[Dict[str, Any]] = None,
                        workspace: Optional[str] = None,
                        memory_root: Optional[str] = None):
        """
        初始化服务
        
        Args:
            model: OpenAI 客户端实例
            model_config: 模型配置字典
            tool_manager: 工具管理器实例
        """
        self.preset_running_config = preset_running_config
        self.preset_system_context = None
        if 'system_context' in self.preset_running_config:
            self.preset_system_context = self.preset_running_config['system_context']
        self.preset_available_workflows =None
        if 'available_workflows' in self.preset_running_config:
            self.preset_available_workflows = self.preset_running_config['available_workflows']
        if "system_prefix" in self.preset_running_config:
            self.preset_system_prefix = self.preset_running_config['system_prefix']
        else:
            self.preset_system_prefix = "You are a helpful AI assistant."

        # workspace 有可能是相对路径
        if workspace:
            workspace = os.path.abspath(workspace)

        # 创建 Sage AgentController 实例
        self.sage_controller = SAgent(
            model=model,
            model_config=model_config,
            system_prefix=self.preset_system_prefix,
            workspace=workspace if workspace.endswith('/') else workspace+'/',
            memory_root=memory_root
        )
        self.tool_manager = tool_manager
        logger.info("SageStreamService 初始化完成")
    
    async def process_stream(self, messages, session_id=None, user_id=None, deep_thinking=None, 
                           max_loop_count=None, multi_agent=None,more_suggest=False,
                            system_context:Dict=None, 
                           available_workflows: Dict=None):
        """处理流式聊天请求"""
        logger.info(f"🚀 SageStreamService.process_stream 开始，会话ID: {session_id}")
        logger.info(f"📝 参数: deep_thinking={deep_thinking}, multi_agent={multi_agent}, messages_count={len(messages)}")
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
            
            # 直接调用同步的 run_stream 方法
            stream_result = self.sage_controller.run_stream(
                input_messages=messages,
                tool_manager=self.tool_manager,
                session_id=session_id,
                user_id=user_id,
                deep_thinking=deep_thinking,
                max_loop_count=max_loop_count,
                multi_agent=multi_agent,
                more_suggest = more_suggest,
                system_context=system_context,
                available_workflows=available_workflows
            )
            
            logger.info("✅ run_stream 调用成功，开始处理结果...")
            
            # 处理返回的生成器
            chunk_count = 0
            for chunk in stream_result:
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
            
            logger.info(f"🏁 流式处理完成，总共处理了 {chunk_count} 个块")
                
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
                'show_content': f"处理失败: {str(e)}"
            }
            yield error_result
    
    # 会话管理方法
    def interrupt_session(self, session_id: str, message: str = "用户请求中断") -> bool:
        """中断指定会话"""
        return self.sage_controller.interrupt_session(session_id, message)
    
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
default_model_client: Optional[OpenAI] = None



async def initialize_tool_manager():
    """异步初始化工具管理器"""
    # 创建工具管理器实例，但不自动发现工具
    manager = ToolManager(is_auto_discover=False)
    
    # 手动进行基础工具发现
    manager._auto_discover_tools()
    
    # 设置 MCP 配置路径
    manager._mcp_setting_path = os.environ.get('SAGE_MCP_CONFIG_PATH', 'mcp_setting.json')
    
    # 异步发现 MCP 工具
    await manager._discover_mcp_tools(mcp_setting_path=manager._mcp_setting_path)
    
    return manager

async def initialize_system(server_args):
    """初始化系统"""
    global default_stream_service, tool_manager, default_model_client
    
    logger.info("正在初始化 Sage Stream Service...")
    
    try:
        # 初始化模型客户端
        if server_args.default_llm_api_key:
            default_model_client = OpenAI(
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
        
        # 初始化流式服务
        if default_model_client:
            # 从配置中构建模型配置字典
            model_config_dict = {
                'model': server_args.default_llm_model_name,
                'max_tokens': server_args.default_llm_max_tokens,
                'temperature': server_args.default_llm_temperature
            }

            if server_args.preset_running_config:
                if os.path.exists(server_args.preset_running_config):
                    with open(server_args.preset_running_config, 'r') as f:
                        preset_running_config = json.load(f)
                else:
                    preset_running_config = {}
            else:
                preset_running_config = {}

            default_stream_service = SageStreamService(
                model=default_model_client,
                model_config=model_config_dict,
                tool_manager=tool_manager,
                preset_running_config=preset_running_config,
                workspace=server_args.workspace,
                memory_root=server_args.memory_root
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
    tool_call_id: Optional[str] = None
    show_content: Optional[str] = None
    # 添加历史对话中可能存在的字段
    message_type: Optional[str] = None
    timestamp: Optional[float] = None
    chunk_id: Optional[str] = None
    is_final: Optional[bool] = None
    is_chunk: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None

class StreamRequest(BaseModel):
    messages: List[ChatMessage]
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    deep_thinking: Optional[Union[bool, str]] = None
    max_loop_count: int = 10
    multi_agent: Optional[Union[bool, str]] = None
    more_suggest: bool = False
    system_context: Optional[Dict[str, Any]] = None
    available_workflows: Optional[Dict[str, List[str]]] = None
    llm_model_config: Optional[Dict[str, Any]] = None
    system_prefix: Optional[str] = None
    available_tools: Optional[List[str]] = None

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
    
    logger.info(f"Server: 请求参数: {request}")
    # 生成会话ID
    # llm_model_config={'model': '', 'maxTokens': '', 'temperature': ''}
    # 如果是value 是空，删除key
    if request.llm_model_config:
        request.llm_model_config = {k: v for k, v in request.llm_model_config.items() if v is not None and v != ''}

    session_id = request.session_id or str(uuid.uuid4())
    # 判断是否要初始化新的 sage service 还是使用默认的
    # 取决于是否需要自定义模型以及 agent 的system prefix ，以及对tool 的工具是否有限制
    if request.llm_model_config or request.system_prefix or request.available_tools:
        # 根据model config 初始化新的模型客户端
        model_client = OpenAI(
            api_key=request.llm_model_config.get('api_key', server_args.default_llm_api_key),
            base_url=request.llm_model_config.get('base_url', server_args.default_llm_api_base_url),
        )
        llm_model_config = {
            'model': request.llm_model_config.get('model', server_args.default_llm_model_name),
            'max_tokens': int(request.llm_model_config.get('max_tokens', server_args.default_llm_max_tokens)),
            'temperature': float(request.llm_model_config.get('temperature', server_args.default_llm_temperature))
        }
        logger.info(f"初始化模型客户端，模型配置: {llm_model_config}")

        if request.available_tools:
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

        start_stream_service = time.time()
        # 初始化新的 sage service
        stream_service = SageStreamService(
            model=model_client,
            model_config=llm_model_config,
            tool_manager=tool_proxy,
            preset_running_config={
                "system_prefix": request.system_prefix
            },
            workspace=server_args.workspace,
            memory_root=server_args.memory_root
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

    async def generate_stream():
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
            # 处理流式响应，传递所有参数
            async for result in stream_service.process_stream(
                messages=messages, 
                session_id=session_id,
                user_id=request.user_id,
                deep_thinking=request.deep_thinking,
                max_loop_count=request.max_loop_count,
                multi_agent=request.multi_agent,
                more_suggest=request.more_suggest,
                system_context=request.system_context,
                available_workflows=request.available_workflows
            ):
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
                    yield json.dumps(error_data, ensure_ascii=False) + "\n"
                    
                await asyncio.sleep(0.01)  # 避免过快发送
                
            # 发送流结束标记
            end_data = {
                'type': 'stream_end',
                'session_id': session_id,
                'timestamp': time.time()
            }
            yield json.dumps(end_data, ensure_ascii=False) + "\n"
            
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
            # 清理会话资源
            if session_id in all_active_sessions_service_map:
                del all_active_sessions_service_map[session_id]
                logger.info(f"会话 {session_id} 资源已清理")
    return StreamingResponse(
        generate_stream(),
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
async def interrupt_session(session_id: str, request: InterruptRequest = None):
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
        session_context = get_session_context(session_id)
    except Exception as e:
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

@app.post("/api/mcp/add")
async def add_mcp_server(request: MCPServerRequest, response: Response):
    """添加MCP server到tool manager"""
    add_cors_headers(response)
    
    try:
        global tool_manager, default_stream_service
        
        if not tool_manager:
            raise HTTPException(status_code=503, detail="工具管理器未初始化")
        
        logger.info(f"开始添加MCP server: {request.name}")
        
        
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
            
            # 添加新的MCP server配置
            server_config = {
                "disabled": request.disabled
            }
            if request.streaming_http_url:
                server_config["streaming_http_url"] = request.streaming_http_url
            if request.sse_url:
                server_config["sse_url"] = request.sse_url
            if request.api_key:
                server_config["api_key"] = request.api_key
            
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



# 主函数
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