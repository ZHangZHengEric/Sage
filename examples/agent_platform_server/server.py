"""
Sage Stream Service

基于 Sage 框架的智能体流式服务
提供简洁的 HTTP API 和 Server-Sent Events (SSE) 实时通信
"""


import os
import sys
import time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

# 项目路径配置
project_root = Path(os.path.realpath(__file__)).parent.parent.parent
sys.path.insert(0, str(project_root))


from sagents.utils.logger import logger

# 导入拆分后的路由模块
import router
import globals.variables as global_vars
from entities.entities import StandardResponse, create_success_response, create_error_response, SageHTTPException

import argparse


def create_argument_parser():
    """创建命令行参数解析器，支持环境变量，优先级：指定入参 > 环境变量 > 默认值"""
    parser = argparse.ArgumentParser(description="Sage Stream Service")
    
    # 新格式参数（推荐使用）
    parser.add_argument("--default_llm_api_key", 
                       default=os.getenv("SAGE_DEFAULT_LLM_API_KEY"), 
                       help="默认LLM API Key (环境变量: SAGE_DEFAULT_LLM_API_KEY)")
    parser.add_argument("--default_llm_api_base_url", 
                       default=os.getenv("SAGE_DEFAULT_LLM_API_BASE_URL"), 
                       help="默认LLM API Base (环境变量: SAGE_DEFAULT_LLM_API_BASE_URL)")
    parser.add_argument("--default_llm_model_name", 
                       default=os.getenv("SAGE_DEFAULT_LLM_MODEL_NAME"), 
                       help="默认LLM API Model (环境变量: SAGE_DEFAULT_LLM_MODEL_NAME)")
    parser.add_argument("--default_llm_max_tokens", 
                       default=int(os.getenv("SAGE_DEFAULT_LLM_MAX_TOKENS", "4096")), 
                       type=int, 
                       help="默认LLM API Max Tokens (环境变量: SAGE_DEFAULT_LLM_MAX_TOKENS)")
    parser.add_argument("--default_llm_temperature", 
                       default=float(os.getenv("SAGE_DEFAULT_LLM_TEMPERATURE", "0.2")), 
                       type=float, 
                       help="默认LLM API Temperature (环境变量: SAGE_DEFAULT_LLM_TEMPERATURE)")
    parser.add_argument("--default_llm_max_model_len", 
                       default=int(os.getenv("SAGE_DEFAULT_LLM_MAX_MODEL_LEN", "54000")), 
                       type=int, 
                       help="默认LLM 最大上下文 (环境变量: SAGE_DEFAULT_LLM_MAX_MODEL_LEN)")

    parser.add_argument("--host", 
                       default=os.getenv("SAGE_HOST", "0.0.0.0"), 
                       help="Server Host (环境变量: SAGE_HOST)")
    parser.add_argument("--port", 
                       default=int(os.getenv("SAGE_PORT", "8001")), 
                       type=int, 
                       help="Server Port (环境变量: SAGE_PORT)")
    parser.add_argument("--preset_mcp_config", 
                       default=os.getenv("SAGE_MCP_CONFIG_PATH", "mcp_setting.json"), 
                       help="MCP配置文件路径 (环境变量: SAGE_MCP_CONFIG_PATH)")
    parser.add_argument("--preset_running_config", 
                       default=os.getenv("SAGE_PRESET_RUNNING_CONFIG_PATH", "agent_setting.json"), 
                       help="预设配置，system_context，以及workflow，与接口中传过来的合并使用 (环境变量: SAGE_PRESET_RUNNING_CONFIG_PATH)")
    parser.add_argument("--workspace", 
                       default=os.getenv("SAGE_WORKSPACE_PATH", "agent_workspace"), 
                       help="工作空间目录 (环境变量: SAGE_WORKSPACE_PATH)")
    parser.add_argument("--logs-dir", 
                       default=os.getenv("SAGE_LOGS_DIR_PATH", "logs"), 
                       help="日志目录 (环境变量: SAGE_LOGS_DIR_PATH)")
    parser.add_argument("--memory_root", 
                       default=os.getenv("SAGE_MEMORY_ROOT"), 
                       help="记忆存储根目录（可选） (环境变量: SAGE_MEMORY_ROOT)")
    parser.add_argument("--daemon", 
                       action="store_true", 
                       default=os.getenv("SAGE_DAEMON", "").lower() in ("true", "1", "yes"), 
                       help="以守护进程模式运行 (环境变量: SAGE_DAEMON)")
    parser.add_argument("--pid-file", 
                       default=os.getenv("SAGE_PID_FILE", "sage_stream.pid"), 
                       help="PID文件路径 (环境变量: SAGE_PID_FILE)")
    parser.add_argument("--force_summary", 
                       action="store_true", 
                       default=os.getenv("SAGE_FORCE_SUMMARY", "").lower() in ("true", "1", "yes"), 
                       help="是否强制总结 (环境变量: SAGE_FORCE_SUMMARY)")
    
    # 数据库相关参数
    parser.add_argument("--db_type", 
                       default=os.getenv("SAGE_DB_TYPE", "file"), 
                       choices=["file", "memory"],
                       help="数据库类型：file（文件模式）或memory（内存模式） (环境变量: SAGE_DB_TYPE)")
    parser.add_argument("--db_path", 
                       default=os.getenv("SAGE_DB_PATH", "./"), 
                       help="数据库文件存储路径，仅在file模式下有效 (环境变量: SAGE_DB_PATH)")
    
    return parser


