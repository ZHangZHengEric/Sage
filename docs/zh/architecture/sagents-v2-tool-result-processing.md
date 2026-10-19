# 工具结果处理

标准 v2 组合默认启用 `tool.result-processor`，内置实现为
`sage.tool.result-processor.file`。它在工具执行或对账完成后、结果提交和进入模型历史前处理结果，
统一覆盖内置工具、MCP、A2A 等工具提供方。自定义 Loop 可通过 `ToolResultProcessor` 端口注入实现。

```yaml
capabilities:
  tool.result-processor:
    plugin: sage.tool.result-processor.file
    config:
      max_inline_characters: 12000
```

`max_inline_characters` 是单次工具返回中所有文本和 JSON 内容合并后的字符上限，默认 12000，
必须为正整数。超过后，保留原始文本前 12000 个字符（或配置的数量），再附上状态和完整文件路径；
提示不占预览字符额度。它不表示 token、字节或图片大小。
Server 的默认插件配置及 Agent 自定义插件配置都可调整，沿用现有配置冻结和生效规则。

完整 `ToolExecutionResult` 保存到当前执行工作区 `.sage/tool-results/<hash>.json`，
包含未裁剪内容、错误和元数据。文件通过 Runtime 的签名沙箱操作写入，遵守租户隔离、目录和容量策略。
Server Linux 返回 `/workspace/...`，Desktop 返回原生工作区路径。
结果以完整 JSON 保存，模型可分段读取或用 shell 提取指定字段，避免再次读取全部内容。

模型和持久化工具结果均使用同一份受限预览，保留调用 ID、操作 ID、成功或失败状态以及图片等非文本块。
`context_reference` 指向完整文件，后续上下文压缩可进一步改用引用。文件属于工作区，
不会在 Run 结束时删除，避免中断恢复或后续回合引用失效。

无可写执行工作区或保存失败时，保留原始结果并记录 `tool.result.offload_unavailable` /
`tool.result.offload_failed`。这属于显式降级，不保证该次结果满足内联上限；不得丢失结果、
把执行成功伪装成工具失败，或为此重新执行工具。

摘要压缩继续由模型报告的输入量或实际 API 拒绝触发。近期窗口中有单批结果占历史体积一半以上时，
在保留最新完整批次及精确用户请求的前提下，优先将覆盖该大结果的完整前缀纳入摘要。
仅达到建议用量阈值且没有新增可压缩历史时，复用摘要；实际 API 拒绝仍可重新压缩旧摘要以恢复。
摘要后下一次模型报告仍超过阈值且输入量下降不足 10% 时，暂停自动预压缩，
直到低于阈值或上下文相比暂停点增长至少 25%。实际 API 拒绝的必要恢复不受此暂停限制，
仍遵守现有次数上限和无进展保护。
模型仅多回传框架派生任务字段时，由权威状态覆盖，无需重试整次摘要；必需字段缺失、类型错误和未知字段仍拒绝。

诊断事件 `context.compression.usage_pressure` 记录报告用量及阈值，
`context.summary.selection` 记录摘要版本、覆盖范围及选中/保留字符数，
`tool.result.offloaded` 记录处理前后长度，不写入业务内容。
