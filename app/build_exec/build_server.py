#!/usr/bin/env python3
"""
Sage Server 构建脚本（只生成本地单文件二进制）
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


class ServerBuilder:
    """Sage Stream Service 单文件二进制构建器"""

    # -------------------------------
    # 所有附加资源目录（相对 project_root）
    # -------------------------------
    RESOURCES = [
        ("sagents/agent/prompts", "sagents/agent/prompts"),
        ("sagents/utils", "sagents/utils"),
        ("sagents/context", "sagents/context"),
        ("sagents/tool", "sagents/tool"),
    ]

    # -------------------------------
    # 隐式导入
    # -------------------------------
    HIDDEN_IMPORTS = [
        "fastapi", "uvicorn", "pydantic", "yaml", "openai", "sagents",
        "mcp", "fastmcp", "docstring_parser", "chardet", "httpx",
        "pdfplumber", "html2text", "openpyxl", "pypandoc",
        "python-docx", "markdown", "python-pptx", "PyMuPDF",
        "tqdm", "unstructured", "numpy", "pandas", "pyarrow",
        "loguru", "asyncio_mqtt", "websockets"
       
    ]

    # -------------------------------
    # PyInstaller collect-all 列表
    # -------------------------------
    COLLECT_ALL = [
        "sagents", "mcp", "fastmcp", "fastapi", "uvicorn", "pydantic",
        "yaml", "openai", "httpx", "loguru", "pypandoc", "pdfplumber",
        "html2text", "openpyxl", "python-docx", "markdown",
        "python-pptx", "PyMuPDF", "tqdm", "unstructured", "numpy",
        "pandas", "pyarrow", "chardet", "asyncio", "aiofiles",
        "websockets", "python-multipart", "jinja2", "itsdangerous",
        "click", "h11", "anyio", "idna", "sniffio",
        "typing_extensions", "starlette", "pydantic_core",
        "annotated_types", "email_validator", "python-dateutil",
        "six", "urllib3", "certifi", "charset_normalizer",
        "requests", "pyyaml", "markupsafe", "blinker",
        "greenlet", "sqlalchemy", "alembic", "psycopg2", "redis",
        "celery", "kombu", "billiard", "amqp", "vine",
        "importlib_metadata", "zipp", "packaging", "pyparsing",
        "setuptools", "wheel", "pip", "distlib", "filelock",
        "platformdirs", "tomli", "pep517", "pyproject_hooks",
        "build", "hatchling", "hatch_vcs", "hatch_fancy_pypi_readme",
        "editables", "pathspec", "pluggy",
    ]

    def __init__(self):
        # build_tools/build.py → project_root
        self.project_root = Path(__file__).resolve().parents[2]
        self.build_dir = Path(__file__).parent / "build"

        print(f"📁 项目根目录: {self.project_root}")
        print(f"📁 sagents 路径: {self.project_root / 'sagents'}")
        print(f"📁 app 路径: {self.project_root / 'app'}")

    # -------------------------------
    # 清理构建目录
    # -------------------------------
    def clean_build(self):
        print("🧹 清理构建目录...")
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir, ignore_errors=True)
        self.build_dir.mkdir(exist_ok=True)
        print("✅ 构建目录已重建")

    # -------------------------------
    # 构建二进制
    # -------------------------------
    def build_binary(self):
        print("🔨 构建二进制文件...")

        os.chdir(self.project_root)

        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--clean",
            "--name", "sage_server",
            "--distpath", str(self.build_dir),
            "--workpath", str(self.build_dir / "work"),
        ]

        # -------------------------------
        # 打包资源
        # -------------------------------
        for src_rel, target_rel in self.RESOURCES:
            src = self.project_root / src_rel
            cmd += ["--add-data", f"{src}/*{os.pathsep}{target_rel}/"]

        # -------------------------------
        # hidden imports
        # -------------------------------
        for mod in self.HIDDEN_IMPORTS:
            cmd += ["--hidden-import", mod]

        # -------------------------------
        # collect-all
        # -------------------------------
        for mod in self.COLLECT_ALL:
            cmd += ["--collect-all", mod]

        # -------------------------------
        # 搜索路径
        # -------------------------------
        cmd += [
            "--paths", str(self.project_root),
            "--paths", str(self.project_root / "app"),
            "--paths", str(self.project_root / "sagents"),
        ]

        # -------------------------------
        # 入口文件：生成临时入口脚本以支持模块化导入
        # -------------------------------
        entry_script_name = "run_server_entry.py"
        entry_path = self.project_root / entry_script_name
        
        print(f"📝 生成临时入口文件: {entry_path}")
        with open(entry_path, "w", encoding="utf-8") as f:
            f.write("import sys\n")
            f.write("import os\n")
            f.write("sys.path.insert(0, os.path.abspath('.'))\n")
            f.write("from app.server.main import main\n")
            f.write("\n")
            f.write("if __name__ == '__main__':\n")
            f.write("    sys.exit(main())\n")

        cmd.append(str(entry_path))

        print("▶️ PyInstaller 命令:")
        print(" ".join(cmd))

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            print("🎉 PyInstaller 构建成功")
            result = True

        except subprocess.CalledProcessError as e:
            print("❌ PyInstaller 构建失败")
            print("🟥 错误输出:")
            print(e.stderr)
            result = False
            
        finally:
            if entry_path.exists():
                os.remove(entry_path)
                print(f"🗑️ 已清理临时入口文件: {entry_path}")
                
        return result

    # -------------------------------
    # 总构建流程
    # -------------------------------
    def build(self):
        print("🚀 开始构建 Sage Server 二进制")
        print("=" * 60)

        self.clean_build()

        if not self.build_binary():
            print("❌ 构建失败")
            return False

        print("=" * 60)
        print("🎯 构建成功")
        print(f"📦 输出目录: {self.build_dir}")
        return True


def main():
    builder = ServerBuilder()

    if len(sys.argv) > 1 and sys.argv[1] == "--clean":
        builder.clean_build()
        print("🧹 ✔️ 清理成功")
        return

    sys.exit(0 if builder.build() else 1)


if __name__ == "__main__":
    main()
