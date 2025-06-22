FROM python:3.11-slim

WORKDIR /app

COPY . .
RUN pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple

WORKDIR /app/examples/fastapi_react_demo/backend

EXPOSE 8000

CMD ["python", "main.py"]

