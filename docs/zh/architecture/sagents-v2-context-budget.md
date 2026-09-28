---
layout: default
title: 上下文预算
parent: 架构
nav_order: 6
lang: zh
ref: v2-detail-sagents-v2-context-budget
---

{% include lang_switcher.html %}

# v2 上下文预算

模型每次能接收的内容有限，但会话历史可以持续增长。v2 会先保留固定指令和当前请求，再在剩余空间中安排历史；需要压缩时，为较早的历史生成摘要。下文的 token 数是预算估算，不是模型供应商的计费统计。

所有裁剪与摘要只作用于模型请求投影，不删除 Session 的原始消息、工具结果或事件。`system` 与 `developer` 都是固定指令，不进入历史裁剪或摘要区。

## 预算边界

| 区域 | 默认约束 | 超限处理 |
| --- | --- | --- |
| 固定指令 | 16,384 个估算 token | 明确报错，不截断，也不调用模型压缩固定指令 |
| 当前回合 | 最新真实 user 消息及后续消息，工具调用与结果成组 | 工具结果可使用持久引用；仍放不下则报错 |
| 较早的近期历史 | 最多 4 个单元、8,192 token，且不超过扣除固定指令后可用预算的 1/3 | 压缩时将超出保护额度的历史移入可压缩前缀 |
| 可压缩历史 | 连续前缀，验证并复用已有摘要 | 分批滚动摘要，不反复压缩重叠原始前缀 |
| 请求预留 | 工具 schema、隐藏工具索引、续跑指引、协议和输出预算 | 先预留，发送前再检查完整请求 |

标准 Builder 与 Desktop 未配置模型窗口或输入预算时使用 32,768 token 默认窗口。应填写真实模型窗口；这些是估算值，不是供应商计费数据。直接使用 `DefaultContextAssembler(budget=None)` 的宿主负责总输入预算，固定指令上限仍生效。

## 配置

Agent 与全局区域预算取较小值。下面是 manifest 片段：

```yaml
policies:
  budgets:
    input_tokens: 32768
    system_tokens: 16384
    protected_recent_tokens: 8192
agents:
  main:
    budgets:
      system_tokens: 12000
      protected_recent_tokens: 4096
```

`protected_recent_tokens: 0` 取消当前回合之前的额外历史保护，不允许删除当前用户请求。Context API 对应 `ContextBudget.max_system_tokens` 和 `ContextBudget.protected_recent_tokens`。

Persistent-summary 默认 `max_summary_calls=4`，摘要源预算 `max_summary_source_tokens=24000`，包含滚动摘要空间。工具调用与结果不跨批次拆分。单个单元无可用持久引用且超限，或批次数超限时，在调用摘要模型前拒绝。每次逻辑摘要先请求一次；返回格式不合格时最多再试一次。因此默认最多 8 次摘要生成请求，每次仍受超时约束。

已有摘要可与新增可压缩历史共同缩短。输出没有缩小源内容或不满足最终预算时，不保存派生摘要，不反复扩大源区重试。同一最新用户请求内的长工具轨迹不会自动成为旧历史；大型工具结果应提供持久引用。

## 指令与 Skill 来源

- `AGENT.md` 最多 16,000 字符，超限报错；`MEMORY.md` 最多 4,096 字符，`USER.md` 最多 2,048 字符，超限使用明确标注的节选。SOUL / IDENTITY 也使用小型节选。
- **可用 Skill 列表和描述不做数量或字符截断。** 不再有 128 项、12,000 字符或单描述 500 字符上限；多行 YAML 描述完整解析。
- **加载后的活跃 Skill** 默认总预算为 6,000 token，按 XML 转义后的注入文本计算。单 Skill 超限在物化前拒绝；多个 Skill 超限时淘汰较早的活跃项。原始文件不截断，源 provider 的文件大小限制仍独立生效。
- Server 的 Skill 描述使用长文本字段；旧截断描述可重新导入原文件修复。
- 完整列表仍计入最终固定指令预算；总预算不足时明确报错，而不是悄悄省略 Skill。

## 并发边界与验证

估算器缓存最多 2,048 条摘要与计数，不保存完整提示词。内置可加性估算器通过累计值裁剪；自定义估算器保留完整请求估算语义。同一事件循环共享后台名额：token/指纹计算 2 个、Skill I/O 8 个、模型摘要 4 个。取消不会提前释放仍在运行的线程名额。文件 Skill 描述缓存最多 2,048 项，按文件变化失效。

这些是上下文准备的辅助额度，不替代 Scheduler、租户配额、模型连接池或存储限制。

```bash
python scripts/benchmark_v2_context.py --messages 800 --sessions 8
python -m pytest tests/sagents/v2/test_context_efficiency.py tests/sagents/v2/test_skill_provider_matrix.py
```

基准只测合成历史的裁剪成本，不代表真实模型、数据库吞吐或生产容量。

实现入口：[persistent_reducer.py](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/context/plugins/persistent_reducer.py) · [summarizer_model.py](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/context/plugins/summarizer_model.py) · [provider.py](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/skill/provider.py)。
