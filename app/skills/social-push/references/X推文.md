## 发布推文 workflow

1. 打开 X 发布页面：`agent-browser --auto-connect open "https://x.com/compose/post"`
2. 查看交互：`agent-browser snapshot -i`
3. 输入推文内容：`agent-browser fill @e6 "{推文内容}"`
4. （可选）上传图片：点击 @e9 "添加照片或视频"，或使用 `agent-browser upload @e10 "{图片路径}"`
5. 等待上传完成：`agent-browser wait 2000`
6. 查看当前状态：`agent-browser snapshot -i`
7. 保存草稿：`agent-browser click @e4` （草稿按钮）
8. 提示用户手动确认发布，不自动点击"发帖"按钮

## 元素参考

| 元素 | 功能 |
|------|------|
| @e4 | 草稿 |
| @e6 | 帖子文本输入框 |
| @e9 | 添加照片或视频 |
| @e10 | 文件上传 |
| @e11 | 添加 GIF |
| @e19 | 发帖按钮（禁止自动点击） |

## 注意事项

- 推文字数限制：普通用户**280 字符**，Premium 用户更多
- 图片支持格式：JPG、PNG、GIF，最多 4 张图片
- 添加话题标签：直接在推文内容中加入 `#话题`
