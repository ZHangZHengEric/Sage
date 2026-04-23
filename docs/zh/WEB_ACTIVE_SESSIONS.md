---
layout: default
title: Web 进行中会话接入
nav_order: 12
description: "基于 active_sessions SSE 的 Web 端接入说明"
lang: zh
---

{% include lang_switcher.html %}

# Web 端“进行中的会话”接入指南

本文说明两件事：

1. desktop 前端现在是怎么主动获取“进行中的会话”的。
2. 基于现有后端接口，web 端应该如何补齐同样的能力。

## 目标

我们希望 web 端具备和 desktop 一致的体验：

- 当某个会话正在生成时，侧边栏能自动出现该会话。
- 会话结束后，侧边栏状态自动刷新。
- 用户点击侧边栏中的进行中会话后，可以回到对应会话并继续消费后续流。
- 页面刷新或短暂离开后，可以通过 `last_index` 继续恢复流，而不是从头重复渲染。

## 后端接口契约

后端已经提供了 SSE 接口：

- 路由：`GET /api/stream/active_sessions`
- 返回类型：`text/event-stream`
- 数据格式：每次推送一条 `data: <json>\n\n`

接口实现在 `app/server/routers/chat.py`，核心行为如下：

- 每次连接建立后立即返回一次当前全量快照。
- 当活跃会话列表变化时再次推送最新全量快照。
- 客户端断开时停止推送。

活跃会话列表由 `app/server/services/chat/stream_manager.py` 维护。当前每条会话对象至少包含这些字段：

- `session_id`
- `query`
- `created_at`
- `is_completed`
- `last_activity`

要点是：这个接口推送的是“当前活跃会话的全量列表”，不是单条增量事件。因此前端收到后应当直接以这份列表为准，同步本地缓存。

## Desktop 端现在怎么做

desktop 端的链路比较直接，分成四层。

### 1. Sidebar 挂载时启动订阅

`app/desktop/ui/src/views/Sidebar.vue` 使用 `useSidebarActiveSessions`。  
`app/desktop/ui/src/composables/sidebar/useSidebarActiveSessions.js` 在 `onMounted` 时调用 `startSSESync()`，在 `onUnmounted` 时调用 `stopSSESync()`。

这意味着只要侧边栏还在，SSE 连接就会持续存在，而不是只在 Chat 页面里存在。

### 2. 用单例缓存管理 SSE 连接

`app/desktop/ui/src/composables/chat/useChatActiveSessionCache.js` 里做了几件关键事情：

- 用模块级单例保存 `activeSessions`、`sessionStreamOffsets`、`sseSource`、`subscriberCount`
- 通过 `subscriberCount` 避免重复建立多个 SSE 连接
- 收到服务端快照后，把数据写入 `localStorage.activeSessions`
- 派发 `active-sessions-updated` 事件，让侧边栏和聊天页都能同步刷新

desktop 端把服务端返回的原始字段转换成更适合 UI 的缓存结构，例如：

- `title` / `user_input`：从 `query` 推导
- `status`：运行中时写成 `running`
- `lastUpdate`：由 `last_activity * 1000` 转成毫秒时间戳
- `include_in_sidebar`：标记是否展示在侧边栏

如果某个本地缓存中的会话之前是 `running`，但这次服务端快照里已经不存在了，desktop 会把它标成 `completed`。

### 3. desktop 直接用原生 EventSource

`app/desktop/ui/src/api/chat.js` 的 `subscribeActiveSessions()` 直接调用 `request.sse('/api/stream/active_sessions')`。  
`app/desktop/ui/src/utils/request.js` 里的 `sse()` 最终使用原生 `EventSource` 建连。

desktop 之所以能这样做，是因为它这条链路不依赖“必须通过自定义 Authorization 头传 token”这一前提。对 desktop 来说，直接用 `EventSource` 成本最低。

### 4. Sidebar 只负责展示与跳转

`app/desktop/ui/src/composables/sidebar/useSidebarActiveSessions.js` 从共享缓存中计算 `activeSessionItems`，再在侧边栏里渲染：

- 按 `lastUpdate` 倒序排列
- 根据 `status` 展示运行中 / 已完成图标
- 点击后跳到 `Chat?session_id=...`
- 已完成会话在查看后可从缓存移除

## Web 端接入时和 desktop 的关键差异

web 端最大的差异不是 UI，而是鉴权方式。

`app/server/web/src/utils/request.js` 的请求拦截器会自动加：

```text
Authorization: Bearer <token>
```

