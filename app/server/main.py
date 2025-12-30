"""
Sage Stream Service

基于 Sage 框架的智能体流式服务
提供简洁的 HTTP API 和 Server-Sent Events (SSE) 实时通信
"""

import os
import sys
from pathlib import Path

# 项目路径配置（保持不动）
project_root = Path(os.path.realpath(__file__)).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# 指定加载的 .env 文件（保持不动）
load_dotenv(".env")

import warnings
for m in ("websockets", "uvicorn"):
    warnings.filterwarnings("ignore", category=DeprecationWarning, module=m)

import uvicorn
from core import config
from application import create_fastapi_app


def start_server(cfg: config.StartupConfig):
    """
    启动 Uvicorn Server

    ⚠️ 注意：
    - create_fastapi_app 必须是无副作用的 FastAPI factory
    """
    un_cfg = uvicorn.Config(
        app=create_fastapi_app,
        host=getattr(cfg, "host", "0.0.0.0"),
        port=cfg.port,
        log_level=getattr(cfg, "log_level", "debug"),
        reload=getattr(cfg, "reload", False),
        factory=True,
    )

    server = uvicorn.Server(config=un_cfg)
    server.run()


def main():
    try:
        cfg = config.init_startup_config()
        start_server(cfg)
        return 0
    except KeyboardInterrupt:
        print("服务收到中断信号，正在退出...")
        return 0
    except SystemExit:
        return 0
    except Exception:
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
