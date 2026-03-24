# Sage 环境变量文档

本文档列出了 Sage 项目中使用的所有环境变量，包括其用途、默认值和使用位置。

## 沙箱相关环境变量

### SAGE\_SANDBOX\_MODE

- **用途**: 指定沙箱运行模式
- **可选值**: `local` | `passthrough` | `remote`
- **默认值**: `local`
- **使用位置**:
  - `sagents/sagents.py:20` - SAgent 初始化时读取
  - `sagents/session_runtime.py:134` - Session 初始化时设置
  - `sagents/context/session_context.py:98` - SessionContext 初始化时读取
  - `sagents/utils/sandbox/config.py:61` - SandboxConfig 从环境变量创建时读取

### SAGE\_SANDBOX\_MOUNT\_PATHS

- **用途**: 沙箱挂载路径列表（逗号分隔）
- **默认值**: 空字符串
- **使用位置**:
  - `sagents/utils/sandbox/config.py:67` - SandboxConfig 从环境变量创建时读取

## 本地沙箱配置

### SAGE\_LOCAL\_CPU\_TIME\_LIMIT

- **用途**: 本地沙箱 CPU 时间限制（秒）
- **默认值**: `300`
- **使用位置**:
  - `sagents/utils/sandbox/config.py:85` - SandboxConfig 从环境变量创建时读取

### SAGE\_LOCAL\_MEMORY\_LIMIT\_MB

- **用途**: 本地沙箱内存限制（MB）
- **默认值**: `4096`
- **使用位置**:
  - `sagents/utils/sandbox/config.py:86` - SandboxConfig 从环境变量创建时读取

### SAGE\_LOCAL\_LINUX\_ISOLATION

- **用途**: Linux 系统隔离模式
- **可选值**: `subprocess` | `bwrap`
- **默认值**: `bwrap`
- **使用位置**:
  - `sagents/utils/sandbox/config.py:87` - SandboxConfig 从环境变量创建时读取

### SAGE\_LOCAL\_MACOS\_ISOLATION

- **用途**: macOS 系统隔离模式
- **可选值**: `subprocess` | `seatbelt`
- **默认值**: `seatbelt`
- **使用位置**:
  - `sagents/utils/sandbox/config.py:88` - SandboxConfig 从环境变量创建时读取

## 远程沙箱配置 (OpenSandbox)

### OPENSANDBOX\_URL

- **用途**: OpenSandbox 服务器 URL
- **默认值**: `None`
- **使用位置**:
  - `sagents/context/session_context.py:361` - 创建远程沙箱时使用
  - `sagents/utils/sandbox/config.py:91` - SandboxConfig 从环境变量创建时读取

### OPENSANDBOX\_API\_KEY

- **用途**: OpenSandbox API 密钥
- **默认值**: `None`
- **使用位置**:
  - `sagents/context/session_context.py:362` - 创建远程沙箱时使用
  - `sagents/utils/sandbox/config.py:92` - SandboxConfig 从环境变量创建时读取

### OPENSANDBOX\_IMAGE

- **用途**: OpenSandbox 容器镜像
- **默认值**: `opensandbox/code-interpreter:v1.0.2`
- **使用位置**:
  - `sagents/context/session_context.py:363` - 创建远程沙箱时使用
  - `sagents/utils/sandbox/config.py:93` - SandboxConfig 从环境变量创建时读取

### OPENSANDBOX\_TIMEOUT

- **用途**: OpenSandbox 请求超时时间（秒）
- **默认值**: `1800`
- **使用位置**:
  - `sagents/context/session_context.py:364` - 创建远程沙箱时使用
  - `sagents/utils/sandbox/config.py:94` - SandboxConfig 从环境变量创建时读取

### SAGE\_OPENSANDBOX\_APPEND\_MAX\_BYTES

- **用途**: OpenSandbox 远程沙箱 append 写入的单次最大字节数（通过环境变量传输时的安全上限）
- **默认值**: `262144` (256KB)
- **使用位置**:
  - `sagents/utils/sandbox/providers/remote/opensandbox.py:18` - append 模式大小限制