但浏览器原生 `EventSource` 不能自定义请求头，所以 web 端如果直接复用 `request.sse()`，通常无法把 Bearer Token 带上。

这就是为什么 web 端更适合用下面这套方式：

1. 先用 `fetch` / `request.getStream()` 建立流式 GET 请求
2. 手动解析 SSE 文本流里的 `data:` 行
3. 在前端模拟一个简化版 `EventSource` 对象，只暴露 `onmessage`、`onerror`、`close`

当前仓库里的 `app/server/web/src/api/chat.js` 已经是按这个思路写的。

## Web 端推荐实现方案

推荐把实现拆成四层，并尽量对齐 desktop 的职责划分。

### 1. API 层：封装 `subscribeActiveSessions`

建议位置：

- `app/server/web/src/api/chat.js`

实现要求：

- 调 `request.getStream('/api/stream/active_sessions')`
- 显式带上 `Accept: text/event-stream`
- 复用现有请求拦截器，让鉴权头自动注入
- 用 `ReadableStreamDefaultReader` + `TextDecoder` 逐段读取
- 按 SSE 规则解析空行和 `data:` 行
- 对外返回一个兼容对象：
  - `onmessage`
  - `onerror`
  - `close()`

这里不需要支持完整 SSE 协议子集；当前后端只发送简单的 `data:` 事件，所以支持以下规则就够了：

- 空行表示一条事件结束
- 只处理 `data: `
- 忽略注释行和未知字段

### 2. 状态层：维护一个全局 active session cache

建议位置：

- `app/server/web/src/composables/chat/useChatActiveSessionCache.js`

建议保持与 desktop 一样的模块级单例结构：

- `activeSessions`
- `sessionStreamOffsets`
- `sseSource`
- `subscriberCount`

收到服务端返回的活跃会话快照后，做下面几步：

1. 遍历远端会话列表，把每条记录标准化为前端缓存结构。
2. 保留本地已有的 `last_index`，不要因为服务端快照刷新而丢掉断点续流位置。
3. 把本地仍是 `running`、但已不在远端快照中的会话标为 `completed`。
4. 更新 `localStorage.activeSessions`。
5. 通过 `window.dispatchEvent(new Event('active-sessions-updated'))` 通知 UI 刷新。

推荐缓存结构示例：

```json
{
  "session_xxx": {
    "title": "用户问题摘要",
    "user_input": "用户问题摘要",
    "status": "running",
    "include_in_sidebar": true,
    "lastUpdate": 1719999999000,
    "last_index": 12
  }
}
```

### 3. 生命周期：把 SSE 订阅挂在全局壳层，而不是只挂在 Chat 页面

这是 web 端最关键的接入点。

当前仓库里，web 的 `useChatLifecycle` 已经会在 Chat 页面挂载时启动 `startSSESync()`，卸载时调用 `stopSSESync()`。  
这能工作，但它有一个明显限制：

- 只要用户离开 Chat 页面，SSE 同步就会停止
- 侧边栏虽然还在，但“进行中的会话”列表不会继续主动刷新

而 desktop 的行为更完整，因为 desktop 把订阅入口放在了侧边栏 composable 上。

对于 web 端，推荐二选一：

### 方案 A：对齐 desktop，把订阅放到 Sidebar

适合“只要左侧侧边栏存在，就要持续刷新进行中会话”的产品预期。

可参考 desktop 的做法，在：

- `app/server/web/src/composables/sidebar/useSidebarActiveSessions.js`

里直接接入：

- `startSSESync()`
- `stopSSESync()`

这样 `app/server/web/src/App.vue` 只要还挂着 `Sidebar`，列表就能持续更新。

### 方案 B：继续放在 Chat 页面

适合“只有进入 Chat 页时才关心进行中会话”的轻量方案。

优点：

- 改动更小
- 连接生命周期更短

缺点：

- 离开 Chat 后侧边栏不会继续刷新
- 行为和 desktop 不完全一致

如果目标是“web 端补齐 desktop 同款体验”，优先推荐方案 A。

### 4. 展示层：Sidebar 只消费缓存，不直接关心 SSE 细节

建议位置：

- `app/server/web/src/views/Sidebar.vue`
- `app/server/web/src/composables/sidebar/useSidebarActiveSessions.js`

Sidebar 只做三件事：

1. 从共享缓存或 `localStorage` 派生 `activeSessionItems`
2. 根据 `status` 决定图标和排序
3. 点击后跳转到 `Chat?session_id=...`

这层不要直接解析 SSE，也不要自己维护连接。这样 web 和 desktop 才能保持一致的模块边界。

