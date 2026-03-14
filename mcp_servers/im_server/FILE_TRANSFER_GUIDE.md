# 企业微信文件传输功能指南

本文档介绍 Sage IM 模块中企业微信文件传输功能的实现和使用方法。

## 功能概述

企业微信文件传输功能支持：

| 功能 | 状态 | 说明 |
|------|------|------|
| 接收文件 | ✅ 已完成 | 自动下载并解密用户发送的文件 |
| 接收图片 | ✅ 已完成 | 支持 PNG/JPG/GIF 等格式 |
| 接收语音 | ✅ 已完成 | 支持语音消息下载 |
| 接收视频 | ✅ 已完成 | 支持视频消息下载 |
| 发送文件 | ✅ 已完成 | 通过分片上传发送文件 |
| 发送图片 | ✅ 已完成 | 发送图片消息 |

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│  企业微信用户                                                │
└────────────────────┬────────────────────────────────────────┘
                     │ WebSocket
┌────────────────────▼────────────────────────────────────────┐
│  WebSocket Client (websocket_client.py)                     │
│  - 接收消息回调 (aibot_msg_callback)                        │
│  - 识别文件类型 (file/image/voice/video)                    │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  文件处理模块 (file_handler.py)                             │
│  - FileDownloader: 下载加密文件                             │
│  - FileDecryptor: AES-256-CBC 解密                         │
│  - FileManager: 文件缓存管理                                │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  IM Server (im_server.py)                                   │
│  - 传递文件信息给 Agent                                     │
│  - 支持 send_file_through_im 工具                          │
└─────────────────────────────────────────────────────────────┘
```

## 发送文件流程

```
┌─────────────────────────────────────────────────────────────┐
│  Agent 调用 send_file_through_im 工具                       │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  ChunkedUploader (chunked_uploader.py)                      │
│  1. 初始化上传 (aibot_init_upload)                          │
│  2. 分片上传 (aibot_upload_chunk)                           │
│     - 每片 ≤ 512KB                                        │
│     - Base64 编码                                         │
│  3. 完成上传 (aibot_finish_upload)                          │
│     → 获取 media_id (3天有效)                              │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  WebSocket 发送文件消息                                     │
│  cmd: aibot_send_msg                                        │
│  msgtype: file/image                                        │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  企业微信用户收到文件                                        │
└─────────────────────────────────────────────────────────────┘
```

## 代码文件说明

### 1. file_handler.py - 文件处理核心

```python
# 主要类和功能

class FileDecryptor:
    """AES-256-CBC 解密器"""
    @staticmethod
    def decrypt(encrypted_data: bytes, aes_key: str) -> bytes

class FileDownloader:
    """文件下载器"""
    async def download(url, aes_key=None, filename=None) -> FileInfo
    
class FileManager:
    """文件管理器"""
    def register_file(file_info: FileInfo) -> str
    def get_file(file_id: str) -> Optional[FileInfo]
    async def cleanup_expired_files()

# 便捷函数
async def download_wechat_file(url, aes_key=None, filename=None) -> FileInfo
```

### 2. chunked_uploader.py - 分片上传器

```python
# 主要类和功能

class ChunkedUploader:
    """企业微信分片上传器"""
    
    CHUNK_SIZE = 512 * 1024  # 512KB 每片
    MAX_CHUNKS = 100         # 最大分片数
    
    async def upload_file(file_path, progress_callback=None) -> UploadResult

class UploadResult:
    success: bool
    media_id: Optional[str]
    error: Optional[str]

# 便捷函数
async def upload_file_to_wechat(file_path, bot_id, secret, progress_callback=None) -> UploadResult
```

### 3. provider.py - Provider 增强

```python
class WeChatWorkProvider:
    # 新增方法
    async def send_file(file_path, chat_id=None, user_id=None, filename=None) -> Dict
    async def send_image(image_path, chat_id=None, user_id=None) -> Dict
    async def _send_media_message(media_id, msg_type, chat_id=None, user_id=None) -> Dict
```

### 4. file_tools.py - MCP 工具

```python
# 新增 MCP 工具

