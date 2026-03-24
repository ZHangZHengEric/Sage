## 发布 Linux.do 帖子 workflow

1. 打开 Linux.do 首页：`agent-browser --auto-connect open "https://linux.do/"`
2. 查看交互元素：`agent-browser --auto-connect snapshot -i`
3. 点击 `新建话题` 按钮进入编辑器（ref 以 snapshot 为准）
4. 再次查看交互元素：`agent-browser --auto-connect snapshot -i`
5. 填写标题：`agent-browser --auto-connect fill @标题输入框 "{标题}"`
6. 选择类别（必选）：
   `agent-browser --auto-connect click @类别下拉框`
   `agent-browser --auto-connect snapshot -i`
   `agent-browser --auto-connect click @目标类别选项`
7. 添加标签（建议至少 1 个）：
   `agent-browser --auto-connect click @标签下拉框`
   `agent-browser --auto-connect snapshot -i`
   `agent-browser --auto-connect fill @标签搜索框 "{标签1}"`
   `agent-browser --auto-connect press Enter`
8. 多标签时，重复第 7 步（每个标签输入后回车确认）
9. 输入正文：`agent-browser --auto-connect fill @正文输入框 "{内容}"`
10. 查看当前状态：`agent-browser --auto-connect snapshot -i`
11. 仅保存草稿或停留编辑页，不自动点击 `创建话题`：
    - 可选：点击 `保存并关闭`（保存草稿）
    - 或保持页面停留，提示用户手动确认并点击 `创建话题`

## 元素参考（示例，实际以 snapshot 为准）

| 元素 | 功能 | 说明 |
|------|------|------|
| `textbox "输入标题，或在此处粘贴链接"` | 标题输入框 | 发帖标题 |
| `listbox "筛选条件：xxx"` | 类别下拉 | 必须选择一个有效类别 |
| `menuitemradio "开发调优/资源荟萃/..."` | 类别选项 | 点击具体类别 |
| `listbox "至少选择 1 个标签…"` | 标签入口 | 打开标签选择 |
| `searchbox "搜索…"` | 标签搜索框 | 输入标签名后回车 |
| `textbox "在此处输入..."` | 正文输入框 | Markdown 编辑区域 |
| `button "保存并关闭"` | 草稿按钮 | 安全结束，避免误发布 |
| `button "创建话题"` | 发布按钮 | 禁止自动点击 |

## 注意事项

- Linux.do 发帖通常要求先选类别，部分类别要求至少 1 个标签
- 类别/标签是动态列表，必须在展开后重新 `snapshot -i` 获取最新 ref
- 标签推荐做法：输入关键词 -> 回车确认；如果出现候选项，也可以直接点击候选项
- 遇到 Cloudflare `Just a moment...` 页面时，等待或改为从首页进入后再点 `新建话题`
- 严格遵守规则：最终只到草稿或待发布状态，不自动点击 `创建话题`
