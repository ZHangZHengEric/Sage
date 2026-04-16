# 统一图片生成服务（Unified Image Generation Service）

## 模块概述

`Unified Image Generation Service` 是 **sage Agent** 项目的核心组件之一，基于 **MCP（Model Context Protocol）** 协议构建。它提供了一个高度抽象、支持多厂商的图片生成接口，能够根据提示词、宽高比及参考图自动调用最合适的后端服务。

## ✨ 核心特性

### 多厂商集成
原生支持以下图片生成服务提供商：

- **Minimax（海螺 AI）**
- **阿里云百炼（Qwen / 万相）**
- **火山引擎（Seedream / 豆包）**

### 智能服务发现
自动检测环境变量，动态加载已配置的生成器。

### 人物 / 风格一致性
支持参考图（`Reference Image`）输入，优先路由至具备图生图能力的模型，以保持人物一致性或实现风格迁移。

### 灵活输出
支持以下两种输出方式：

- 直接返回 Base64 数据流
- 将结果保存至指定本地路径

### 异常回退机制
当默认引擎调用失败时，自动尝试其他可用的提供商。

## 🛠️ 快速配置

本模块通过环境变量进行配置。你至少需要配置以下其中一组密钥。

### 1. 阿里云百炼（Qwen / 万相）

```bash
export QWEN_API_KEY=your_api_key_here
export QWEN_MODEL=wanx2.1-t2i-plus  # 推荐模型
```

### 2. Minimax（海螺 AI）

```bash
export MINIMAX_API_KEY=your_api_key_here
export MINIMAX_MODEL=image-01
```

### 3. 火山引擎（Seedream / 豆包）

```bash
export SEEDREAM_API_KEY=your_api_key_here
export SEEDREAM_MODEL=doubao-seedream-5.0-lite
```

## 🚀 MCP 工具使用指南

模块通过 `generate_image` 工具对外暴露能力。

### `generate_image` 参数说明

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `prompt` | `string` | 是 | - | 图片描述词，建议包含风格、场景、光影细节 |
| `aspect_ratio` | `string` | 否 | `1:1` | 比例支持：`1:1`、`16:9`、`4:3`、`3:2`、`2:3`、`9:16` |
| `reference_image` | `string` | 否 | `""` | 参考图 URL，用于保持人物一致性或风格迁移 |
| `output_path` | `string` | 否 | `""` | 本地保存路径；若提供，则返回路径；若不提供，则返回 Base64 |

## 🏗️ 架构设计

模块采用了典型的**工厂模式（Factory Pattern）+ 适配器模式（Adapter Pattern）**结构。

### `BaseImageProvider`
定义所有厂商必须实现的抽象接口，包括：

- API 调用
- 错误处理
- 环境变量校验

### Provider 适配器

#### `MinimaxProvider`
处理海螺 AI 的异步 / 同步请求。

#### `QwenProvider`
实现阿里云百炼的任务轮询（Polling）机制。

#### `SeedreamProvider`
对接火山引擎方舟平台的最新 V3 接口。

### Unified Server
负责逻辑路由，根据 `reference_image` 参数和模型可用性选择最优路径。

## 📂 文件结构

```plaintext
.
├── unified_image_generation_server.py  # MCP 服务入口及路由逻辑
└── image_providers/
    ├── __init__.py           # Provider 枚举与结果格式定义
    ├── base.py               # 基类定义
    ├── minimax_provider.py   # Minimax 适配器
    ├── qwen_provider.py      # 阿里云百炼适配器
    └── seedream_provider.py  # 火山引擎适配器
```

## 📝 开发扩展

若要添加新的图片生成厂商（如 Midjourney 或 OpenAI DALL-E 3），可按以下步骤进行扩展：

1. 在 `image_providers/` 下继承 `BaseImageProvider` 创建新类。
2. 实现 `generate_image` 方法，处理特定 API 逻辑。
3. 在 `unified_image_generation_server.py` 的 `PROVIDER_CLASSES` 字典中注册该类。
4. 在 `ImageProviderEnum` 中添加对应的枚举值。

## ⚠️ 注意事项

### 超时控制
图片生成通常较慢，内部已针对各厂商设置了 30s–60s 的 timeout。

### 模型支持
不同模型支持的宽高比可能略有差异，模块内部已根据官方文档做了 `SIZE_MAP` 映射。

### 网络需求
由于调用的是国内主流云厂商 API，请确保服务器网络能够正常访问以下端点：

- 阿里云
- 火山引擎
- Minimax

## 总结

统一图片生成服务通过抽象统一的接口，将多个图片生成厂商接入到同一套 MCP 服务框架中，具备以下优势：

- 多厂商统一接入
- 自动服务发现
- 支持参考图一致性控制
- 灵活输出 Base64 或文件路径
- 默认失败后自动回退到其他可用提供商

这使其能够作为 sage Agent 项目中的通用图片生成底层能力模块，便于后续扩展更多模型与服务商。