@mcp.tool()
async def send_file_through_im(
    file_path: str,
    provider: str,
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> str:
    """发送文件给 IM 用户"""

@mcp.tool()
async def send_image_through_im(
    file_path: str,
    provider: str,
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> str:
    """发送图片给 IM 用户"""
```

## 使用方法

### 1. 接收文件

当用户在企业微信中发送文件时，系统会自动：

1. 接收 WebSocket 消息回调
2. 识别文件类型 (file/image/voice/video)
3. 下载加密文件
4. AES-256-CBC 解密
5. 保存到临时目录
6. 将文件信息传递给 Agent

Agent 收到的消息格式：
```
【IM文件消息 - 平台: wechat_work, 用户: userid_xxx, 用户ID: userid_xxx】

[FILE消息] report.pdf
文件路径: /var/folders/.../wechat_work_files/20260315_013358_report.pdf
文件名: report.pdf
文件大小: 102456 字节
文件类型: application/pdf
本地路径: /var/folders/.../wechat_work_files/20260315_013358_report.pdf

(P.S. 如需回复该用户，请使用 send_message_through_im 工具，
 如需发送文件请使用 send_file_through_im 工具)
```

### 2. 发送文件

Agent 可以使用工具主动发送文件：

```python
# 发送文件
send_file_through_im(
    provider="wechat_work",
    user_id="userid_xxx",
    file_path="/path/to/document.pdf"
)

# 发送图片
send_image_through_im(
    provider="wechat_work",
    chat_id="chat_xxx",
    file_path="/path/to/image.png"
)
```

### 3. 限制说明

| 限制项 | 值 | 说明 |
|--------|-----|------|
| 单个文件大小 | ≤ 20MB | 企业微信限制 |
| 分片大小 | ≤ 512KB | 每片大小 |
| 最大分片数 | 100 | 最大支持约 50MB |
| media_id 有效期 | 3天 | 临时素材有效期 |
| 下载 URL 有效期 | 5分钟 | 必须在5分钟内下载 |
| 发送频率 | 30条/分钟 | 单会话限制 |

## 测试

### 运行测试脚本

```bash
# 测试文件处理模块
cd /Users/caoqihang/Desktop/vibe_coding/Sage
python3 mcp_servers/im_server/providers/wechat_work/test_file_handler.py

# 测试分片上传模块
python3 mcp_servers/im_server/providers/wechat_work/test_chunked_uploader.py
```

### 预期输出

```
============================================================
WeChat Work File Handler Test Suite
============================================================
============================================================
Test 1: AES-256-CBC Decryption
============================================================
✅ AES decryption test passed!

============================================================
Test 2: File Downloader
============================================================
✅ Downloaded successfully:
   Name: test_download.pdf
   Size: 13264 bytes
✅ File exists verification passed!
...
All tests completed!
```

## 故障排除

### 问题1: 文件下载失败

**症状**: 日志显示 "Failed to download file"

**解决**:
1. 检查 URL 是否过期 (5分钟有效期)
2. 检查网络连接
3. 查看文件大小是否超过限制

### 问题2: 文件解密失败

**症状**: 日志显示 "Decryption failed"

**解决**:
1. 确认 aeskey 是否正确
2. 检查文件是否完整下载
3. 查看日志中的详细错误信息

### 问题3: 上传失败

**症状**: 日志显示 "Upload failed"

**解决**:
1. 检查 BotID 和 Secret 是否正确
2. 确认文件大小不超过 20MB
3. 检查网络连接是否稳定

## 配置说明

无需额外配置，文件传输功能会自动启用。

文件存储位置：
- 临时目录: `{temp_dir}/wechat_work_files/`
- 自动清理: 24小时后自动删除

## 后续优化方向

1. **大文件支持**: 实现断点续传机制
2. **多平台支持**: 扩展飞书、钉钉的文件传输
3. **文件预览**: 生成图片缩略图
4. **持久化存储**: 支持 S3/OSS 等云存储
5. **文件安全**: 病毒扫描、内容过滤
