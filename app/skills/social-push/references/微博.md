## 发布微博 workflow

1. 打开微博主页：`agent-browser --auto-connect open "https://weibo.com"`
2. 查看交互元素：`agent-browser snapshot -i`
3. 点击输入框（可选）：`agent-browser click @e{输入框ref}`
4. 填写微博内容：`agent-browser fill @e{输入框ref} "{微博内容}"`
5. （可选）上传图片：`agent-browser upload "input[type='file']" "{图片路径}"`
6. （可选）添加话题：在内容中直接输入 `#话题#` 格式（前后都需要 # 号）
7. 查看当前状态：`agent-browser snapshot -i`
8. 提示用户手动点击"发送"按钮确认发布，不自动点击

## 元素参考

| 元素 | 功能 | 说明 |
|------|------|------|
| @e36 | 微博内容输入框 | "有什么新鲜事想分享给大家？" |
| @e37/e38 | 发送按钮 | 输入内容后会被激活 |
| input[type='file'] | 文件上传元素 | 用于上传图片和视频 |

## 注意事项

- **微博字数限制**：普通用户 140 字，会员用户 2000 字
- **图片支持格式**：JPG、PNG、GIF、HEIF、HEIC，最多 9 张图片
- **视频支持格式**：MP4、M4V、MKV、FLV
- **话题标签格式**：`#话题内容#` （前后都需要 # 号）
- **元素 ref 变化**：每次操作后用 `agent-browser snapshot -i` 重新确认元素编号
- **无草稿功能**：微博的简单发布框没有保存草稿功能，只能通过不点击发送按钮来保留内容

## 常见问题

1. **元素 ref 变化**：每次操作后用 `agent-browser snapshot -i` 重新确认元素编号
2. **上传失败**：检查图片格式和大小，单张图片不超过 5MB
3. **内容被限制**：微博有敏感词过滤，发布前建议用户自行检查
4. **图片上传后出现 Choose File 按钮**：这是正常现象，表示文件上传功能已被触发
