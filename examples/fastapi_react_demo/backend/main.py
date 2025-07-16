"""
Sage FastAPI + React Demo Backend

现代化多智能体协作Web应用后端
采用FastAPI + WebSocket实现实时通信
支持从配置文件自动加载模型配置
"""

import os
import sys
import json
import uuid
import asyncio
import traceback
import time
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, status, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel
import uvicorn
import httpx

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from sagents.agent.agent_controller import AgentController
from sagents.tool.tool_manager import ToolManager
from sagents.professional_agents.code_agents import CodeAgent
from sagents.utils.logger import logger
from sagents.config import get_settings
from openai import OpenAI

# 导入新的配置加载器
from config_loader import get_app_config, save_app_config, ModelConfig

# FTP服务器已移除

# Pydantic模型定义
class ChatMessage(BaseModel):
    role: str
    content: str
    message_id: str = None
    type: str = "normal"
    tool_calls: Optional[List[Dict[str, Any]]] = None

class ChatRequest(BaseModel):
    type: str = "chat"
    messages: List[ChatMessage]
    use_deepthink: bool = True
    use_multi_agent: bool = True
    session_id: Optional[str] = None
    system_context: Optional[Dict[str, Any]] = None

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
    agents_count: int
    tools_count: int
    active_sessions: int
    version: str = "0.8"
    workspace_path: str = ""

# 全局变量
tool_manager: Optional[ToolManager] = None
controller: Optional[AgentController] = None
active_sessions: Dict[str, Dict] = {}

# 存储会话状态
sessions: Dict[str, Dict] = {}


class ConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.session_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, session_id: str = None):
        await websocket.accept()
        self.active_connections.append(websocket)
        if session_id:
            self.session_connections[session_id] = websocket
        logger.info(f"WebSocket连接建立，会话ID: {session_id}")
    
    def disconnect(self, websocket: WebSocket, session_id: str = None):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if session_id and session_id in self.session_connections:
            del self.session_connections[session_id]
        logger.info(f"WebSocket连接断开，会话ID: {session_id}")
    
    async def send_personal_message(self, message: dict, session_id: str):
        if session_id in self.session_connections:
            try:
                await self.session_connections[session_id].send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
    
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"广播消息失败: {e}")


# 初始化连接管理器
manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    logger.info("FastAPI应用启动中...")
    await initialize_system()
    yield
    # 关闭时清理
    logger.info("FastAPI应用关闭中...")
    await cleanup_system()