def handle_llm_args_compatibility(args):
    """处理LLM参数的向后兼容性"""
    # 检查是否使用了旧格式参数
    if args.default_llm_max_model_len is None:
        args.default_llm_max_model_len = 54000
    elif args.default_llm_max_model_len < 8000:
        args.default_llm_max_model_len = 54000
    
    old_args_used = []
    
    # 处理每个LLM参数 (新参数, 旧参数)
    llm_params = [
        ('default_llm_api_key', 'llm_api_key'),
        ('default_llm_api_base_url', 'llm_api_base_url'), 
        ('default_llm_model_name', 'llm_model_name'),
        ('default_llm_max_tokens', 'llm_max_tokens'),
        ('default_llm_temperature', 'llm_temperature')
    ]
    
    for new_param, old_param in llm_params:
        new_value = getattr(args, new_param, None)
        old_value = getattr(args, old_param, None)
        
        if new_value is not None:
            # 使用新格式参数
            continue
        elif old_value is not None:
            # 使用旧格式参数，设置到新格式
            setattr(args, new_param, old_value)
            old_args_used.append(old_param)
        elif new_param in ['default_llm_api_key', 'default_llm_api_base_url', 'default_llm_model_name']:
            # 必需参数缺失
            raise ValueError(f"必需参数缺失: 请提供 --{new_param} 或 --{old_param}")
    
    # 设置默认值
    if args.default_llm_max_tokens is None:
        args.default_llm_max_tokens = 4096
    if args.default_llm_temperature is None:
        args.default_llm_temperature = 0.3
    
    # 发出废弃警告
    if old_args_used:
        logger.warning(f"使用了已废弃的参数: {', '.join(old_args_used)}。"
                      f"请使用新格式参数: {', '.join(['--default_' + p.replace('llm_', '') for p in old_args_used])}")
        logger.warning(f"使用了已废弃的参数: {', '.join(old_args_used)}")


def setup_environment_and_args():
    """设置环境变量和处理命令行参数"""
    # 解析命令行参数
    parser = create_argument_parser()
    args = parser.parse_args()
    
    # 处理参数兼容性
    handle_llm_args_compatibility(args)
    
    # 设置工作空间路径
    if args.workspace:
        args.workspace = os.path.abspath(args.workspace)
    os.environ['PREFIX_FILE_WORKSPACE'] = args.workspace if args.workspace.endswith('/') else args.workspace+'/'

    return args

def create_lifespan_handler(args):
    """创建应用生命周期管理器"""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """应用生命周期管理"""
        # 启动时初始化
        await global_vars.initialize_system(args)
        yield
        # 关闭时清理
        await global_vars.cleanup_system()
    return lifespan


def create_fastapi_app(args):
    """创建并配置FastAPI应用"""
    # 创建FastAPI应用
    app = FastAPI(
        title="Sage Stream Service",
        description="基于 Sage 框架的智能体流式服务",
        version="1.0.0",
        lifespan=create_lifespan_handler(args)
    )

    # CORS 配置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 全局异常处理器
    @app.exception_handler(SageHTTPException)
    async def sage_http_exception_handler(request: Request, exc: SageHTTPException):
        """处理自定义HTTP异常"""
        error_response = create_error_response(
            code=exc.status_code,
            message=exc.detail,
            error_detail=exc.error_detail
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response.model_dump()
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """处理标准HTTP异常"""
        error_response = create_error_response(
            code=exc.status_code,
            message=exc.detail,
            error_detail=getattr(exc, 'error_detail', '')
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response.model_dump()
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """处理通用异常"""
        logger.error(f"未处理的异常: {str(exc)}，请求路径: {request.url}")
        import traceback
        logger.error(traceback.format_exc())
        
        error_response = create_error_response(
            code=500,
            message="内部服务器错误",
            error_detail=str(exc)
        )
        return JSONResponse(
            status_code=500,
            content=error_response.model_dump()
        )

    # 健康检查接口
    @app.get("/api/health", response_model=StandardResponse)
    async def health_check():
        """
        健康检查接口
        
        Returns:
            StandardResponse: 包含服务状态的标准响应
        """
        return create_success_response(
            message="服务运行正常",
            data={
                "status": "healthy",
                "timestamp": time.time(),
                "service": "SageStreamService"
            }
        )

    # 添加路由
    app.include_router(router.mcp_router)
    app.include_router(router.agent_router)
    app.include_router(router.stream_router)
    app.include_router(router.session_router)
    app.include_router(router.tool_router)
    
    return app


def start_server(args, app):
    """启动服务器"""
    # 创建必要的目录
    os.makedirs(args.logs_dir, exist_ok=True)
    os.makedirs(args.workspace, exist_ok=True)
    
    # 守护进程模式
    if args.daemon:
        import daemon
        import daemon.pidfile
        
        context = daemon.DaemonContext(
            working_directory=os.getcwd(),
            umask=0o002,
            pidfile=daemon.pidfile.TimeoutPIDLockFile(args.pid_file),
        )
        
        with context:
            uvicorn.run(
                app,
                host=args.host,
                port=args.port,
                log_level="debug",
                reload=False
            )
    else:
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level="debug",
            reload=False
        )


def main():
    """主函数 - 启动Sage Stream Service"""
    try:
        # 设置环境变量和处理命令行参数
        args = setup_environment_and_args()
        
        # 创建FastAPI应用
        app = create_fastapi_app(args)
        
        # 启动服务器
        start_server(args, app)
        
    except Exception as e:
        logger.error(f"服务启动失败: {e}")
        raise



if __name__ == "__main__":
    main()