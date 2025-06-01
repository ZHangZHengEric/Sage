#!/usr/bin/env python3
"""
Sage FastAPI + React Demo 后端启动脚本

便捷启动脚本，自动检查依赖并启动后端服务器
"""

import sys
import subprocess
import os
from pathlib import Path

def check_dependencies():
    """检查必需的依赖"""
    required_packages = [
        'fastapi',
        'uvicorn',
        'websockets',
        'pydantic'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"❌ 缺少以下依赖包: {', '.join(missing_packages)}")
        print("请运行以下命令安装:")
        print(f"pip install {' '.join(missing_packages)}")
        return False
    
    return True

def main():
    """主函数"""
    print("🚀 启动 Sage FastAPI + React Demo 后端服务器")
    print("=" * 50)
    
    # 检查当前目录
    current_dir = Path(__file__).parent
    backend_dir = current_dir / "backend"
    main_py = backend_dir / "main.py"
    
    if not main_py.exists():
        print(f"❌ 找不到后端文件: {main_py}")
        print("请确保在正确的目录下运行此脚本")
        sys.exit(1)
    
    # 检查依赖
    print("🔍 检查依赖...")
    if not check_dependencies():
        sys.exit(1)
    
    print("✅ 依赖检查通过")
    
    # 启动服务器
    print("🌟 启动FastAPI服务器...")
    print("📡 服务器地址: http://localhost:8000")
    print("📚 API文档: http://localhost:8000/docs")
    print("🔧 交互式API: http://localhost:8000/redoc")
    print("-" * 50)
    print("按 Ctrl+C 停止服务器")
    print("=" * 50)
    
    try:
        # 切换到backend目录并启动
        os.chdir(backend_dir)
        subprocess.run([
            sys.executable, "main.py"
        ], check=True)
    except KeyboardInterrupt:
        print("\n👋 服务器已停止")
    except subprocess.CalledProcessError as e:
        print(f"❌ 启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 