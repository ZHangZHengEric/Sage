#!/usr/bin/env python3
"""
内置FTP服务器 - 为Sage工作空间提供文件访问

基于pyftpdlib的简单FTP服务器
支持从配置文件加载设置
"""

import os
import sys
import threading
from pathlib import Path
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

# 根据运行环境选择导入路径
try:
    # 尝试从当前目录导入（当从backend目录运行时）
    from config_loader import get_app_config
except ImportError:
    # 尝试从backend目录导入（当从项目根目录运行时）
    try:
        from backend.config_loader import get_app_config
    except ImportError:
        # 最后尝试绝对导入
        sys.path.append(str(Path(__file__).parent))
        from config_loader import get_app_config

from agents.utils.logger import logger


class SageFTPHandler(FTPHandler):
    """自定义FTP处理器，添加日志记录"""
    
    def on_connect(self):
        logger.info(f"FTP: 客户端连接 {self.remote_ip}:{self.remote_port}")
    
    def on_disconnect(self):
        logger.info(f"FTP: 客户端断开 {self.remote_ip}:{self.remote_port}")
    
    def on_login(self, username):
        logger.info(f"FTP: 用户登录 {username} from {self.remote_ip}")
    
    def on_logout(self, username):
        logger.info(f"FTP: 用户登出 {username}")


class SageFTPServer:
    """Sage FTP服务器"""
    
    def __init__(self):
        self.server = None
        self.thread = None
        self.config = get_app_config()
        
    def setup_server(self):
        """设置FTP服务器"""
        try:
            # 创建授权器
            authorizer = DummyAuthorizer()
            
            # 确保工作空间目录存在
            workspace_path = self.config.workspace.root_path
            os.makedirs(workspace_path, exist_ok=True)
            
            # 添加用户
            authorizer.add_user(
                self.config.ftp.username,
                self.config.ftp.password,
                workspace_path,
                perm='elradfmwMT'  # 完整权限
            )
            
            # 创建处理器
            handler = SageFTPHandler
            handler.authorizer = authorizer
            handler.banner = "Sage Multi-Agent Framework FTP Server Ready"
            
            # 被动模式配置
            handler.passive_ports = range(30000, 30010)
            
            # 创建服务器
            self.server = FTPServer((self.config.ftp.host, self.config.ftp.port), handler)
            self.server.max_cons = self.config.ftp.max_connections
            self.server.max_cons_per_ip = 5
            
            logger.info(f"FTP服务器配置完成:")
            logger.info(f"  地址: {self.config.ftp.host}:{self.config.ftp.port}")
            logger.info(f"  用户: {self.config.ftp.username}")
            logger.info(f"  根目录: {workspace_path}")
            logger.info(f"  最大连接: {self.config.ftp.max_connections}")
            
            return True
            
        except Exception as e:
            logger.error(f"FTP服务器配置失败: {e}")
            return False
    
    def start(self):
        """启动FTP服务器"""
        if not self.config.ftp.enabled:
            logger.info("FTP服务已禁用")
            return False
            
        if not self.setup_server():
            return False
            
        try:
            def run_server():
                logger.info("🚀 FTP服务器启动中...")
                self.server.serve_forever()
            
            self.thread = threading.Thread(target=run_server, daemon=True)
            self.thread.start()
            
            logger.info(f"✅ FTP服务器已启动")
            logger.info(f"📁 访问地址: ftp://{self.config.ftp.username}:{self.config.ftp.password}@localhost:{self.config.ftp.port}")
            return True
            
        except Exception as e:
            logger.error(f"FTP服务器启动失败: {e}")
            return False
    
    def stop(self):
        """停止FTP服务器"""
        if self.server:
            logger.info("🛑 停止FTP服务器...")
            self.server.close_all()
            self.server = None
            logger.info("✅ FTP服务器已停止")
    
    def is_running(self):
        """检查服务器是否运行"""
        return self.server is not None and self.thread and self.thread.is_alive()


# 全局FTP服务器实例
_ftp_server = None


def get_ftp_server():
    """获取FTP服务器实例"""
    global _ftp_server
    if _ftp_server is None:
        _ftp_server = SageFTPServer()
    return _ftp_server


def start_ftp_server():
    """启动FTP服务器"""
    server = get_ftp_server()
    return server.start()


def stop_ftp_server():
    """停止FTP服务器"""
    server = get_ftp_server()
    server.stop()


def is_ftp_running():
    """检查FTP服务器状态"""
    server = get_ftp_server()
    return server.is_running()


if __name__ == "__main__":
    """独立运行FTP服务器"""
    print("🧠 Sage FTP Server")
    print("=" * 50)
    
    try:
        server = SageFTPServer()
        if server.start():
            print("✅ FTP服务器运行中...")
            print("按 Ctrl+C 停止服务器")
            try:
                while server.is_running():
                    import time
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n👋 正在停止FTP服务器...")
                server.stop()
        else:
            print("❌ FTP服务器启动失败")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        sys.exit(1) 