### SAGE\_REMOTE\_PROVIDER

- **用途**: 远程沙箱提供者类型
- **可选值**: `opensandbox` | `kubernetes` | `firecracker`
- **默认值**: `opensandbox`
- **使用位置**:
  - `sagents/context/session_context.py:360` - 创建远程沙箱时使用
  - `sagents/utils/sandbox/config.py:90` - SandboxConfig 从环境变量创建时读取

## 运行时环境变量

### SAGE\_USE\_CLAW\_MODE

- **用途**: 是否启用 CLAW 模式（特定功能开关）
- **可选值**: `true` | `false`
- **默认值**: `true`
- **自动设置**: `sage_cli.py` 启动时自动设置为 `true`
- **使用位置**:
  - `sagents/context/session_context.py:261` - SessionContext 初始化时读取
  - `sagents/agent/agent_base.py:586` - AgentBase 中使用

### MEMORY\_ROOT\_PATH

- **用途**: 记忆索引存储根目录（用于 BM25 索引文件存储）
- **默认值**: 用户主目录下的 `.sage/memory` 目录
- **自动设置**: `sage_cli.py` 启动时自动设置为 workspace 的上级目录
- **使用位置**:
  - `sagents/tool/impl/memory_tool.py:94` - MemoryTool 中获取索引路径时使用

## 锁管理相关

### ENABLE\_REDIS\_LOCK

- **用途**: 是否启用 Redis 分布式锁
- **可选值**: `true` | `false`
- **默认值**: `false`
- **使用位置**:
  - `sagents/utils/lock_manager.py:95` - LockManager 初始化时读取

### REDIS\_URL

- **用途**: Redis 服务器 URL
- **默认值**: `redis://localhost:6379/0`
- **使用位置**:
  - `sagents/utils/lock_manager.py:96` - LockManager 初始化时读取

### MEMORY\_LOCK\_EXPIRE\_SECONDS

- **用途**: 内存锁过期时间（秒）
- **默认值**: `1800`
- **使用位置**:
  - `sagents/utils/lock_manager.py:100` - LockManager 初始化时读取

## 调试与性能

### SAGENTS\_PROFILING\_TOOL\_DECORATOR

- **用途**: 启用工具装饰器性能分析
- **可选值**: `1` | `true` | `yes`
- **默认值**: `false`
- **使用位置**:
  - `sagents/tool/tool_base.py:36` - tool 装饰器中读取

## 系统环境变量使用

### PATH

- **用途**: 系统可执行文件搜索路径
- **使用位置**:
  - `sagents/tool/tool_manager.py:60,85-86` - 添加 uv 工具路径
  - `sagents/utils/sandbox/providers/local/local.py:224` - 复制到沙箱环境
  - `sagents/utils/sandbox/providers/passthrough/passthrough.py:136` - 复制到沙箱环境
  - `sagents/utils/sandbox/providers/local/isolation/subprocess.py:297` - 隔离进程环境

### HOME / USERPROFILE

- **用途**: 用户主目录
- **使用位置**:
  - `sagents/utils/common_utils.py:36,52` - 获取用户目录
  - `sagents/utils/sandbox/providers/local/isolation/subprocess.py:314,378` - 隔离进程环境

### SystemRoot / ProgramFiles / ProgramFiles(x86)

- **用途**: Windows 系统目录
- **使用位置**:
  - `sagents/utils/sandbox/providers/local/sandbox.py:47-51` - Windows 默认允许路径

## 使用建议

1. **沙箱模式选择**: 开发测试时使用 `passthrough` 模式，生产环境使用 `local` 或 `remote` 模式
2. **远程沙箱配置**: 使用 OpenSandbox 时需要配置 `OPENSANDBOX_URL` 和 `OPENSANDBOX_API_KEY`
3. **资源限制**: 根据实际需求调整 `SAGE_LOCAL_CPU_TIME_LIMIT` 和 `SAGE_LOCAL_MEMORY_LIMIT_MB`
4. **调试**: 启用 `SAGENTS_PROFILING_TOOL_DECORATOR` 进行性能分析
