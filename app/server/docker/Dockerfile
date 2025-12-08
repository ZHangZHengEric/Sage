FROM docker.m.daocloud.io/python:3.11-slim
RUN sed -i s@/deb.debian.org/@/mirrors.aliyun.com/@g /etc/apt/sources.list.d/debian.sources

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    libreoffice \
    fonts-noto-cjk \
    lsof \
    pandoc \
    ca-certificates \
    tzdata \
    upx \
    && update-ca-certificates \
    && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# 复制 requirements.txt 文件
COPY app/server/requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple

COPY app/server  /app/app/server
COPY sagents /app/sagents

# 创建工作空间目录 & 日志目录
RUN mkdir -p /app/agent_workspace /app/logs

# 设置环境变量
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT [ "python", "app/server/main.py" ]
