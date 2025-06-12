# Execute Command MCP Server

一个安全、强大的命令执行MCP服务器，支持Shell命令执行、Python代码运行、系统监控等功能。

## 🚀 主要特性

### 🔒 安全机制
- **命令安全检查**：内置危险命令黑名单，防止执行破坏性操作
- **恶意模式检测**：识别并阻止潜在的恶意命令模式
- **可配置安全级别**：可选择启用危险命令执行模式
- **进程隔离**：每个命令在独立的进程中执行

### ⚡ 执行控制
- **超时管理**：可配置的命令执行超时时间
- **进程管理**：自动清理和终止超时进程
- **环境变量支持**：自定义执行环境
- **工作目录控制**：指定命令执行的工作目录

### 📊 系统监控
- **系统信息获取**：CPU、内存、磁盘使用情况
- **命令可用性检查**：验证系统中可用的命令
- **执行统计**：命令执行时间和结果统计
- **详细日志记录**：完整的操作日志

## 🛠 工具列表

### 1. execute_shell_command
在指定目录执行Shell命令

**参数：**
- `command` (str): 要执行的Shell命令
- `workdir` (str, 可选): 命令执行的工作目录
- `timeout` (int, 可选): 超时时间，默认30秒
- `env_vars` (dict, 可选): 自定义环境变量

**返回：**
```json
{
  "success": true,
  "return_code": 0,
  "stdout": "命令输出",
  "stderr": "错误输出",
  "command": "执行的命令",
  "workdir": "工作目录",
  "execution_time": 1.23,
  "process_id": "proc_1234567890"
}
```

### 2. execute_python_code
执行Python代码

**参数：**
- `code` (str): 要执行的Python代码
- `workdir` (str, 可选): 代码执行的工作目录
- `timeout` (int, 可选): 执行超时时间，默认30秒
- `requirements` (list, 可选): 需要安装的包列表

**返回：**
```json
{
  "success": true,
  "output": "代码输出",
  "error": null,
  "return_code": 0,
  "installed_packages": ["pandas", "numpy"],
  "code": "执行的代码",
  "workdir": "工作目录"
}
```

### 3. get_system_information
获取系统信息

**返回：**
```json
{
  "success": true,
  "system_info": {
    "platform": "Darwin",
    "architecture": "arm64",
    "python_version": "3.11.5",
    "cpu_count": 8,
    "memory_total": 17179869184,
    "memory_available": 8589934592,
    "disk_usage": {
      "total": 1000204886016,
      "used": 500102443008,
      "free": 500102443008
    },
    "process_count": 342
  }
}
```

### 4. check_command_availability
检查命令可用性

**参数：**
- `commands` (list): 要检查的命令列表

**返回：**
```json
{
  "success": true,
  "available_commands": ["python", "git", "npm"],
  "unavailable_commands": ["docker", "kubectl"],
  "command_paths": {
    "python": "/usr/bin/python",
    "git": "/usr/bin/git"
  },
  "total_checked": 5
}
```

## 📦 安装和配置

### 依赖包安装
```bash
pip install psutil fastmcp starlette uvicorn
```

### 启动服务器
```bash
# 基本启动
python execute_command.py

# 自定义配置
python execute_command.py --port 34010 --host 0.0.0.0 --max_timeout 600

# 启用危险命令执行（谨慎使用）
python execute_command.py --enable_dangerous_commands
```

### 启动参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `--port` | int | 34010 | 服务器端口 |
| `--host` | str | 0.0.0.0 | 服务器主机 |
| `--max_timeout` | int | 300 | 最大超时时间(秒) |
| `--enable_dangerous_commands` | bool | false | 启用危险命令执行 |

## 🔐 安全特性

### 危险命令黑名单
以下命令被默认阻止执行：
- 文件删除：`rm`, `rmdir`, `del`
- 系统格式化：`format`, `fdisk`, `mkfs`
- 权限管理：`sudo`, `su`, `chmod`, `chown`
- 系统控制：`shutdown`, `reboot`, `systemctl`
- 进程管理：`kill`, `killall`, `pkill`

### 恶意模式检测
自动检测以下潜在恶意模式：
- 命令链接：`&&`, `||`, `;`
- 管道操作：`|`, `>`, `>>`
- 命令替换：`$(`, `` ` ``
- 动态执行：`eval`, `exec`

### 安全建议
1. **生产环境不要启用危险命令执行**
2. **设置合理的超时时间限制**
3. **监控服务器日志以发现异常活动**
4. **使用专用的低权限用户运行服务**

## 🧪 使用示例

### 基本命令执行
```python
# 查看当前目录
result = await execute_shell_command("ls -la", workdir="/tmp")

# 安装Python包
result = await execute_shell_command("pip install pandas", timeout=60)
```

### Python代码执行
```python
# 执行数据分析代码
code = """
import pandas as pd
import numpy as np

data = np.random.rand(100, 3)
df = pd.DataFrame(data, columns=['A', 'B', 'C'])
print(df.describe())
"""

result = await execute_python_code(
    code=code,
    requirements=["pandas", "numpy"],
    timeout=60
)
```

### 系统监控
```python
# 获取系统信息
system_info = await get_system_information()

# 检查开发环境
commands = ["python", "node", "git", "docker", "kubectl"]
availability = await check_command_availability(commands)
```

## 📊 性能监控

### 执行统计
- **命令执行时间**：每个命令的精确执行时间
- **成功率统计**：命令执行成功/失败比率
- **资源使用**：系统资源使用情况监控
- **错误分析**：详细的错误日志和分析

### 日志记录
服务器会记录以下信息：
- 命令执行详情
- 安全检查结果
- 错误和异常信息
- 系统资源使用情况

## 🐛 故障排除

### 常见问题

**Q: 命令执行被阻止**
A: 检查命令是否在危险命令黑名单中，或使用 `--enable_dangerous_commands` 参数

**Q: 命令执行超时**
A: 增加 `timeout` 参数值或调整 `--max_timeout` 配置

**Q: Python代码执行失败**
A: 检查代码语法、依赖包是否正确安装

**Q: 系统信息获取失败**
A: 确保 `psutil` 包已正确安装

### 调试模式
启用详细日志记录：
```bash
export PYTHONPATH=/path/to/execute_command
python -c "import logging; logging.basicConfig(level=logging.DEBUG)"
python execute_command.py
```

## 🔄 版本历史

### v2.0.0
- 完全重构代码架构
- 添加安全管理器和进程管理器
- 增强错误处理和日志记录
- 添加Python代码执行功能
- 增加系统监控工具
- 改进命令安全检查

### v1.0.0
- 基本命令执行功能
- 简单的错误处理

## 📝 许可证

MIT License

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个项目。

## 📞 支持

如有问题或建议，请创建Issue或联系开发团队。 