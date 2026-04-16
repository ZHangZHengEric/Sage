from setuptools import find_packages, setup
from pathlib import Path


def get_docs_files():
    """获取 docs 目录下的所有 markdown 文件，用于 data_files 配置"""
    docs_files = []
    docs_dir = Path("docs")
    if docs_dir.exists():
        for lang in ["en", "zh"]:
            lang_dir = docs_dir / lang
            if lang_dir.exists():
                # 收集该语言目录下的所有 markdown 文件
                md_files = [str(f) for f in lang_dir.glob("*.md")]
                if md_files:
                    # 目标路径: share/sage/docs/{lang}/
                    docs_files.append(
                        (f"share/sage/docs/{lang}", md_files)
                    )
    return docs_files


setup(
    name="sage",
    version="1.1.0",
    description="A production-ready, modular, and intelligent multi-agent orchestration framework for complex problem solving.",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Eric ZZ",
    author_email="",
    url="https://github.com/ZHangZHengEric/Sage",
    license="MIT",
    packages=find_packages(
        include=["sagents*", "common*", "app*"],
        exclude=["tests*", "app.desktop*", "app.skills*", "app.wiki*", "assets*", "logs*"],
    ),
    include_package_data=True,
    data_files=get_docs_files(),
    entry_points={
        "console_scripts": [
            "sage=app.cli.main:main",
        ]
    },
    install_requires=[
        "gradio>=4.0.0",
        "openai>=1.0.0",
        "requests>=2.31.0",
        "python-dotenv>=1.0.0",
        "pyyaml>=6.0",
        "aiofiles>=0.8.0",
        "fastapi>=0.104.0",
        "uvicorn[standard]>=0.24.0",
        "pydantic>=2.5.0",
        "Authlib>=1.6.0",
        "alibabacloud_dm20151123",
        "alibabacloud_credentials",
        "alibabacloud_tea_openapi",
        "alibabacloud_tea_util",
        "mcp>=1.9.2",
        "fastmcp>=0.9.0",
        "docstring_parser>=0.16",
        "chardet>=5.0.0",
        "httpx>=0.24.0",
        "pdfplumber",
        "html2text",
        "openpyxl",
        "pypandoc",
        "python-docx",
        "markdown",
        "python-pptx",
        "PyMuPDF",
        "tqdm",
        "unstructured"
    ],
    python_requires=">=3.10",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
