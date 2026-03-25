# 环境变量配置

Sage 使用环境变量来配置各种外部服务的 API 密钥和系统设置。这些环境变量存储在 `~/.sage/sage_env` 文件中。

## 配置文件位置

```
~/.sage/sage_env
```

## 配置方法

### 方法一：通过系统设置界面（推荐）

1. 打开 Sage 应用
2. 进入「系统设置」→「环境变量」
3. 点击「配置」按钮
4. 选择预设的环境变量或手动添加
5. 保存后**重启 Sage** 使配置生效

### 方法二：手动编辑文件

直接编辑 `~/.sage/sage_env` 文件，格式如下：

```bash
# 搜索引擎 API Keys
SERPAPI_API_KEY=your_serpapi_key_here
TAVILY_API_KEY=your_tavily_key_here

# 图片生成 API Keys
MINIMAX_API_KEY=your_minimax_key_here
QWEN_API_KEY=your_qwen_key_here

# 代理设置
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890
```

**注意**：修改后需要重启 Sage 应用才能生效。

## 环境变量列表

### 搜索引擎 API Keys

用于 MCP 搜索服务器，让 Agent 能够搜索网络信息。

| 环境变量 | 说明 | 获取地址 |
|---------|------|---------|
| `SERPAPI_API_KEY` | SerpApi Google 搜索 API Key | [serpapi.com](https://serpapi.com) |
| `SERPER_API_KEY` | Serper Google 搜索 API Key | [serper.dev](https://serper.dev) |
| `TAVILY_API_KEY` | Tavily 搜索 API Key | [tavily.com](https://tavily.com) |
| `BRAVE_API_KEY` | Brave 搜索 API Key | [brave.com/search/api](https://brave.com/search/api) |
| `ZHIPU_API_KEY` | 智谱 AI 搜索 API Key | [bigmodel.cn](https://bigmodel.cn) |
| `BOCHA_API_KEY` | 博查搜索 API Key | [bochaai.com](https://bochaai.com) |
| `SHUYAN_API_KEY` | 数眼搜索 API Key | [shuyanai.com](https://shuyanai.com) |

### 图片生成 API Keys

用于统一图片生成服务，让 Agent 能够生成图片。

#### Minimax (海螺 AI)

| 环境变量 | 说明 | 示例值 |
|---------|------|--------|
| `MINIMAX_API_KEY` | Minimax API Key | `your_minimax_api_key` |
| `MINIMAX_MODEL` | 图片生成模型 | `image-01` |

获取地址：[platform.minimaxi.com](https://platform.minimaxi.com)

#### 阿里云百炼 (Qwen)

| 环境变量 | 说明 | 示例值 |
|---------|------|--------|
| `QWEN_API_KEY` | 阿里云百炼 API Key | `your_qwen_api_key` |
| `QWEN_MODEL` | 图片生成模型 | `wanx2.1-t2i-plus` |

支持的模型：
- `wanx2.1-t2i-plus` - 万相-文生图V2 (推荐)
- `wanx2.1-t2i-turbo` - 万相-文生图V2-Turbo
- `wanx2.1-t2i` - 万相-文生图V2-标准版
- `wanx-v1` - 万相-文生图V1

获取地址：[bailian.console.aliyun.com](https://bailian.console.aliyun.com)

#### 火山引擎 Seedream

| 环境变量 | 说明 | 示例值 |
|---------|------|--------|
| `SEEDREAM_API_KEY` | 方舟平台 API Key | `your_seedream_api_key` |
| `SEEDREAM_MODEL` | 图片生成模型 | `doubao-seedream-5.0-lite` |

支持的模型：
- `doubao-seedream-5.0-lite` - Seedream 5.0 Lite (默认)
- `doubao-seedream-4.5` - Seedream 4.5
- `doubao-seedream-3.0-t2i` - Seedream 3.0

获取地址：[console.volcengine.com/ark](https://console.volcengine.com/ark)

### 代理设置

用于配置系统代理，影响所有网络请求。

| 环境变量 | 说明 | 示例值 |
|---------|------|--------|
| `HTTP_PROXY` | HTTP 代理地址 | `http://127.0.0.1:7890` |
| `HTTPS_PROXY` | HTTPS 代理地址 | `http://127.0.0.1:7890` |
| `ALL_PROXY` | 全局代理地址 (SOCKS5) | `socks5://127.0.0.1:7890` |

## 使用说明

### 优先级

1. 系统设置界面中配置的环境变量会保存到 `~/.sage/sage_env`
2. Sage 启动时会自动加载该文件中的环境变量
3. 环境变量会注入到所有子进程（包括 MCP 服务器）

### 重启要求

**修改环境变量后必须重启 Sage 才能生效**，因为：
- 环境变量在应用启动时加载
- MCP 服务器等子进程继承启动时的环境变量
- 运行时的修改不会影响已启动的进程

### 安全性

- `~/.sage/sage_env` 文件存储在用户主目录下
- 建议设置适当的文件权限（仅用户可读写）
- 不要将包含 API Keys 的文件提交到版本控制

## 故障排查

### 环境变量未生效

1. 确认文件路径正确：`~/.sage/sage_env`
2. 确认文件格式正确：`KEY=value`（无引号，无空格）
3. 确认已重启 Sage 应用
4. 检查系统设置界面中是否正确显示

### API Key 无效

1. 确认 API Key 已正确复制（无多余空格）
2. 确认 API Key 未过期
3. 确认账户有余额或配额
4. 查看对应服务平台的文档获取帮助
