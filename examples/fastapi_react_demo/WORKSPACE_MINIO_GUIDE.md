# 🗂️ 工作空间和MinIO对象存储使用指南

Sage Demo提供了完整的工作空间管理和MinIO对象存储文件访问功能。

## 🔄 数据一致性设计

**重要特性**：本地`workspace`目录与MinIO存储**完全同步**

- 📁 本地`./workspace`目录直接映射为MinIO的`workspace` bucket
- ⚡ 文件变化实时反映：本地创建/修改文件，立即可通过MinIO HTTP API访问
- 🔗 双向访问：既可以通过本地文件系统操作，也可以通过MinIO Web控制台或API访问
- 📊 统一存储：无需手动同步，一份数据，多种访问方式

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

minio:
  enabled: true
  endpoint: "localhost:20044"
  external_endpoint: "localhost:20044"
  access_key: "sage"
  secret_key: "sage123456"
  bucket: "workspace"
  region: "us-east-1"
  secure: false
  console_url: "http://localhost:20045"
```

### Docker环境
```yaml
# backend/config.docker.yaml
workspace:
  root_path: "/app/workspace"    # 容器内路径
  host_path: "./workspace"       # 主机映射路径

minio:
  enabled: true
  endpoint: "minio:9000"         # 容器内访问地址
  external_endpoint: "localhost:20044"  # 外部访问地址
  access_key: "sage"
  secret_key: "sage123456"
  bucket: "workspace"            # 对应本地workspace目录
  region: "us-east-1"
  secure: false
  console_url: "http://localhost:20045"

# Docker volume映射关系：
# ./workspace:/data/workspace  # 本地workspace → MinIO workspace bucket
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
docker compose logs -f sage_minio
```

## 🗄️ MinIO对象存储访问方式

### 连接信息
- **API端点**: `http://localhost:20044`
- **控制台**: `http://localhost:20045`
- **访问密钥**: `sage`
- **秘密密钥**: `sage123456`
- **存储桶**: `workspace`

### 1. Web控制台访问
打开浏览器访问：`http://localhost:20045`
- 用户名: `sage`
- 密码: `sage123456`

在控制台中您可以：
- 📁 浏览文件和文件夹
- ⬆️ 上传文件
- ⬇️ 下载文件
- 🗑️ 删除文件
- 📊 查看存储统计

### 2. HTTP API访问
```bash
# 列出存储桶中的对象
curl -X GET "http://localhost:20044/workspace/" \
  --user "sage:sage123456"

# 上传文件
curl -X PUT "http://localhost:20044/workspace/test.txt" \
  --user "sage:sage123456" \
  --data-binary @local_file.txt

# 下载文件
curl -X GET "http://localhost:20044/workspace/session_123/message_manager.json" \
  --user "sage:sage123456" \
  -o downloaded_file.json
```

### 3. 直接URL访问
由于存储桶设置为public，可以直接通过URL访问文件：
```
http://localhost:20044/workspace/session_123/message_manager.json
http://localhost:20044/workspace/session_123/task_manager.json
```

### 4. Python SDK访问
```python
from minio import Minio
import io

# 创建MinIO客户端
client = Minio(
    "localhost:20044",
    access_key="sage",
    secret_key="sage123456",
    secure=False
)

# 列出对象
objects = client.list_objects("workspace", recursive=True)
for obj in objects:
    print(f"文件: {obj.object_name}, 大小: {obj.size}")

# 下载文件
response = client.get_object("workspace", "session_123/message_manager.json")
data = response.read()
print("文件内容:", data.decode())

# 上传文件
data = io.BytesIO(b"Hello, MinIO!")
client.put_object("workspace", "test.txt", data, len(b"Hello, MinIO!"))

# 获取文件URL（临时访问链接）
from datetime import timedelta
url = client.presigned_get_object("workspace", "session_123/message_manager.json", expires=timedelta(hours=1))
print("临时访问链接:", url)
```

