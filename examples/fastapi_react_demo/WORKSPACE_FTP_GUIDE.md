# 🗂️ 工作空间和FTP服务使用指南

Sage Demo提供了完整的工作空间管理和FTP文件访问功能。

## 📁 工作空间结构

```
workspace/
├── {session_id_1}/
│   ├── message_manager.json    # 会话消息状态
│   └── task_manager.json       # 任务状态信息
├── {session_id_2}/
│   ├── message_manager.json
│   └── task_manager.json
└── shared/                     # 共享文件区
    └── ...
```

## ⚙️ 配置说明

### 本地开发环境
```yaml
# backend/config.yaml
workspace:
  root_path: "../workspace"      # 相对于backend目录
  host_path: "./workspace"       # 相对于项目根目录

ftp:
  enabled: true
  host: "0.0.0.0"
  port: 2121
  username: "sage"
  password: "sage123"
  root_directory: "../workspace"
  max_connections: 50
```

### Docker环境
```yaml
# backend/config.docker.yaml
workspace:
  root_path: "/app/workspace"    # 容器内路径
  host_path: "./workspace"       # 主机映射路径

ftp:
  enabled: true
  host: "0.0.0.0"
  port: 2121
  username: "sage"
  password: "sage123"
  root_directory: "/app/workspace"
  max_connections: 50
```

## 🚀 启动服务

### 本地启动
```bash
# 启动所有服务
./start_services.sh

# 或者分别启动
cd backend
python main.py
```

### Docker启动
```bash
# 启动容器服务
docker compose up -d

# 查看日志
docker compose logs -f sage_backend
```

## 📂 FTP访问方式

### 连接信息
- **服务器**: `localhost`
- **端口**: `2121`
- **用户名**: `sage`
- **密码**: `sage123`
- **根目录**: 工作空间根目录

### 1. 命令行访问
```bash
# 使用内置ftp客户端
ftp localhost 2121

# 输入用户名和密码
Name: sage
Password: sage123

# 常用FTP命令
ftp> ls                    # 列出文件
ftp> cd session_123        # 进入会话目录
ftp> get message_manager.json  # 下载文件
ftp> put local_file.txt    # 上传文件
ftp> quit                  # 退出
```

### 2. 浏览器访问
```
ftp://sage:sage123@localhost:2121
```

### 3. FTP客户端
- **FileZilla**: 
  - 主机: `localhost`
  - 端口: `2121`
  - 用户: `sage`
  - 密码: `sage123`

- **macOS Finder**: `⌘+K` → `ftp://sage:sage123@localhost:2121`
- **Windows资源管理器**: 地址栏输入 `ftp://sage:sage123@localhost:2121`

### 4. 编程访问
```python
import ftplib

# 连接FTP服务器
ftp = ftplib.FTP()
ftp.connect('localhost', 2121)
ftp.login('sage', 'sage123')

# 列出文件
files = ftp.nlst()
print("工作空间文件:", files)

# 下载文件
with open('local_file.json', 'wb') as f:
    ftp.retrbinary('RETR session_123/message_manager.json', f.write)

# 上传文件
with open('upload_file.txt', 'rb') as f:
    ftp.storbinary('STOR uploaded_file.txt', f)

ftp.quit()
```

## 📋 会话状态文件

### message_manager.json
```json
{
  "session_id": "session_123",
  "created_time": "2025-06-25T13:27:02",
  "messages": [
    {
      "role": "user",
      "content": "用户消息",
      "message_id": "msg_001",
      "type": "normal"
    }
  ]
}
```

### task_manager.json
```json
{
  "session_id": "session_123",
  "created_time": "2025-06-25T13:27:02",
  "next_task_number": 3,
  "tasks": {
    "1": {
      "task_id": "1",
      "description": "任务描述",
      "status": "completed",
      "priority": "medium"
    }
  },
  "task_history": []
}
```

## 🔧 故障排除

### FTP服务器无法启动
1. **端口冲突**: 检查端口2121是否被占用
   ```bash
   lsof -i :2121
   ```

2. **权限问题**: 确保工作空间目录有读写权限
   ```bash
   chmod 755 workspace/
   ```

3. **防火墙**: 确保防火墙允许端口2121
   ```bash
   # macOS
   sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /path/to/python
   
   # Linux (ufw)
   sudo ufw allow 2121
   ```

### 无法连接FTP
1. **检查服务状态**: 确认FTP服务已启动
   ```bash
   # 查看进程
   ps aux | grep ftp
   
   # 测试端口
   telnet localhost 2121
   ```

2. **配置检查**: 验证配置文件中的FTP设置
   ```bash
   cd backend
   python -c "from config_loader import get_app_config; print(get_app_config().ftp.__dict__)"
   ```

### 文件权限问题
1. **读取权限**: 确保FTP用户有读取权限
   ```bash
   chmod -R 644 workspace/
   find workspace/ -type d -exec chmod 755 {} \;
   ```

2. **写入权限**: 需要上传文件时
   ```bash
   chmod -R 755 workspace/
   ```

## 📊 监控和日志

### 查看FTP连接日志
```bash
# 查看应用日志
tail -f logs/app.log | grep FTP

# Docker环境
docker compose logs -f sage_backend | grep FTP
```

### API状态检查
```bash
# 检查系统状态（包含FTP状态）
curl http://localhost:8000/api/status

# 预期响应
{
  "status": "running",
  "agents_count": 7,
  "tools_count": 16,
  "active_sessions": 0,
  "ftp_enabled": true,
  "ftp_running": true,
  "workspace_path": "../workspace"
}
```

## 🎯 最佳实践

1. **定期备份**: 定期备份工作空间重要文件
2. **权限管理**: 生产环境中使用更复杂的FTP认证
3. **监控空间**: 监控工作空间磁盘使用情况
4. **日志清理**: 定期清理过期的会话日志
5. **安全考虑**: 生产环境建议使用FTPS或SFTP

## 📱 前端集成

未来可以在React前端添加文件管理功能：
- 会话文件浏览器
- 文件上传/下载界面
- 工作空间使用统计
- 实时文件同步显示 