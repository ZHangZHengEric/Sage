"""
配置加载器模块
支持从YAML文件或环境变量加载配置
"""

import yaml
import os
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class ModelConfig:
    """模型配置"""
    api_key: str
    model_name: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    max_tokens: int = 4096
    temperature: float = 0.7


@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 8001
    reload: bool = True
    log_level: str = "info"


@dataclass
class WorkspaceConfig:
    """工作空间配置"""
    root_path: str = "/app/workspace"
    host_path: str = "./workspace"


@dataclass
class FtpConfig:
    """FTP服务配置"""
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 2121
    username: str = "sage"
    password: str = "sage123"
    root_directory: str = "/app/workspace"
    max_connections: int = 50


@dataclass
class AppConfig:
    """应用配置"""
    model: ModelConfig
    server: ServerConfig
    workspace: WorkspaceConfig
    ftp: FtpConfig
    
    def __post_init__(self):
        # 验证必填字段
        if not self.model.api_key:
            print("⚠️  警告: 未配置API密钥，需要通过Web界面手动配置")


class ConfigLoader:
    """配置加载器"""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._find_config_file()
        self._config_data = None
    
    def _find_config_file(self) -> Optional[str]:
        """查找配置文件"""
        # 检查环境变量指定的配置文件
        env_config = os.getenv('SAGE_CONFIG_FILE')
        if env_config and Path(env_config).exists():
            return env_config
            
        # 检查是否在Docker环境中
        is_docker = os.getenv('DOCKER_ENV') == 'true' or os.path.exists('/.dockerenv')
        
        # 按优先级查找配置文件
        if is_docker:
            possible_paths = [
                "config.docker.yaml",  # Docker专用配置
                "config.yaml",
                "/app/config.yaml",
                "/etc/sage/config.yaml"
            ]
        else:
            possible_paths = [
                "config.yaml",
                "config.yml", 
                "backend/config.yaml",
                "backend/config.yml",
                os.path.expanduser("~/.sage/config.yaml"),
                "/etc/sage/config.yaml"
            ]
        
        for path in possible_paths:
            if Path(path).exists():
                return path
        return None
    
    def load_config(self) -> AppConfig:
        """加载配置"""
        if self.config_path and Path(self.config_path).exists():
            print(f"📁 读取配置文件: {self.config_path}")
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._config_data = yaml.safe_load(f)
        else:
            print("📁 未找到配置文件，使用默认配置")
            self._config_data = {}
        
        # 从环境变量覆盖配置
        self._load_from_env()
        
        # 创建配置对象
        return self._create_config()
    
    def _load_from_env(self):
        """从环境变量加载配置"""
        env_mappings = {
            'SAGE_API_KEY': ['model', 'api_key'],
            'SAGE_MODEL_NAME': ['model', 'model_name'],
            'SAGE_BASE_URL': ['model', 'base_url'],
            'SAGE_MAX_TOKENS': ['model', 'max_tokens'],
            'SAGE_TEMPERATURE': ['model', 'temperature'],
            'SAGE_HOST': ['server', 'host'],
            'SAGE_PORT': ['server', 'port'],
        }
        
        for env_var, config_path in env_mappings.items():
            value = os.getenv(env_var)
            if value:
                # 设置嵌套配置
                current = self._config_data
                for key in config_path[:-1]:
                    if key not in current:
                        current[key] = {}
                    current = current[key]
                
                # 类型转换
                if config_path[-1] in ['max_tokens', 'port']:
                    value = int(value)
                elif config_path[-1] == 'temperature':
                    value = float(value)
                elif config_path[-1] in ['reload']:
                    value = value.lower() in ('true', '1', 'yes')
                
                current[config_path[-1]] = value
                print(f"🔧 从环境变量加载: {env_var}")
    
    def _create_config(self) -> AppConfig:
        """创建配置对象"""
        # 模型配置
        model_data = self._config_data.get('model', {})
        model_config = ModelConfig(
            api_key=model_data.get('api_key', ''),
            model_name=model_data.get('model_name', 'deepseek-chat'),
            base_url=model_data.get('base_url', 'https://api.deepseek.com/v1'),
            max_tokens=model_data.get('max_tokens', 4096),
            temperature=model_data.get('temperature', 0.7)
        )
        
        # 服务器配置
        server_data = self._config_data.get('server', {})
        server_config = ServerConfig(
            host=server_data.get('host', '0.0.0.0'),
            port=server_data.get('port', 8001),
            reload=server_data.get('reload', True),
            log_level=server_data.get('log_level', 'info')
        )
        
        # 工作空间配置
        workspace_data = self._config_data.get('workspace', {})
        workspace_config = WorkspaceConfig(
            root_path=workspace_data.get('root_path', '/app/workspace'),
            host_path=workspace_data.get('host_path', './workspace')
        )
        
        # FTP配置
        ftp_data = self._config_data.get('ftp', {})
        ftp_config = FtpConfig(
            enabled=ftp_data.get('enabled', True),
            host=ftp_data.get('host', '0.0.0.0'),
            port=ftp_data.get('port', 2121),
            username=ftp_data.get('username', 'sage'),
            password=ftp_data.get('password', 'sage123'),
            root_directory=ftp_data.get('root_directory', '/app/workspace'),
            max_connections=ftp_data.get('max_connections', 50)
        )
        
        return AppConfig(
            model=model_config, 
            server=server_config,
            workspace=workspace_config,
            ftp=ftp_config
        )
    
    def save_config(self, config: AppConfig):
        """保存配置到文件"""
        if not self.config_path:
            self.config_path = "config.yaml"
        
        config_data = {
            'model': {
                'api_key': config.model.api_key,
                'model_name': config.model.model_name,
                'base_url': config.model.base_url,
                'max_tokens': config.model.max_tokens,
                'temperature': config.model.temperature
            },
            'server': {
                'host': config.server.host,
                'port': config.server.port,
                'reload': config.server.reload,
                'log_level': config.server.log_level
            },
            'workspace': {
                'root_path': config.workspace.root_path,
                'host_path': config.workspace.host_path
            },
            'ftp': {
                'enabled': config.ftp.enabled,
                'host': config.ftp.host,
                'port': config.ftp.port,
                'username': config.ftp.username,
                'password': config.ftp.password,
                'root_directory': config.ftp.root_directory,
                'max_connections': config.ftp.max_connections
            }
        }
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
        
        print(f"💾 配置已保存到: {self.config_path}")


# 全局配置加载器实例
_loader = ConfigLoader()
_app_config = None


def get_app_config() -> AppConfig:
    """获取应用配置"""
    global _app_config
    if _app_config is None:
        _app_config = _loader.load_config()
    return _app_config


def reload_config() -> AppConfig:
    """重新加载配置"""
    global _app_config
    _app_config = _loader.load_config()
    return _app_config


def save_app_config(config: AppConfig):
    """保存应用配置"""
    global _app_config
    _loader.save_config(config)
    _app_config = config 