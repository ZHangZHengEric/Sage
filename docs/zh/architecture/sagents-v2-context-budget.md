---
layout: default
title: 上下文预算
parent: 架构
nav_order: 6
lang: zh
ref: v2-detail-sagents-v2-context-budget
---

{% include lang_switcher.html %}

# v2 上下文压缩

不再进行本地输入 token 估算、校准或估算预算拦截。模型配置的最大输入长度仍有效：API 返回的实际 input usage 达到配置上限减去显式输出/输入预留后，下一次请求前触发压缩。缓存输入属于 input usage 的子集，不会重复计数。

API 直接返回超长时，立即压缩并重试；主请求每个未完成步骤最多恢复 6 次。首次请求或刚新增内容的精确 token 长度只能由 API 反馈得知。输出 token 配置仍通过 API 请求限制。

摘要请求先发送完整来源，包含已有摘要。仅当 API 返回超长，才将来源二分；两个分片都完成后再合并摘要。模型请求、格式修复、临时错误重试共享每次操作最多 64 次调用的上限，递归深度最多 12 层。摘要为空、没有缩短来源、调用数耗尽、永久错误或取消时，保留旧检查点和全部原始历史。

主请求、工具选择、记忆检索词生成、完成判断均有 API 超长恢复。临时服务错误按 1、2、4 秒退避重试，摘要超时有独立的有限重试。中断输出不会进入已完成历史。

压缩只修改推理视图；原始消息、工具结果、媒体引用和事件一直保留。最新真实用户请求保持原文；并行工具调用及其结果作为完整单元处理。长单轮的已完成工具批次也可整体摘要。只有工具提供了真实持久引用，才能替换为引用。工具执行结果不会因模型重试而重跑。

usage 或 API 超长触发摘要时，摘要范围会推进到最近 `protected_recent_units` 个完整对话单元之前（默认 4 个），不再仅选择最新用户请求之前的部分历史。已完成的当前轮工具批次及其附带图像可进入摘要，最新用户请求另以原文保留。保留窗口按完整批次划分，不拆并行调用、结果和图像；短历史仍沿用已有的最小恢复范围。此策略扩大单次摘要的覆盖范围，不估算或承诺固定压缩后 token 数；实际占用仍以后续 API usage 为准。

整个选定前缀完成后才通过摘要仓库的 revision CAS 提交检查点。失败或取消不能提交半个并行批次。重新读取时验证来源摘要哈希，禁止把旧摘要应用于已改写的历史。

如果固定指令或单条当前用户输入本身不可压缩，恢复有界停止并保留原始历史。仅由 usage 触发的提前压缩，若已经没有内容可压，不会中断仍可发送的请求。

估算插件和相关配置入口已移除。旧摘要中的 `estimated_tokens` 仅为存储兼容保留，运行中不生成或使用估算值。旧 `max_source_tokens` / `max_summary_source_tokens` 参数接受但不再限制输入；摘要输出预算仍有效。

测试：`python -m pytest tests/sagents/v2/test_api_context_recovery.py tests/sagents/v2/test_persistent_summary_context_matrix.py tests/sagents/v2/test_agent_loop_matrix.py`。真实模型验收位于 `tests/sagents/v2/live/test_gpt_5_6_luna_scenarios.py`，包括真实 usage 阈值与注入超长后的真实摘要、工具流程。

真实 API 验收位于 `tests/sagents/v2/live/test_real_api_context_recovery.py`：包括真实 HTTP 422 超长、实际 usage 阈值、并行工具、视觉输入、取消、输出截断和持久化重启。分片采用结构化合并，保留每个成功分片的全部事实；完整 API 输出不再本地截断。完成判断的固定规则与 JSON 契约保留为 system 消息。HTTP 401/429/503 和断流通过单独标明的本地 HTTP 故障网关测试，成功响应来自真实模型；不会把网关故障冒称为上游自然故障。
