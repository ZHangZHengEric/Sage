"""
Python 虚拟环境管理。
"""
import os
import venv
import sys
from typing import Optional
from sagents.utils.logger import logger
from sagents.utils.common_utils import get_system_python_path


class VenvManager:
    """管理沙箱的 Python 虚拟环境"""

    def __init__(self, venv_dir: str, python_version: Optional[str] = None):
        """
        初始化虚拟环境管理器。

        Args:
            venv_dir: 虚拟环境目录路径
            python_version: Python 版本（默认使用系统 Python）
        """
        self.venv_dir = venv_dir
        self.python_version = python_version
        self._ensure_venv()

    def _ensure_venv(self):
        """确保虚拟环境存在"""
        if not os.path.exists(self.venv_dir):
            logger.info(f"[VenvManager] 创建虚拟环境: {self.venv_dir}")
            os.makedirs(os.path.dirname(self.venv_dir), exist_ok=True)

            # 获取正确的 Python 解释器路径（处理 PyInstaller 打包环境）
            system_python = get_system_python_path()
            if not system_python:
                logger.error("[VenvManager] 无法找到系统 Python 解释器")
                raise RuntimeError("无法找到系统 Python 解释器")

            logger.info(f"[VenvManager] 使用 Python 解释器: {system_python}")

            # 创建虚拟环境，指定正确的 Python 解释器
            venv.create(self.venv_dir, with_pip=True, executable=system_python)
            self._install_uv_in_venv()

            # 配置阿里云 pip 源
            self._configure_pip_mirror()

            logger.info("[VenvManager] 虚拟环境创建完成")
        else:
            logger.info(f"[VenvManager] 虚拟环境已存在: {self.venv_dir}")

    def _configure_pip_mirror(self):
        """配置阿里云 pip 镜像源"""
        import subprocess

        pip_bin = self.get_pip_bin()

        # 阿里云 pip 镜像源
        aliyun_index_url = "https://mirrors.aliyun.com/pypi/simple/"
        trusted_host = "mirrors.aliyun.com"

        logger.info(f"[VenvManager] 配置阿里云 pip 镜像源: {aliyun_index_url}")

        try:
            # 升级 pip 并配置镜像源
            result = subprocess.run(
                [pip_bin, "config", "set", "global.index-url", aliyun_index_url],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                # 配置信任主机
                subprocess.run(
                    [pip_bin, "config", "set", "global.trusted-host", trusted_host],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                logger.info("[VenvManager] 阿里云 pip 镜像源配置成功")
            else:
                logger.warning(f"[VenvManager] 配置 pip 镜像源失败: {result.stderr}")

        except Exception as e:
            logger.warning(f"[VenvManager] 配置 pip 镜像源时出错: {e}")

    def _install_uv_in_venv(self):
        """在 venv 中安装 uv，失败不阻塞。"""
        import subprocess

        python_bin = self.get_python_bin()
        if not os.path.exists(python_bin):
            logger.warning("[VenvManager] venv python 不存在，跳过 uv 安装")
            return

        install_cmd = [
            python_bin, "-m", "pip", "install", "-U", "uv",
            "--index-url", "https://mirrors.aliyun.com/pypi/simple/",
            "--trusted-host", "mirrors.aliyun.com",
        ]
        result = subprocess.run(install_cmd, capture_output=True, text=True, timeout=180)
        if result.returncode == 0:
            logger.info("[VenvManager] uv 已安装到 venv")
            return

        fallback_cmd = [python_bin, "-m", "pip", "install", "-U", "uv"]
        fallback_result = subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=180)
        if fallback_result.returncode == 0:
            logger.info("[VenvManager] uv 已安装到 venv（默认源）")
        else:
            logger.warning(f"[VenvManager] uv 安装失败，不影响后续: {fallback_result.stderr}")
            
    def get_python_bin(self) -> str:
        """获取 Python 解释器路径"""
        return os.path.join(self.venv_dir, "bin", "python")
    
    def get_pip_bin(self) -> str:
        """获取 pip 路径"""
        return os.path.join(self.venv_dir, "bin", "pip")
    
    def install_package(self, package: str) -> bool:
        """
        安装 Python 包。
        
        Args:
            package: 包名（如 'requests' 或 'requests==2.28.0'）
            
        Returns:
            是否安装成功
        """
        import subprocess
        
        logger.info(f"[VenvManager] 安装包: {package}")
        
        pip_bin = self.get_pip_bin()
        
        try:
            result = subprocess.run(
                [pip_bin, "install", package, "--quiet"],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                logger.info(f"[VenvManager] {package} 安装成功")
                return True
            else:
                logger.error(f"[VenvManager] {package} 安装失败: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"[VenvManager] 安装 {package} 失败: {e}")
            return False
            
    def install_requirements(self, requirements: list) -> bool:
        """
        安装多个 Python 包。
        
        Args:
            requirements: 包名列表
            
        Returns:
            是否全部安装成功
        """
        import subprocess
        
        if not requirements:
            return True
            
        logger.info(f"[VenvManager] 安装 requirements: {requirements}")
        
        pip_bin = self.get_pip_bin()
        
        try:
            result = subprocess.run(
                [pip_bin, "install"] + list(requirements),
                capture_output=True,
                text=True,
                timeout=600
            )
            
            if result.returncode == 0:
                logger.info("[VenvManager] requirements 安装成功")
                return True
            else:
                logger.error(f"[VenvManager] requirements 安装失败: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"[VenvManager] 安装 requirements 失败: {e}")
            return False
