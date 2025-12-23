#!/usr/bin/env python3
"""
Sage Server 构建脚本（仅生成二进制）
只进行本地二进制构建，不包含任何 Docker 打包或部署逻辑
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


class SimpleBuilder:
    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent  # 回到 agent_server 目录
        print("项目根目录:", self.project_root)
        self.build_dir = Path(__file__).parent / "build"  # 构建目录放在 build_tools 下

    def clean_build(self):
        """清理构建目录"""
        print("🧹 清理构建目录...")
        if self.build_dir.exists():
            try:
                shutil.rmtree(self.build_dir)
            except OSError:
                print("⚠️  无法删除构建目录，继续使用现有目录")
        self.build_dir.mkdir(exist_ok=True)
        print("✅ 构建目录清理完成")

    def build_binary(self):
        """构建二进制文件（仅 PyInstaller 单文件）"""
        print("🔨 构建二进制文件...")

        try:
            # 切换到项目目录
            os.chdir(self.project_root)

            # 使用 PyInstaller 构建
            cmd = [
                sys.executable, "-m", "PyInstaller",
                "--onefile",
                "--clean",
                "--distpath", str(self.build_dir),
                "--workpath", str(self.build_dir / "work"),
                "--name", "sage_stream_service",

                # 添加 prompt 文件和其他资源文件
                "--add-data", f"{self.project_root.parent / 'Sage' / 'sagents' / 'agent' / 'prompts'}/*{os.pathsep}sagents/agent/prompts/",
                "--add-data", f"{self.project_root.parent / 'Sage' / 'sagents' / 'utils'}/*{os.pathsep}sagents/utils/",
                "--add-data", f"{self.project_root.parent / 'Sage' / 'sagents' / 'context'}/*{os.pathsep}sagents/context/",
                "--add-data", f"{self.project_root.parent / 'Sage' / 'sagents' / 'tool'}/*{os.pathsep}sagents/tool/",

                "--hidden-import", "fastapi",
                "--hidden-import", "uvicorn",
                "--hidden-import", "pydantic",
                "--hidden-import", "yaml",
                "--hidden-import", "openai",
                "--hidden-import", "sagents",
                "--hidden-import", "sagents.agent",
                "--hidden-import", "sagents.agent.prompts",
                "--hidden-import", "sagents.agent.prompts.simple_agent_prompts",
                "--hidden-import", "sagents.agent.prompts.simple_react_agent_prompts",
                "--hidden-import", "sagents.agent.prompts.task_executor_agent_prompts",
                "--hidden-import", "sagents.agent.prompts.task_analysis_prompts",
                "--hidden-import", "sagents.agent.prompts.task_decompose_prompts",
                "--hidden-import", "sagents.agent.prompts.task_observation_prompts",
                "--hidden-import", "sagents.agent.prompts.task_planning_prompts",
                "--hidden-import", "sagents.agent.prompts.task_rewrite_prompts",
                "--hidden-import", "sagents.agent.prompts.task_router_prompts",
                "--hidden-import", "sagents.agent.prompts.task_stage_summary_prompts",
                "--hidden-import", "sagents.agent.prompts.task_summary_prompts",
                "--hidden-import", "sagents.agent.prompts.workflow_select_prompts",
                "--hidden-import", "sagents.agent.prompts.memory_extraction_prompts",
                "--hidden-import", "sagents.agent.prompts.query_suggest_prompts",
                "--hidden-import", "sagents.utils",
                "--hidden-import", "sagents.utils.prompt_manager",
                "--hidden-import", "sagents.utils.logger",
                "--hidden-import", "sagents.context",
                "--hidden-import", "sagents.tool",
                "--hidden-import", "mcp",
                "--hidden-import", "fastmcp",
                "--hidden-import", "docstring_parser",
                "--hidden-import", "chardet",
                "--hidden-import", "httpx",
                "--hidden-import", "pdfplumber",
                "--hidden-import", "html2text",
                "--hidden-import", "openpyxl",
                "--hidden-import", "pypandoc",
                "--hidden-import", "python-docx",
                "--hidden-import", "markdown",
                "--hidden-import", "python-pptx",
                "--hidden-import", "PyMuPDF",
                "--hidden-import", "tqdm",
                "--hidden-import", "unstructured",
                "--hidden-import", "numpy",
                "--hidden-import", "pandas",
                "--hidden-import", "pandas._libs",
                "--hidden-import", "pandas._libs.lib",
                "--hidden-import", "pandas._libs.hashtable",
                "--hidden-import", "pandas._libs.tslib",
                "--hidden-import", "pandas._libs.interval",
                "--hidden-import", "pandas._libs.parsers",
                "--hidden-import", "pandas._libs.writers",
                "--hidden-import", "pandas._libs.reduction",
                "--hidden-import", "pandas._libs.algos",
                "--hidden-import", "pandas._libs.groupby",
                "--hidden-import", "pandas._libs.join",
                "--hidden-import", "pandas._libs.indexing",
                "--hidden-import", "pandas._libs.sparse",
                "--hidden-import", "pandas._libs.ops",
                "--hidden-import", "pandas._libs.properties",
                "--hidden-import", "pandas._libs.reshape",
                "--hidden-import", "pandas._libs.testing",
                "--hidden-import", "pandas._libs.window",
                "--hidden-import", "pandas._libs.json",
                "--hidden-import", "pandas.io.formats.format",
                "--hidden-import", "pandas.io.common",
                "--hidden-import", "pandas.io.parsers",
                "--hidden-import", "pyarrow",
                "--hidden-import", "pyarrow.lib",
                "--hidden-import", "pyarrow.compute",
                "--hidden-import", "pyarrow.csv",
                "--hidden-import", "pyarrow.json",
                "--hidden-import", "pyarrow.parquet",
                "--hidden-import", "loguru",
                "--hidden-import", "asyncio_mqtt",
                "--hidden-import", "websockets",
                "--hidden-import", "python-daemon",
                "--hidden-import", "daemon.pidfile",
                "--paths", str(self.project_root.parent / "Sage"),
                "--paths", str(self.project_root),
                "--collect-all", "sagents",
                "--collect-all", "mcp",
                "--collect-all", "fastmcp",
                "--collect-all", "fastapi",
                "--collect-all", "uvicorn",
                "--collect-all", "pydantic",
                "--collect-all", "yaml",
                "--collect-all", "openai",
                "--collect-all", "httpx",
                "--collect-all", "loguru",
                "--collect-all", "pypandoc",
                "--collect-all", "pdfplumber",
                "--collect-all", "html2text",
                "--collect-all", "openpyxl",
                "--collect-all", "python-docx",
                "--collect-all", "markdown",
                "--collect-all", "python-pptx",
                "--collect-all", "PyMuPDF",
                "--collect-all", "tqdm",
                "--collect-all", "unstructured",
                "--collect-all", "numpy",
                "--collect-all", "pandas",
                "--collect-all", "pyarrow",
                "--collect-all", "chardet",
                "--collect-all", "asyncio",
                "--collect-all", "aiofiles",
                "--collect-all", "websockets",
                "--collect-all", "python-multipart",
                "--collect-all", "jinja2",
                "--collect-all", "itsdangerous",
                "--collect-all", "click",
                "--collect-all", "h11",
                "--collect-all", "anyio",
                "--collect-all", "idna",
                "--collect-all", "sniffio",
                "--collect-all", "typing_extensions",
                "--collect-all", "starlette",
                "--collect-all", "pydantic_core",
                "--collect-all", "annotated_types",
                "--collect-all", "email_validator",
                "--collect-all", "python-dateutil",
                "--collect-all", "six",
                "--collect-all", "urllib3",
                "--collect-all", "certifi",
                "--collect-all", "charset_normalizer",
                "--collect-all", "requests",
                "--collect-all", "pyyaml",
                "--collect-all", "markupsafe",
                "--collect-all", "blinker",
                "--collect-all", "greenlet",
                "--collect-all", "sqlalchemy",
                "--collect-all", "alembic",
                "--collect-all", "psycopg2",
                "--collect-all", "redis",
                "--collect-all", "celery",
                "--collect-all", "kombu",
                "--collect-all", "billiard",
                "--collect-all", "amqp",
                "--collect-all", "vine",
                "--collect-all", "importlib_metadata",
                "--collect-all", "zipp",
                "--collect-all", "packaging",
                "--collect-all", "pyparsing",
                "--collect-all", "setuptools",
                "--collect-all", "wheel",
                "--collect-all", "pip",
                "--collect-all", "distlib",
                "--collect-all", "filelock",
                "--collect-all", "platformdirs",
                "--collect-all", "tomli",
                "--collect-all", "pep517",
                "--collect-all", "pyproject_hooks",
                "--collect-all", "build",
                "--collect-all", "hatchling",
                "--collect-all", "hatch_vcs",
                "--collect-all", "hatch_fancy_pypi_readme",
                "--collect-all", "editables",
                "--collect-all", "pathspec",
                "--collect-all", "pluggy",
                # 测试相关依赖不需要打包到生产二进制
                "app/sage_server.py"
            ]

            print(f"执行命令: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, capture_output=True, text=True)

            print("✅ 二进制文件构建完成")
            return True

        except subprocess.CalledProcessError as e:
            print(f"❌ 构建失败: {e}")
            print(f"错误输出: {e.stderr}")
            return False
        except Exception as e:
            print(f"❌ 构建异常: {e}")
            return False

    # 已移除 Docker 与部署相关函数

    def build(self):
        """执行完整构建流程"""
        print("🚀 开始 Sage Stream Service 简化构建流程")
        print("=" * 50)

        # 1. 清理构建目录
        self.clean_build()

        # 2. 构建二进制文件
        if not self.build_binary():
            return False

        # 仅生成二进制，不创建任何 Docker 文件或部署包

        print("=" * 50)
        print("🎉 构建完成!")
        print(f"📦 二进制输出目录: {self.build_dir}")

        return True


def main():
    """主函数"""
    builder = SimpleBuilder()

    if len(sys.argv) > 1 and sys.argv[1] == "--clean":
        builder.clean_build()
        print("✅ 清理完成")
        return

    success = builder.build()
    if success:
        print("✅ 构建成功")
        print(f"📦 输出目录: {builder.build_dir}")
        sys.exit(0)
    else:
        print("❌ 构建失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
