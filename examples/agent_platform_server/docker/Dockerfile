FROM docker.m.daocloud.io/python:3.11-slim
RUN sed -i s@/deb.debian.org/@/mirrors.aliyun.com/@g /etc/apt/sources.list.d/debian.sources

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    libreoffice \
    lsof \
    pandoc \
    ca-certificates \
    tzdata \
    upx \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime  \
    && echo Asia/Shanghai > /etc/timezone

# 复制 requirements.txt 文件
COPY examples/agent_platform_server/requirements.txt .

# 安装 Python 依赖
RUN pip install  -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple

COPY examples/agent_platform_server  /app/examples/agent_platform_server
COPY sagents /app/sagents

# 创建工作空间目录 & 日志目录
RUN mkdir -p /app/agent_workspace /app/logs

# 设置环境变量
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT [ "python", "examples/agent_platform_server/main.py" ]
