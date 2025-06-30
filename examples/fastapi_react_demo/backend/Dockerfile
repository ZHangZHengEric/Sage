FROM python:3.11-slim

WORKDIR /app

COPY ./requirements.txt .
RUN pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple
COPY . .

WORKDIR /app/examples/fastapi_react_demo/backend

# 给启动脚本添加执行权限
RUN chmod +x start.sh

EXPOSE 8000

CMD ["./start.sh"]