# 创建FastAPI应用
app = FastAPI(
    title="Sage Multi-Agent Framework",
    description="现代化多智能体协作框架API",
    version="0.8"
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080", "*"],  # 允许前端开发服务器
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 手动添加CORS响应头的函数
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*" 
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


# 使用事件处理器替代lifespan
@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    await initialize_system()

@app.on_event("shutdown") 
async def shutdown_event():
    """应用关闭事件"""
    await cleanup_system()


async def initialize_system():
    """初始化系统组件"""
    global tool_manager, controller
    try:
        # 加载应用配置
        app_config = get_app_config()
        print("🚀 Sage Multi-Agent Framework 启动中...")
        print(f"📊 模型: {app_config.model.model_name}")
        print(f"🔗 API: {app_config.model.base_url}")
        
        # 初始化工具管理器（不自动发现MCP工具，避免异步问题）
        tool_manager = ToolManager(is_auto_discover=False)
        # 手动进行自动发现本地工具
        tool_manager._auto_discover_tools()
        await tool_manager._discover_mcp_tools(mcp_setting_path='/app/mcp_servers/mcp_setting.json')
        logger.info("工具管理器初始化完成")
        
        # 优先使用配置文件中的模型配置
        if app_config.model.api_key:
            # 使用配置文件的设置
            model = OpenAI(
                api_key=app_config.model.api_key,
                base_url=app_config.model.base_url
            )
            
            model_config = {
                "model": app_config.model.model_name,
                "temperature": app_config.model.temperature,
                "max_tokens": app_config.model.max_tokens
            }
            code_agent = CodeAgent(model, model_config)
            tool_manager.register_tool(code_agent.to_tool())
            
            # 使用配置文件中的workspace路径
            workspace_path = app_config.workspace.root_path
            controller = AgentController(model, model_config, workspace=workspace_path)
            logger.info(f"✅ 智能体控制器初始化完成 (使用配置文件)")
            print(f"✅ 系统已就绪，模型: {app_config.model.model_name}")
            print(f"📁 工作空间: {workspace_path}")
            
            # FTP服务器已移除，使用AList文件服务
            
            # 同步到Sage框架的配置系统
            settings = get_settings()
            settings.model.api_key = app_config.model.api_key
            settings.model.model_name = app_config.model.model_name
            settings.model.base_url = app_config.model.base_url
            settings.model.max_tokens = app_config.model.max_tokens
            settings.model.temperature = app_config.model.temperature
        else:
            # 如果配置文件没有API密钥，尝试从Sage框架配置加载
            settings = get_settings()
            if settings.model.api_key:
                model = OpenAI(
                    api_key=settings.model.api_key,
                    base_url=settings.model.base_url
                )
                
                model_config = {
                    "model": settings.model.model_name,
                    "temperature": settings.model.temperature,
                    "max_tokens": settings.model.max_tokens
                }
                
                # 使用默认workspace路径
                workspace_path = os.getenv('WORKSPACE_ROOT', '/tmp/sage')
                controller = AgentController(model, model_config, workspace=workspace_path)
                logger.info("✅ 智能体控制器初始化完成 (使用Sage配置)")
                print(f"✅ 系统已就绪，模型: {settings.model.model_name}")
                print(f"📁 工作空间: {workspace_path}")
            else:
                print("⚠️  未配置API密钥，需要通过Web界面配置或在config.yaml中设置")
                print("💡 提示：编辑 backend/config.yaml 文件，设置您的API密钥")
        
    except Exception as e:
        logger.error(f"系统初始化失败: {e}")
        print(f"❌ 系统初始化失败: {e}")
        print("💡 请检查配置文件或网络连接")


async def cleanup_system():
    """清理系统资源"""
    global active_sessions
    try:
        # FTP服务器已移除
        
        # 清理活跃会话
        for session_id in list(active_sessions.keys()):
            if tool_manager:
                await tool_manager.cleanup_session(session_id)
        active_sessions.clear()
        logger.info("系统资源清理完成")
    except Exception as e:
        logger.error(f"系统清理失败: {e}")


# API路由

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """根路径，返回React应用"""
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Sage Multi-Agent Framework</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
    </head>
    <body>
        <div id="root"></div>
        <script>
            // 如果React应用未构建，显示提示信息
            document.getElementById('root').innerHTML = `
                <div style="text-align: center; padding: 50px; font-family: Arial, sans-serif;">
                    <h1>🧠 Sage Multi-Agent Framework</h1>
                    <p>FastAPI Backend is running successfully!</p>
                    <p>Please build and serve the React frontend to see the full interface.</p>
                    <div style="margin-top: 30px;">
                        <h3>API Endpoints:</h3>
                        <ul style="list-style: none;">
                            <li>📡 WebSocket: <code>ws://localhost:8000/ws</code></li>
                            <li>🔧 API Docs: <a href="/docs">http://localhost:8000/docs</a></li>
                            <li>⚙️ System Status: <a href="/api/status">http://localhost:8000/api/status</a></li>
                        </ul>
                    </div>
                </div>
            `;
        </script>
    </body>
    </html>
    """)


@app.get("/api/status", response_model=SystemStatus)
async def get_system_status(response: Response):
    """获取系统状态"""
    add_cors_headers(response)
    try:
        tools_count = len(tool_manager.list_tools()) if tool_manager else 0
        app_config = get_app_config()
        
        return SystemStatus(
            status="running",
            agents_count=7,  # Sage框架的智能体数量
            tools_count=tools_count,
            active_sessions=len(active_sessions),
            workspace_path=app_config.workspace.root_path
        )
    except Exception as e:
        logger.error(f"获取系统状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/configure")
async def configure_system(config: ConfigRequest, response: Response):
    """配置系统"""
    add_cors_headers(response)
    global controller
    try:
        # 获取当前设置并更新模型配置
        settings = get_settings()
        settings.model.api_key = config.api_key
        settings.model.model_name = config.model_name
        settings.model.base_url = config.base_url
        settings.model.max_tokens = config.max_tokens
        settings.model.temperature = config.temperature
        
        # 同时更新配置文件
        app_config = get_app_config()
        app_config.model.api_key = config.api_key
        app_config.model.model_name = config.model_name
        app_config.model.base_url = config.base_url
        app_config.model.max_tokens = config.max_tokens
        app_config.model.temperature = config.temperature
        
        # 保存到配置文件
        save_app_config(app_config)
        
        # 重新初始化模型和控制器
        model = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url
        )
        
        model_config = {
            "model": config.model_name,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens
        }
        
        # 从配置文件或环境变量获取workspace路径
        app_config = get_app_config()
        workspace_path = app_config.workspace.root_path if app_config else os.getenv('WORKSPACE_ROOT', '/tmp/sage')
        controller = AgentController(model, model_config, workspace=workspace_path)
        
        logger.info(f"系统配置更新成功: {config.model_name}")
        print(f"🔄 配置已更新并保存: {config.model_name}")
        return {"status": "success", "message": "配置更新成功并已保存到文件"}
        
    except Exception as e:
        logger.error(f"系统配置失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/tools", response_model=List[ToolInfo])
async def get_tools(response: Response):
    """获取可用工具列表"""
    add_cors_headers(response)
    try:
        if not tool_manager:
            return []
        
        tools = tool_manager.list_tools_with_type()
        return [
            ToolInfo(
                name=tool["name"],
                description=tool["description"],
                parameters=tool.get("parameters", {}),
                type=tool["type"],
                source=tool["source"]
            )
            for tool in tools
        ]
    except Exception as e:
        logger.error(f"获取工具列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """聊天API端点（非流式）"""
    try:
        if not controller:
            raise HTTPException(status_code=400, detail="系统未配置，请先配置API密钥")
        
        # 转换消息格式
        messages = [
            {
                "role": msg.role,
                "content": msg.content,
                "type": msg.type or "normal",
                "message_id": msg.message_id or str(uuid.uuid4())
            }
            for msg in request.messages
        ]
        
        # 从system_context中提取available_workflows
        available_workflows = None
        system_context = request.system_context
        if system_context and 'available_workflows' in system_context:
            available_workflows = system_context['available_workflows']
            # 从system_context中移除available_workflows，避免重复传递
            system_context = {k: v for k, v in system_context.items() if k != 'available_workflows'}
        
        # 执行智能体对话
        result = controller.run(
            messages,
            tool_manager,
            session_id=request.session_id,
            deep_thinking=request.use_deepthink,
            summary=True,
            deep_research=request.use_multi_agent,
            system_context=system_context,
            available_workflows=available_workflows
        )
        
        return {
            "status": "success",
            "result": result,
            "session_id": request.session_id
        }
        
    except Exception as e:
        logger.error(f"聊天处理失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat-stream")
async def chat_stream(request: ChatRequest):
    """处理聊天请求并返回流式响应"""
    
    if not controller:
        raise HTTPException(status_code=500, detail="系统未配置，请先配置API密钥")
    
    async def generate_stream() -> AsyncGenerator[str, None]:
        try:
            # 构建消息历史
            message_history = []
            for msg in request.messages:
                message_data = {
                    "role": msg.role,
                    "content": msg.content,
                    "message_id": msg.message_id or str(uuid.uuid4()),
                    "type": msg.type
                }
                
                # 处理工具调用信息
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    message_data["tool_calls"] = msg.tool_calls
                    
                message_history.append(message_data)
            
            # 生成回复消息ID
            message_id = str(uuid.uuid4())
            
            # 发送开始标记
            yield f"data: {json.dumps({'type': 'chat_start', 'message_id': message_id})}\n\n"
            
            # 从system_context中提取available_workflows
            available_workflows = None
            system_context = request.system_context
            if system_context and 'available_workflows' in system_context:
                available_workflows = system_context['available_workflows']
                # 从system_context中移除available_workflows，避免重复传递
                system_context = {k: v for k, v in system_context.items() if k != 'available_workflows'}
            
            # 使用AgentController进行流式处理
            for chunk in controller.run_stream(
                input_messages=message_history,
                tool_manager=tool_manager,
                session_id=str(uuid.uuid4()),
                deep_thinking=request.use_deepthink,
                summary=True,
                deep_research=request.use_multi_agent,
                system_context=system_context,
                available_workflows=available_workflows,
                max_loop_count=20,
            ):
                # 处理消息块
                for msg in chunk:
                    # 安全处理content和show_content，避免JSON转义问题
                    content = msg.get('content', '')
                    show_content = msg.get('show_content', '')
                    
                    # 清理show_content中的base64图片数据，避免JSON过大
                    if isinstance(show_content, str) and 'data:image' in show_content:
                        try:
                            # 如果show_content是JSON字符串，解析并清理
                            if show_content.strip().startswith('{'):
                                show_content_data = json.loads(show_content)
                                if isinstance(show_content_data, dict) and 'results' in show_content_data:
                                    if isinstance(show_content_data['results'], list):
                                        for result in show_content_data['results']:
                                            if isinstance(result, dict) and 'image' in result:
                                                if result['image'] and isinstance(result['image'], str) and result['image'].startswith('data:image'):
                                                    result['image'] = None
                                show_content = json.dumps(show_content_data, ensure_ascii=False)
                            else:
                                # 如果不是JSON，直接移除base64数据
                                import re
                                show_content = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', 'null', show_content)
                        except (json.JSONDecodeError, Exception) as e:
                            print(f"⚠️ [SHOW_CONTENT CLEANUP] 清理失败: {e}")
                            # 如果清理失败，使用正则表达式移除base64数据
                            import re
                            show_content = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', 'null', show_content)
                    
                    # 特殊处理工具调用结果，避免JSON嵌套问题
                    if msg.get('role') == 'tool' and isinstance(content, str):
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
                                            search_data = json.loads(inner_content)
                                            
                                            # 清理搜索结果中的大数据，避免JSON过大
                                            if isinstance(search_data, dict) and 'results' in search_data:
                                                if isinstance(search_data['results'], list):
                                                    for result in search_data['results']:
                                                        if isinstance(result, dict):
                                                            # 移除base64图片数据，避免JSON过大
                                                            if 'image' in result and result['image']:
                                                                if isinstance(result['image'], str) and result['image'].startswith('data:image'):
                                                                    result['image'] = None
                                                            # 限制文本字段长度
                                                            for field in ['snippet', 'description', 'content']:
                                                                if field in result and isinstance(result[field], str):
                                                                    if len(result[field]) > 500:
                                                                        result[field] = result[field][:500] + '...'
                                            
                                            # 直接使用解析后的数据，避免再次嵌套
                                            content = search_data
                                            print(f"🔍 [SEARCH RESULT] 成功解析嵌套JSON结果")
                                        except json.JSONDecodeError:
                                            # 内层解析失败，使用外层数据
                                            content = parsed_content
                                    else:
                                        # 内层不是JSON字符串，直接使用
                                        content = parsed_content
                                else:
                                    # 不是嵌套结构，直接使用
                                    content = parsed_content
                                    
                                # 确保content是可序列化的
                                if not isinstance(content, (str, dict, list, int, float, bool, type(None))):
                                    content = str(content)
                                    
                        except json.JSONDecodeError as e:
                            print(f"⚠️ [JSON PARSE ERROR] 解析失败: {e}")
                            # 如果解析失败，保持原始字符串但清理特殊字符
                            content = str(content).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
                            # 移除可能导致JSON解析问题的转义字符
                            content = content.replace('\\"', '"').replace('\\\\', '\\')
                    
                    data = {
                        'type': 'chat_chunk',
                        'message_id': msg.get('message_id', message_id),
                        'role': msg.get('role', 'assistant'),
                        'content': content,
                        'show_content': show_content,
                        'step_type': msg.get('type', ''),
                        'agent_type': msg.get('role', '')
                    }
                    
                    # 处理工具调用信息
                    if 'tool_calls' in msg and msg['tool_calls']:
                        data['tool_calls'] = []
                        for tool_call in msg['tool_calls']:
                            tool_call_data = {
                                'id': tool_call.get('id', ''),
                                'name': tool_call.get('function', {}).get('name', ''),
                                'arguments': {},
                                'status': 'running'
                            }
                            
                            # 解析工具参数
                            if 'function' in tool_call and 'arguments' in tool_call['function']:
                                try:
                                    args_str = tool_call['function']['arguments']
                                    if isinstance(args_str, str):
                                        tool_call_data['arguments'] = json.loads(args_str)
                                    else:
                                        tool_call_data['arguments'] = args_str
                                except json.JSONDecodeError:
                                    logger.warning(f"Failed to parse tool arguments: {args_str}")
                                    tool_call_data['arguments'] = {}
                            
                            data['tool_calls'].append(tool_call_data)
                    
                    # 序列化JSON - 保证完整传输大JSON
                    try:
                        json_str = json.dumps(data, ensure_ascii=False)
                        json_size = len(json_str)
                        
                        # print(f"📊 [JSON SIZE] 准备发送JSON: {json_size} 字符")
                        
                        # 对于超大JSON，使用分块发送确保完整性
                        if json_size > 32768:  # 32KB以上使用分块发送
                            print(f"🔄 [CHUNKED SEND] 大JSON分块发送: {json_size} 字符")
                            
                            # 分块发送大JSON
                            chunk_size = 8192  # 8KB per chunk，更小的分块确保稳定性
                            total_chunks = (json_size + chunk_size - 1) // chunk_size
                            
                            # 发送分块开始标记
                            start_marker = {
                                'type': 'chunk_start',
                                'message_id': data.get('message_id', 'unknown'),
                                'total_size': json_size,
                                'total_chunks': total_chunks,
                                'chunk_size': chunk_size
                            }
                            yield f"data: {json.dumps(start_marker, ensure_ascii=False)}\n\n"
                            await asyncio.sleep(0.01)  # 稍长延迟确保前端准备好
                            
                            for i in range(total_chunks):
                                start = i * chunk_size
                                end = min(start + chunk_size, json_size)
                                chunk_data = json_str[start:end]
                                
                                # 创建分块消息，包含校验信息
                                chunk_message = {
                                    'type': 'json_chunk',
                                    'chunk_id': f"{data.get('message_id', 'unknown')}_{i}",
                                    'chunk_index': i,
                                    'total_chunks': total_chunks,
                                    'chunk_data': chunk_data,
                                    'chunk_size': len(chunk_data),
                                    'is_final': i == total_chunks - 1,
                                    'checksum': hash(chunk_data) % 1000000  # 简单校验和
                                }
                                
                                yield f"data: {json.dumps(chunk_message, ensure_ascii=False)}\n\n"
                                await asyncio.sleep(0.005)  # 适中延迟确保顺序和稳定性
                            
                            # 发送分块结束标记
                            end_marker = {
                                'type': 'chunk_end',
                                'message_id': data.get('message_id', 'unknown'),
                                'total_chunks': total_chunks,
                                'expected_size': json_size
                            }
                            yield f"data: {json.dumps(end_marker, ensure_ascii=False)}\n\n"
                            
                            print(f"✅ [CHUNKED SEND] 完成分块发送: {total_chunks} 块")
                        else:
                            # 小JSON直接发送，但添加完整性标记
                            complete_message = {
                                'type': 'complete_json',
                                'data': data,
                                'size': json_size
                            }
                            yield f"data: {json.dumps(complete_message, ensure_ascii=False)}\n\n"
                        
                    except Exception as e:
                        print(f"❌ [JSON SERIALIZE] 序列化失败: {e}")
                        print(f"❌ [ERROR DETAILS] 数据类型: {type(data)}, 大小估计: {len(str(data))}")
                        
                        # 创建错误响应，但保留原始数据结构
                        try:
                            # 尝试创建包含错误信息但保持结构的响应
                            error_data = {
                                'type': 'chat_chunk',
                                'message_id': data.get('message_id', 'error'),
                                'role': data.get('role', 'tool'),
                                'content': {'error': f'JSON序列化失败: {str(e)}', 'original_type': str(type(data.get('content', {})))},
                                'show_content': f'❌ 数据处理错误: {str(e)[:100]}...',
                                'step_type': data.get('step_type', ''),
                                'agent_type': data.get('agent_type', ''),
                                'error': True
                            }
                            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                        except Exception as nested_error:
                            print(f"❌ [NESTED ERROR] 连错误响应都无法序列化: {nested_error}")
                            # 最后的备用方案
                            simple_error = {
                                'type': 'error',
                                'message': 'JSON处理失败，数据过大或格式异常'
                            }
                            yield f"data: {json.dumps(simple_error)}\n\n"
                    
                    await asyncio.sleep(0.01)  # 小延迟避免过快
            
            # 发送完成标记
            yield f"data: {json.dumps({'type': 'chat_complete', 'message_id': message_id})}\n\n"
            
        except Exception as e:
            logger.error(f"流式处理错误: {str(e)}")
            error_data = {
                'type': 'error',
                'message': str(e)
            }
            yield f"data: {json.dumps(error_data)}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )


@app.get("/api/sse/{session_id}")
async def sse_endpoint(session_id: str):
    """SSE连接端点"""
    
    async def event_stream():
        try:
            # 发送连接成功消息
            yield f"data: {json.dumps({'type': 'connected', 'session_id': session_id})}\n\n"
            
            # 保持连接
            while True:
                await asyncio.sleep(30)  # 每30秒发送心跳
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                
        except Exception as e:
            logger.error(f"SSE连接错误: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )


@app.get("/api/sessions")
async def get_active_sessions():
    """获取活跃会话列表"""
    return {
        "active_sessions": list(active_sessions.keys()),
        "count": len(active_sessions)
    }


@app.delete("/api/sessions/{session_id}")
async def cleanup_session(session_id: str):
    """清理指定会话"""
    try:
        if session_id in active_sessions:
            if tool_manager:
                await tool_manager.cleanup_session(session_id)
            del active_sessions[session_id]
            
            # 清理LLM请求记录器
            try:
                from sagents.utils.llm_request_logger import cleanup_logger
                cleanup_logger(session_id)
            except Exception as e:
                logger.warning(f"清理LLM记录器失败: {e}")
            
            logger.info(f"会话 {session_id} 已清理")
        return {"status": "success", "message": f"会话 {session_id} 已清理"}
    except Exception as e:
        logger.error(f"清理会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.options("/{rest_of_path:path}")
async def options_handler(rest_of_path: str, response: Response):
    """处理OPTIONS预检请求"""
    add_cors_headers(response)
    return {"message": "OK"}


@app.get("/api/sessions/{session_id}/llm-summary")
async def get_session_llm_summary(session_id: str):
    """获取会话的LLM请求摘要（极简版本）"""
    try:
        from sagents.utils.llm_request_logger import get_llm_logger
        llm_logger = get_llm_logger(session_id)
        files = llm_logger.list_request_files()
        
        # 按智能体类型统计
        agent_stats = {}
        for file_info in files:
            agent_name = file_info.get('agent_name', 'Unknown')
            if agent_name not in agent_stats:
                agent_stats[agent_name] = 0
            agent_stats[agent_name] += 1
        
        # 极简的摘要信息
        summary = {
            "session_id": session_id,
            "total_requests": len(files),
            "agent_stats": agent_stats,
            "request_files": [f["filename"] for f in files]
        }
        return {"status": "success", "data": summary}
    except Exception as e:
        logger.error(f"获取会话LLM摘要失败: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/sessions/{session_id}/llm-requests")
async def get_session_llm_requests(session_id: str):
    """获取会话的所有LLM请求文件列表"""
    try:
        from sagents.utils.llm_request_logger import get_llm_logger
        llm_logger = get_llm_logger(session_id)
        files = llm_logger.list_request_files()
        return {"status": "success", "data": files}
    except Exception as e:
        logger.error(f"获取会话LLM请求列表失败: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/sessions/{session_id}/llm-requests/{filename}")
async def get_llm_request_detail(session_id: str, filename: str):
    """获取特定LLM请求的详细信息
    
    Args:
        session_id: 会话ID
        filename: 文件名 (例如: PlanningAgent_session_0001_1234567890.json)
    """
    try:
        from sagents.utils.llm_request_logger import get_llm_logger
        from pathlib import Path
        import json
        
        llm_logger = get_llm_logger(session_id)
        file_path = llm_logger.requests_dir / filename
        
        if not file_path.exists():
            return {"status": "error", "message": f"文件不存在: {filename}"}
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return {"status": "success", "data": data}
    except Exception as e:
        logger.error(f"获取LLM请求详情失败: {e}")
        return {"status": "error", "message": str(e)}

# 静态文件服务（用于React构建文件）
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/proxy-file")
async def proxy_file(request: Request):
    file_url = request.query_params.get("url")
    if not file_url:
        return Response("URL parameter is required", status_code=400)

    headers = {
        'User-Agent': 'curl/7.81.0'  # 模拟 curl 的 User-Agent
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(file_url, timeout=30.0, headers=headers)
            response.raise_for_status()

            return Response(
                content=response.content,
                media_type=response.headers.get('content-type', 'text/plain')
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"代理请求失败 (HTTPStatusError): {e.response.status_code} for url: {e.request.url}")
            logger.error(f"响应内容: {e.response.text}")
            logger.error(traceback.format_exc())
            return Response(f"HTTP error occurred: {e.response.status_code}\n{e.response.text}", status_code=e.response.status_code)
        except httpx.RequestError as e:
            logger.error(f"代理请求失败 (RequestError): {e.request.url!r}")
            logger.error(traceback.format_exc())
            return Response(f"An error occurred while requesting {e.request.url!r}:\n{str(e)}", status_code=500)
        except Exception as e:
            logger.error(f"代理请求发生未知错误")
            logger.error(traceback.format_exc())
            return Response(f"An unexpected error occurred: {str(e)}", status_code=500)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        logger.info("WebSocket连接断开")
    except Exception as e:
        logger.error(f"WebSocket处理错误: {e}")


if __name__ == "__main__":
    # 加载配置
    app_config = get_app_config()
    
    print("🌟 启动 Sage Multi-Agent Framework 服务器")
    print(f"🏠 地址: http://{app_config.server.host}:{app_config.server.port}")
    print(f"📚 API文档: http://{app_config.server.host}:{app_config.server.port}/docs")
    print(f"🔄 热重载: {'开启' if app_config.server.reload else '关闭'}")
    
    uvicorn.run(
        "main:app",
        host=app_config.server.host,
        port=app_config.server.port,
        reload=app_config.server.reload,
        log_level=app_config.server.log_level
    )