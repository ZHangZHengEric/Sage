#!/usr/bin/env python3
"""
Sage Stream Service 简化构建脚本
先本地构建二进制文件，然后创建 Docker 运行时镜像
"""

import os
import sys
import subprocess
import shutil
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
        """构建二进制文件"""
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
                "--collect-all", "pytest",
                "--collect-all", "pytest_asyncio",
                "--collect-all", "pytest_cov",
                "--collect-all", "coverage",
                "--collect-all", "pytest_html",
                "--collect-all", "pytest_metadata",
                "--collect-all", "pytest_ordering",
                "--collect-all", "pytest_repeat",
                "--collect-all", "pytest_xdist",
                "--collect-all", "execnet",
                "--collect-all", "apipkg",
                "--collect-all", "pytest_forked",
                "--collect-all", "pytest_timeout",
                "--collect-all", "pytest_benchmark",
                "--collect-all", "pytest_mock",
                "--collect-all", "pytest_freezegun",
                "--collect-all", "freezegun",
                "--collect-all", "python_dateutil",
                "--collect-all", "pytest_sugar",
                "--collect-all", "termcolor",
                "--collect-all", "pytest_html",
                "--collect-all", "pytest_metadata",
                "--collect-all", "pytest_ordering",
                "--collect-all", "pytest_repeat",
                "--collect-all", "pytest_xdist",
                "--collect-all", "execnet",
                "--collect-all", "apipkg",
                "--collect-all", "pytest_forked",
                "--collect-all", "pytest_timeout",
                "--collect-all", "pytest_benchmark",
                "--collect-all", "pytest_mock",
                "--collect-all", "pytest_freezegun",
                "--collect-all", "freezegun",
                "--collect-all", "python_dateutil",
                "--collect-all", "pytest_sugar",
                "--collect-all", "termcolor",
                "server.py"
            ]
            
            print(f"执行命令: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            
            print("✅ 二进制文件构建完成")
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"❌ 构建失败: {e}")
            print(f"错误输出: {e.stderr}")
            return False
        except Exception as e:
            print(f"❌ 构建异常: {e}")
            return False
    
    def create_docker_runtime(self):
        """创建 Docker 运行时镜像"""
        print("🐳 创建 Docker 运行时镜像...")
        
        # 创建运行时 Dockerfile（离线部署版本，无外网依赖）
        runtime_dockerfile_content = '''# 运行时镜像（离线部署版本）
# 使用预构建的基础镜像，包含必要的运行时依赖
FROM zavixai:1.0.0

# 设置非交互式安装
ENV DEBIAN_FRONTEND=noninteractive

# 注意：此镜像需要预先安装 curl 和 ca-certificates
# 在离线环境中，请使用包含这些依赖的预构建镜像
# 或者在构建时提供离线安装包

# 创建应用目录
WORKDIR /app

# 复制二进制文件和配置文件
COPY sage_stream_service /app/
COPY config.example.yaml /app/
COPY config.yaml /app/
COPY mcp_setting.json /app/

# 创建必要的目录
RUN mkdir -p /app/logs /app/sage_demo_workspace

# 设置执行权限
RUN chmod +x /app/sage_stream_service

# 创建启动脚本
COPY start.sh /app/
RUN chmod +x /app/start.sh

# 暴露端口
EXPOSE 8001

# 健康检查（如果基础镜像没有curl，此检查将失败，可以注释掉）
# HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
#     CMD curl -f http://localhost:8001/api/health || exit 1

'''
        
        runtime_dockerfile_path = self.build_dir / "Dockerfile"
        with open(runtime_dockerfile_path, 'w', encoding='utf-8') as f:
            f.write(runtime_dockerfile_content)
        
        print(f"✅ 运行时 Dockerfile 创建完成: {runtime_dockerfile_path}")
        return runtime_dockerfile_path
    
    def create_deployment_package(self):
        """创建部署包"""
        print("📦 创建部署包...")
        
        # 创建部署目录
        deploy_dir = self.build_dir / "sage_stream_service_docker"
        deploy_dir.mkdir(exist_ok=True)
        
        # 复制二进制文件
        binary_path = self.build_dir / "sage_stream_service"
        if binary_path.exists():
            shutil.copy2(binary_path, deploy_dir / "sage_stream_service")
            print("✅ 复制二进制文件")
        else:
            print("❌ 二进制文件不存在")
            return False
        
        # 复制配置文件
        config_files = [
            "config.example.yaml",
            "mcp_setting.json"
        ]
        
        for config_file in config_files:
            src_path = self.project_root / config_file
            if src_path.exists():
                shutil.copy2(src_path, deploy_dir / config_file)
                print(f"✅ 复制配置文件: {config_file}")
        
        # 复制运行时 Dockerfile
        runtime_dockerfile = self.build_dir / "Dockerfile"
        if runtime_dockerfile.exists():
            shutil.copy2(runtime_dockerfile, deploy_dir / "Dockerfile")
            print("✅ 复制运行时 Dockerfile")
        
        # 创建 docker-compose.yml（离线部署版本）
        compose_content = '''
services:
  sage-stream-service:
    build: .
    container_name: sage_stream_service
    ports:
      - "8001:8001"
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./mcp_setting.json:/app/mcp_setting.json
      - ./logs:/app/logs
      - ./sage_demo_workspace:/app/sage_demo_workspace
    environment:
      - PYTHONUNBUFFERED=1
      - TZ=Asia/Shanghai
    restart: unless-stopped
    # 健康检查已禁用，因为离线环境可能没有curl
    # healthcheck:
    #   test: ["CMD", "curl", "-f", "http://localhost:8001/api/health"]
    #   interval: 30s
    #   timeout: 10s
    #   retries: 3
    #   start_period: 40s
'''
        
        with open(deploy_dir / "docker-compose.yml", 'w', encoding='utf-8') as f:
            f.write(compose_content)
        
        # 复制启动脚本
        start_script_content = f'''#!/bin/bash

# 检查 config.yaml 是否存在，如果不存在则从 config.example.yaml 复制
if [ ! -f "config.yaml" ]; then
    echo "配置文件 config.yaml 不存在，从 config.example.yaml 复制..."
    cp config.example.yaml config.yaml
    echo "请编辑 config.yaml 文件，设置您的 API 密钥"
fi

# 检查 mcp_setting.json 是否存在，如果不存在则从 mcp_setting.json 复制
if [ ! -f "mcp_setting.json" ]; then
    echo "配置文件 mcp_setting.json 不存在，从 mcp_setting.json 复制..."
    cp mcp_setting.json mcp_setting.json
    echo "请编辑 mcp_setting.json 文件，设置您的 MCP 配置"
fi



# 启动 Sage Stream Service
exec /app/sage_stream_service --config config.yaml --mcp-config mcp_setting.json --workspace sage_demo_workspace --logs-dir logs --daemon --pid-file sage_stream.pid "$@"'''

        with open(deploy_dir / "start.sh", 'w', encoding='utf-8') as f:
            f.write(start_script_content)
        os.chmod(deploy_dir / "start.sh", 0o755)

        # 复制 config.example.yaml 到部署目录
        shutil.copy2(self.project_root / "config.example.yaml", deploy_dir / "config.example.yaml")
        
        # 创建停止脚本
        stop_script = '''#!/bin/bash

echo "🛑 停止 Sage Stream Service..."

docker compose down

echo "✅ 服务已停止"
'''
        
        with open(deploy_dir / "stop.sh", 'w', encoding='utf-8') as f:
            f.write(stop_script)
        
        os.chmod(deploy_dir / "stop.sh", 0o755)
        
        # 创建部署说明
        readme_content = '''# Sage Stream Service Docker 部署包

## 快速开始

### 1. 配置服务
```bash
# 复制并编辑配置文件
cp config.example.yaml config.yaml
vim config.yaml  # 设置您的 API 密钥
```

### 2. 启动服务
```bash
# 使用启动脚本
./start.sh

# 或手动启动
docker compose up -d
```

### 3. 验证服务
```bash
# 健康检查
curl http://localhost:8001/api/health

# 查看状态
docker compose ps

# 查看日志
docker compose logs -f
```

## 服务管理

### 停止服务
```bash
./stop.sh
# 或
docker compose down
```

### 重启服务
```bash
docker compose restart
```

### 更新服务
```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

## 配置说明

编辑 `config.yaml` 文件：

```yaml
model:
  api_key: "your_api_key_here"
  model_name: "deepseek-chat"
  base_url: "https://api.deepseek.com/v1"
  max_tokens: 4096
  temperature: 0.7

server:
  host: "0.0.0.0"
  port: 8001
  log_level: "info"
```

## 端口说明

- `8001`: HTTP API 服务端口

## 目录说明

- `logs/`: 日志文件目录
- `sage_demo_workspace/`: 工作空间目录
- `config.yaml`: 配置文件

## 故障排除

1. **端口被占用**
   ```bash
   # 修改 docker-compose.yml 中的端口映射
   ports:
     - "8002:8001"  # 改为其他端口
   ```

2. **权限问题**
   ```bash
   chmod +x start.sh stop.sh
   ```

3. **查看详细日志**
   ```bash
   docker compose logs -f sage-stream-service
   ```

## 更多信息

- 项目文档: 请查看 docs/ 目录
- 作者: Eric ZZ
'''
        
        with open(deploy_dir / "DEPLOYMENT.md", 'w', encoding='utf-8') as f:
            f.write(readme_content)
        
        # 创建压缩包
        archive_name = "sage_stream_service_docker.tar.gz"
        archive_path = self.build_dir / archive_name
        
        try:
            shutil.make_archive(
                str(archive_path).replace('.tar.gz', ''),
                'gztar',
                deploy_dir
            )
            print(f"✅ 创建压缩包: {archive_name}")
        except Exception as e:
            print(f"❌ 创建压缩包失败: {e}")
        
        print(f"🎉 部署包创建完成: {deploy_dir}")
        return True
    
    def build(self):
        """执行完整构建流程"""
        print("🚀 开始 Sage Stream Service 简化构建流程")
        print("=" * 50)
        
        # 1. 清理构建目录
        self.clean_build()
        
        # 2. 构建二进制文件
        if not self.build_binary():
            return False
        
        # 3. 创建 Docker 运行时
        self.create_docker_runtime()
        
        # 4. 创建部署包
        if not self.create_deployment_package():
            return False
        
        print("=" * 50)
        print("🎉 构建完成!")
        print(f"📦 部署包位置: {self.build_dir}")
        print("📖 详细说明请查看 DEPLOYMENT.md")
        
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
        print("📦 部署包位置: build/sage_stream_service_docker/")
        print("📦 压缩包位置: build/sage_stream_service_docker.tar.gz")
        sys.exit(0)
    else:
        print("❌ 构建失败")
        sys.exit(1)

if __name__ == "__main__":
    main()