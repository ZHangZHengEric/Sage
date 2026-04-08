# Sage Browser Bridge Extension

这是一个本地 Chrome 插件前端，用于连接 Sage Desktop 后端：

- 浏览器右侧 Side Panel 里直接对话（调用 Desktop 的 `/api/web-stream`）。
- 自动检测本地 Sage 服务是否启动；未启动时禁止使用对话能力。
- 插件持续上报当前页面上下文（标题、URL、选中文本、正文摘要）。
- 插件轮询 Desktop 的浏览器命令队列，并在当前标签页执行操作。
- 插件图标使用 Sage logo。

## 1. 加载插件

1. 打开 `chrome://extensions/`
2. 打开右上角「开发者模式」
3. 点击「加载已解压的扩展程序」
4. 选择目录：`app/chrome-extension`

## 2. 配置/检测本地服务

插件默认自动探测：

- `http://127.0.0.1:8000`
- `http://localhost:8000`
- `http://127.0.0.1:8080`
- `http://localhost:8080`

如果你本地端口不同，可以在插件弹窗中手动填写后端地址并保存。

## 3. Side Panel 使用方式

点击浏览器工具栏中的 Sage 图标，会自动打开浏览器右侧 Side Panel（分屏模式）。

## 4. 浏览器命令动作示例

`browser_run_action` 支持：

- `navigate`：`{"url":"https://example.com"}`
- `click`：`{"selector":"button.submit"}`
- `fill`：`{"selector":"input[name=q]","value":"Sage","submit":true}`
- `extract_text`：`{"selector":"main","maxChars":4000}`
- `run_script`：`{"code":"({ title: document.title, href: location.href })"}`
