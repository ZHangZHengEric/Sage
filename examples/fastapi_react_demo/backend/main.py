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
from pathlib import Path
from typing import List, Dict, Any, Optional, AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, status, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from agents.agent.agent_controller import AgentController
from agents.tool.tool_manager import ToolManager
from agents.utils.logger import logger
from agents.config import get_settings
from openai import OpenAI

# 导入新的配置加载器
from config_loader import get_app_config, save_app_config, ModelConfig


# Pydantic模型定义
class ChatMessage(BaseModel):
    role: str
    content: str
    message_id: str = None
    type: str = "normal"

class ChatRequest(BaseModel):
    type: str = "chat"
    messages: List[ChatMessage]
    use_deepthink: bool = True
    use_multi_agent: bool = True
    session_id: Optional[str] = None

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

class SystemStatus(BaseModel):
    status: str
    agents_count: int
    tools_count: int
    active_sessions: int
    version: str = "0.8"

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
            
            controller = AgentController(model, model_config)
            logger.info(f"✅ 智能体控制器初始化完成 (使用配置文件)")
            print(f"✅ 系统已就绪，模型: {app_config.model.model_name}")
            
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
                
                controller = AgentController(model, model_config)
                logger.info("✅ 智能体控制器初始化完成 (使用Sage配置)")
                print(f"✅ 系统已就绪，模型: {settings.model.model_name}")
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
        return SystemStatus(
            status="running",
            agents_count=7,  # Sage框架的智能体数量
            tools_count=tools_count,
            active_sessions=len(active_sessions)
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
        
        controller = AgentController(model, model_config)
        
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
        
        tools = tool_manager.list_tools_simplified()
        return [
            ToolInfo(
                name=tool["name"],
                description=tool["description"],
                parameters=tool.get("parameters", {})
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
        
        # 执行智能体对话
        result = controller.run(
            messages,
            tool_manager,
            session_id=request.session_id,
            deep_thinking=request.use_deepthink,
            summary=True,
            deep_research=request.use_multi_agent
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
                message_history.append({
                    "role": msg.role,
                    "content": msg.content,
                    "message_id": msg.message_id or str(uuid.uuid4()),
                    "type": msg.type
                })
            
            # 生成回复消息ID
            message_id = str(uuid.uuid4())
            
            # 发送开始标记
            yield f"data: {json.dumps({'type': 'chat_start', 'message_id': message_id})}\n\n"
            
            # 使用AgentController进行流式处理
            for chunk in controller.run_stream(
                input_messages=message_history,
                tool_manager=tool_manager,
                session_id=str(uuid.uuid4()),
                deep_thinking=request.use_deepthink,
                summary=True,
                deep_research=request.use_multi_agent
            ):
                # 处理消息块
                for msg in chunk:
                    data = {
                        'type': 'chat_chunk',
                        'message_id': msg.get('message_id', message_id),
                        'role': msg.get('role', 'assistant'),
                        'content': msg.get('content', ''),
                        'show_content': msg.get('show_content', ''),
                        'step_type': msg.get('type', ''),
                        'agent_type': msg.get('role', '')
                    }
                    
                    yield f"data: {json.dumps(data)}\n\n"
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


# 静态文件服务（用于React构建文件）
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=static_path), name="static")


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