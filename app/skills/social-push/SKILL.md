---
name: social-push
description: 使用 agent-browser 帮用户将内容发到社交媒体上。当用户需要发布内容、推送文章、上传文章、发帖到社交平台时使用此 skill。
disable-model-invocation: false
allowed-tools: Bash(agent-browser:*), Bash(jq:*), Bash(osascript:*) ,Read
---

用户输入 $ARGUMENTS

# Social-push Skill
你需要使用 bash 运行 agent-browser，并参考 references 中对应平台的 workflow，帮助用户将文章、图片上传到对应的社交平台上

# Rules
1. 打开用户浏览器：`open -na "Google Chrome" / "Microsoft Edge" --args --remote-debugging-port=9222`, 确保用户打开的浏览器支持远程调试
2. 使用 `agent-browser --auto-connect` 自动连接用户的浏览器
3. 最终操作只能是**暂存草稿**，禁止自动点击"发布"按钮，由用户自行确认发布
4. 每步操作后用 `agent-browser snapshot -i` 确认元素 ref，因为页面状态变化可能导致 ref 编号变化

# Core Workflow
1. 确认发布信息 调用 AskUserQuestion tool：目标平台（还是**添加新平台**）、内容类型、内容来源（文件路径/直接输入/ai 创作）、标题、话题标签
2. 简单了解 `agent-browser --help` 可用命令
3. 读取 references 中对应平台和内容类型的 workflow
4. 查看对应平台和内容类型的爆款写作指导，了解如何写出适合该平台的爆款内容
5. 严格按照 workflow 中的步骤逐步执行


# Self-evolution

## fix and verify Workflow
网页交互可能发生变化，references 下面的 workflow 可能失效，按以下步骤修复：
1. 运行 `agent-browser snapshot` 查看当前页面的详细元素
2. 当查找失败，运行 `agent-browser eval "js"` 查看具体 html 元素
3. 验证正确的交互路径后，编辑 references 下对应的 workflow 文件进行修正

## 添加新的社交平台
当用户询问需要新添加一个平台时候，按以下步骤添加：
1. 参考 references 下已有的 workflow 作为模板
2. 用 `agent-browser --help` 查看可用命令 和 agent-browser 的 skill
3. 只有当启动浏览器，完整一步一步测试新的平台交互路径，确保每步操作正确
4. 才能在 references 目录下创建新平台的 workflow 文件，并在下方 References 中添加链接



# References

## 小红书
- `小红书图文` ：查看[小红书图文](./references/小红书图文.md)发布简短文章图文时候需要的 workflow，[小红书图文爆款指导](./references/小红书图文_爆款指导.md)了解如何写出爆款内容
- `小红书长文` ：查看[小红书长文](./references/小红书长文.md)用户发送长文本时候需要的 workflow，[小红书长文爆款指导](./references/小红书长文_爆款指导.md)了解如何写出爆款内容

## X (Twitter)
- `X推文` ：查看[X推文](./references/X推文.md)发布推文时候需要的 workflow，[X推文爆款指导](./references/X推文_爆款指导.md)了解如何写出爆款内容

## 微博 (Weibo)
- `微博` ：查看[微博](./references/微博.md)发布微博时候需要的 workflow，[微博爆款指导](./references/微博_爆款指导.md)了解如何写出爆款内容

## 微信公众号
- `微信公众号文章` ：查看[微信公众号文章](./references/微信公众号文章.md)发布公众号文章时候需要的 workflow，[微信公众号文章爆款指导](./references/微信公众号文章_爆款指导.md)了解如何写出爆款内容

## 掘金
- `掘金文章` ：查看[掘金文章](./references/掘金文章.md)发布掘金文章并自动保存草稿的 workflow，[掘金文章爆款指导](./references/掘金文章_爆款指导.md)了解如何写出爆款内容

## Linux.do
- `LinuxDo发帖` ：查看[LinuxDo发帖](./references/LinuxDo发帖.md)发布帖子（含类别与标签选择）的 workflow，[LinuxDo发帖爆款指导](./references/LinuxDo发帖_爆款指导.md)了解如何写出爆款内容

## 知乎
- `知乎想法` ：查看[知乎想法](./references/知乎想法.md)发布知乎想法时候需要的 workflow，[知乎想法爆款指导](./references/知乎想法_爆款指导.md)了解如何写出爆款内容