## 与续流能力的配合

“进行中的会话”列表本身只解决“发现会话”的问题，真正回到会话后能否无缝继续，还要靠 `/api/stream/resume/{session_id}`。

web 端需要继续保留下面这套配合关系：

- `activeSessions[sessionId].last_index` 记录已经消费到哪个 chunk
- 打开会话时先加载历史消息
- 再调用 `resumeStream(sessionId, last_index)`
- 读到新 chunk 时递增 `last_index`
- 周期性持久化 `last_index`
- 读到 `stream_end` 后把本地状态改成完成态并清理缓存

这样即使用户刷新页面，或者从历史/侧边栏重新进入同一个会话，也不会重复渲染已经消费过的流内容。

## 建议的接入步骤

如果要把这套能力稳定加到 web 端，建议按下面顺序做。

1. 在 `chatAPI` 中实现带鉴权的 `subscribeActiveSessions()`。
2. 在 `useChatActiveSessionCache` 中实现 SSE 连接、重连、缓存同步和 `last_index` 保留。
3. 把 `startSSESync()` / `stopSSESync()` 的调用点上移到全局 Sidebar 或 App 壳层。
4. 让 `Sidebar` 只消费 `activeSessionItems`，展示“进行中的会话”分组。
5. 保留现有 `resumeStream()` 能力，确保点击会话后可继续消费流。
6. 验证异常路径，包括断网、401、页面切换、刷新和流结束。

## 验证清单

建议至少覆盖下面这些场景。

### 基础场景

- 发送一条新消息后，侧边栏立即出现对应会话
- 会话生成完成后，状态从 `running` 变成 `completed`，或者按产品要求从列表移除
- 点击侧边栏中的会话后，可以进入正确的 `session_id`

### 生命周期场景

- 在 Chat 页面生成中切到其他页面，列表仍能继续刷新
- 浏览器刷新后，列表能从本地缓存恢复
- 页面重新进入后，`resumeStream` 能从 `last_index` 继续

### 异常场景

- SSE 连接断开后能自动重连
- token 失效时不会无穷重连
- 服务端返回空列表时，本地运行中的会话能被正确收敛为完成态

## 常见坑

### 1. 把 SSE 当成增量事件流处理

这里服务端发的是“全量快照”，不是“某个会话开始/结束”的单条事件。  
所以前端同步逻辑应该是“用新快照校正本地状态”，而不是只追加。

### 2. 在 web 端直接用原生 EventSource

如果 web 鉴权依赖 `Authorization` 头，原生 `EventSource` 通常不够用。  
这时应该走 `fetch + ReadableStream` 的 SSE 解析方案。

### 3. 只在 Chat 页面启动订阅

这会导致离开 Chat 后，左侧还在显示，但数据不再主动刷新。  
如果目标是对齐 desktop，这个订阅应当上移到全局壳层。

### 4. 覆盖掉本地的 `last_index`

`/api/stream/active_sessions` 不返回流断点。  
前端同步快照时必须保留本地已有的 `last_index`，否则恢复流时会从错误位置继续。

## 当前仓库中的参考实现

如果要直接对照代码，优先看这些文件：

- 后端 SSE 路由：`app/server/routers/chat.py`
- 后端活跃会话管理：`app/server/services/chat/stream_manager.py`
- desktop 订阅封装：`app/desktop/ui/src/composables/chat/useChatActiveSessionCache.js`
- desktop 侧边栏接入：`app/desktop/ui/src/composables/sidebar/useSidebarActiveSessions.js`
- web 带鉴权 SSE 封装：`app/server/web/src/api/chat.js`
- web active session cache：`app/server/web/src/composables/chat/useChatActiveSessionCache.js`
- web 侧边栏展示：`app/server/web/src/composables/sidebar/useSidebarActiveSessions.js`
- web Chat 生命周期：`app/server/web/src/composables/chat/useChatLifecycle.js`

## 结论

如果只是问“desktop 前端怎么做到主动获取进行中的会话”，答案其实很简单：

- 后端通过 `/api/stream/active_sessions` 推送活跃会话全量快照
- desktop 在侧边栏生命周期里建立一个全局 SSE 订阅
- 收到快照后同步到本地缓存
- 侧边栏始终只读缓存并渲染

web 端要补齐这个功能，最重要的不是再造一套 UI，而是：

- 用支持鉴权头的方式订阅 SSE
- 复用一份全局 active session cache
- 把订阅入口放到全局壳层，而不是只放在 Chat 页面里

这样才能真正做到和 desktop 一样的“主动获取进行中的会话”。
