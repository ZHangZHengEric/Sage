"""
Python 虚拟环境管理。
"""
import os
import venv
from typing import Optional
from sagents.utils.logger import logger


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
            
            # 创建虚拟环境
            venv.create(self.venv_dir, with_pip=True)
            logger.info(f"[VenvManager] 虚拟环境创建完成")
        else:
            logger.info(f"[VenvManager] 虚拟环境已存在: {self.venv_dir}")
            
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
                logger.info(f"[VenvManager] requirements 安装成功")
                return True
            else:
                logger.error(f"[VenvManager] requirements 安装失败: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"[VenvManager] 安装 requirements 失败: {e}")
            return False
