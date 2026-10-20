---
layout: default
title: Session 附件与历史总结
parent: 架构
lang: zh
ref: v2-detail-SAGENTS_V2_SESSION_ATTACHMENTS
---

{% include lang_switcher.html %}

# Session 附件与历史总结

`analyze_image` 在沙箱内读取并标准化图片，把 JPEG 快照写入当前 Run 所属的 SessionStore。消息账本保存 `sage-image:<sha256>` 引用；模型推理时从附件快照加载图片，总结时只保留附件标记。原图片路径变化不会改变已保存的快照。旧消息内的 data URL 仍可读取，总结投影会移除其中的图片字节。

`SessionArtifactStore` 是 ArtifactStore 接口的 session 适配器。图片的持久性、授权和生命周期由选中的 session 插件决定，不再另选独立的 artifact 插件。通用 `artifact.store` 仍可用于其他产物。第三方 session 插件需要实现附件接口；不支持时返回 `session.attachments_unsupported`，不会隐式落到另一个存储。

- Ephemeral 插件把字节保存在内存，关闭进程后不保留。
- Filesystem 插件在所属 session 目录的 `attachments/` 下保存不可变二进制文件；先持久化文件，再提交附件清单。失败不会把不存在的附件写进清单；提交前留下的孤立文件随 session 删除回收。完整目录备份包含子 session 和附件。
- MySQL 插件使用相同数据库和表前缀下的附件表；附件字节和 session 清单在同一事务中提交，外键随 session 删除级联回收。不新增 SQLite。

同一 session 的多个 Run 可以读取已有附件。Fork 自动复制父 session 的附件。其他 session 使用引用前应调用 `copy_attachment(source_session_id, target_session_id, artifact_id, context=...)`，该操作同时检查两个 session 的归属，并把不可变快照复制到目标 session。之后删除源 session 不影响目标 session。附件不会单独删除，直到所属 session 被删除，避免破坏历史回放。

`export_session_backup(session_id, context=...)` 导出 session、所有 fork 后代和附件。只有这个显式的可移植备份把二进制编码为 base64，常规消息和状态快照不包含附件 base64。`restore_session_backup(backup, context=...)` 校验归属、树结构、清单、大小和校验和，拒绝覆盖不同的已有 session 或其他 session 的标识。恢复按父到子顺序进行，每个 session 原子提交；整个树不是一个跨 session 事务。中断后可重试相同备份，已完成且内容一致的 session 会跳过。恢复期间应暂停目标 session 的运行。`export_state/load_state` 是内部状态调试接口，不能替代包含附件字节的备份 API。派生总结缓存不属于权威备份，恢复后可以重建。

总结会继续保持原始账本和并行工具执行。遇到超出总结输入预算的完整工具组时，只在总结投影里拆分带调用 ID 的消息，单个大结果再分片，多个小片合并装入预算。整组分片完成后才推进原消息的覆盖位置。失败或调用预算不足不会把未处理的片段标为已总结。该机制解决 `context.summary_source_too_large` 的超大工具组场景；模型网络错误、502 和空总结仍按原错误处理。
