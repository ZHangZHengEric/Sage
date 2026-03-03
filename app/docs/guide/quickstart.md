# 快速开始

本指南将帮助你在几分钟内开始使用 Sage。

## 前置要求

- macOS 或 Linux 系统
- 已安装 Sage Desktop 应用

---

## 第一步：启动应用

1. 打开 Sage Desktop 应用
2. 首次启动时会显示初始化向导
3. 点击 **"开始使用"** 进入配置

![初始化向导 - 欢迎页面](/images/setup-welcome.png)

---

## 第二步：配置模型提供商

Sage 需要配置至少一个模型提供商才能正常工作。

### 选择提供商

点击 **"模型提供商"**，选择你要使用的提供商：

- **OpenAI** - GPT-4、GPT-3.5 等
- **DeepSeek** - DeepSeek Chat、Coder 等
- **Aliyun** - 通义千问系列（推荐 qwen3.5）
- **ByteDance** - 豆包大模型
- **OpenRouter** - 聚合多种模型

![选择模型提供商](/images/setup-provider-select.png)

### 填写配置

根据所选提供商填写配置信息：

1. **Base URL** - API 基础地址
2. **API Key** - 你的 API 密钥
3. **模型名称** - 如 `qwen3.5-32b`、`gpt-4` 等
4. **最大 Token** - 单次请求最大 token 数（默认 4096）
5. **温度值** - 控制输出随机性（默认 0.7）

![模型提供商配置](/images/setup-provider-config.png)

### 验证连接

填写完成后，点击左下角的 **"验证连接"** 按钮：

- 验证成功后会显示绿色提示
- 验证失败请检查配置信息

![验证成功](/images/setup-verify-success.png)

::: tip 提示
**推荐模型**：

**国内模型**：
- 阿里云通义千问 - 性价比高，中文表现优秀
- Moonshot Kimi - 长文本处理能力强
- DeepSeek - 代码能力突出

**国外模型**：
- OpenAI GPT - 综合能力最强
- Anthropic Claude - 推理能力优秀
- xAI Grok - 实时信息获取
- Google Gemini - 多模态能力强

**自定义提供商**：
Sage 支持任何兼容 OpenAI API 格式的提供商，只需填写对应的 Base URL 和 API Key。
:::

---

## 第三步：完成初始化

验证成功后，点击 **"下一步"** 完成初始化。Sage 会自动为你创建一个默认智能体。

![主界面](/images/main-interface.png)

---

## 开始使用

### 与默认智能体对话

1. 点击左侧菜单 **"新对话"**
2. 右上角会默认选中系统创建的默认智能体
3. 在底部输入框输入消息，按 Enter 发送

![对话示例](/images/chat-example.png)

### 创建自定义智能体

如果你想创建更多智能体，可以参考 [智能体管理](../agent/) 文档。

---

## 下一步

- [了解更多智能体功能](../agent/) - 创建和管理多个智能体
- [配置工具扩展能力](../tools/) - 让智能体使用外部工具
- [设置 IM 渠道接入](../im/) - 在钉钉、飞书等平台使用智能体
