# 单轮执行、循环保护与评分

`single_turn` 只发送一次任务输入；Agent 在这一轮内仍可多次调用工具。
正常完成后按固定 scorer 或模型 rubric 判分。环境返回 `done=true` 也不等于
成功：ALFWorld 的动作上限会终止失败任务，最终分数仍由官方 `won` 决定。

原生运行触发 `loop.repeated_pattern` 或 `loop.no_progress` 时，运行状态是
`suspended`。对于无人值守的单轮评测，这可以是一次执行的终点，而不是要求
模拟用户额外提示后重试的理由。`native_episode.close_single_turn_episode` 只在
以下证据全部成立时，添加 `evidence.episode_termination`：

- 数据集明确为单轮；原生 Run 仍为 suspended，原因是 input_required。
- 对应 interaction 的类型、ID、允许的决策与原生循环保护事件一致。
- trace 未截断，每个工具提议都对应同一 Run/step/operation 的成功收据。
- 工具结果完整且无错误；MCP 确认实际收到结果；没有悬空调用或不确定副作用。

runner 从原生 item.completed 事件保存完整 item envelope，再压缩重复的 trace，
所以暂停任务也有可核验的 `final_items`。证据达到容量上限时明确标记截断，
不把不完整证据转换为可评分的封闭执行。原生 Run、suspension、工具参数、
结果与事件均不改写，也不生成 run.completed。

封闭执行不意味着通过，也不会直接赋零。scorer 依据已执行动作与固定规则独立
判分。ALFWorld native-v3、ScienceWorld native-v2 对照固定的官方环境重放动作，
逐条核验工具结果，计算官方奖励；不接受模型自述的成功或外部轨迹。旧评分器
的已归档版本与分数保持不变，修改后的依赖与引擎具有新的冻结绑定。

相同边界用于训练评测、版本选择与独立 test。选择器可以比较一个有效但失败的
执行，仍按既定分数、回归与采纳门槛决定，不会因为 native state 为 suspended
就忽略其有效评分。普通用户澄清、授权/权限请求、传输错误、未确认工具效果
以及多轮任务不会被此规则关闭，继续沿用原有暂停与恢复协议。

`training_challenge_completed.retained_evaluation` 是补测后的完整保留版本快照；
局部 discovery batch 不应覆盖完整 train/dev 展示。新鲜对照与稳定性补测也只
更新同一 package hash 的展示快照。test 分数不反馈给 tuner 或参与采纳选择。

独立 test 恢复时，已完成的私人证据按 round/package/case/trial 合并；内容冲突
拒绝覆盖。保存使用权限为 0600 的同目录临时文件、fsync 与原子替换，写入失败
保留原文件。