### 5. JavaScript/TypeScript访问
```javascript
import { Client } from 'minio';

// 创建客户端
const minioClient = new Client({
  endPoint: 'localhost',
  port: 20044,
  useSSL: false,
  accessKey: 'sage',
  secretKey: 'sage123456'
});

// 列出文件
const stream = minioClient.listObjects('workspace', '', true);
stream.on('data', (obj) => {
  console.log('文件:', obj.name, '大小:', obj.size);
});

// 上传文件
const fileStream = fs.createReadStream('local_file.txt');
minioClient.putObject('workspace', 'uploaded_file.txt', fileStream, (err, objInfo) => {
  if (err) {
    console.error('上传失败:', err);
  } else {
    console.log('上传成功:', objInfo);
  }
});

// 下载文件
minioClient.getObject('workspace', 'session_123/message_manager.json', (err, dataStream) => {
  if (err) {
    console.error('下载失败:', err);
    return;
  }
  
  let data = '';
  dataStream.on('data', (chunk) => {
    data += chunk;
  });
  
  dataStream.on('end', () => {
    console.log('文件内容:', data);
  });
});
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

## 🔧 MinIO服务管理

### 数据一致性验证
验证本地文件和MinIO的同步效果：

```bash
# 1. 在本地workspace创建测试文件
echo "Hello from local file system" > workspace/test.txt

# 2. 立即通过MinIO API访问
curl http://localhost:20044/workspace/test.txt

# 3. 在MinIO控制台查看
# 访问 http://localhost:20045，登录后可以看到test.txt文件

# 4. 通过MinIO上传文件，本地也能立即看到
# 在MinIO控制台上传文件后，检查本地workspace目录
```

### 实时文件监控
```bash
# 监控workspace目录变化
watch -n 1 'ls -la workspace/'

# 同时在另一个终端监控MinIO bucket
watch -n 1 'curl -s http://localhost:20044/workspace/ | head -20'
```

### 存储桶管理
```bash
# 进入MinIO客户端容器
docker exec -it sage_minio_init mc

# 列出存储桶
mc ls myminio

# 创建新存储桶
mc mb myminio/new-bucket

# 设置存储桶策略
mc policy set public myminio/workspace
```

### 监控和日志
```bash
# 查看MinIO服务日志
docker compose logs -f sage_minio

# 查看MinIO初始化日志
docker compose logs sage_minio_init

# 检查MinIO健康状态
curl http://localhost:20044/minio/health/live
```

## 🔧 故障排除

### MinIO服务无法启动
1. **端口冲突**: 检查端口20044和20045是否被占用
   ```bash
   lsof -i :20044
   lsof -i :20045
   ```

2. **权限问题**: 确保工作空间目录有读写权限
   ```bash
   chmod 755 workspace/
   chmod 755 minio-data/
   ```

3. **存储空间**: 确保有足够的磁盘空间
   ```bash
   df -h
   ```

### 无法访问MinIO控制台
1. **检查服务状态**: 确认MinIO服务已启动
   ```bash
   docker compose ps sage_minio
   ```

2. **网络连接**: 检查防火墙设置
   ```bash
   # macOS
   sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /Applications/Docker.app
   
   # Linux (ufw)
   sudo ufw allow 20044
   sudo ufw allow 20045
   ```

3. **浏览器缓存**: 清除浏览器缓存或使用无痕模式

### 文件上传/下载失败
1. **检查存储桶权限**:
   ```bash
   docker exec sage_minio_init mc policy get myminio/workspace
   ```

2. **验证凭据**: 确认访问密钥和秘密密钥正确

3. **检查文件大小**: MinIO默认最大对象大小为5GB

## 📚 更多资源

- [MinIO官方文档](https://docs.min.io/)
- [MinIO Python SDK](https://docs.min.io/docs/python-client-quickstart-guide.html)
- [MinIO JavaScript SDK](https://docs.min.io/docs/javascript-client-quickstart-guide.html)
- [MinIO REST API](https://docs.min.io/docs/minio-server-api-reference.html)

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