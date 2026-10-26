# Team 运行时 Skill

宿主可以通过 `RunConfig.skill_attachments` 给一次 Team Run 附加 Package 未声明的
Skill。它沿实际的 `parent_run_id` 委派树共享可用性，包括之后创建的成员 Run。
Package、成员配置和原有静态 Skill 白名单不需要修改。

## 标准公开调用

以下代码接续宿主已有的 `runtime`、`models`、`team_package`、`subagents` 和
`context`。`runtime` 应已配置 `skill.provider` 和正常的 Skill workspace / execution
binding；加载操作仍使用现有 workspace 策略。

```python
from sagents.v2 import SAgentBuilder, StartRun
from sagents.v2.contracts.commands import InputItem, RunConfig
from sagents.v2.contracts.items import TextBlock
from sagents.v2.skill import (
    FilesystemSkillProvider,
    RuntimeSkillAttachment,
    RuntimeSkillAuthorization,
)

# 宿主读取明确来源，冻结内容身份。不会发布到全局 Skill 仓库。
source = FilesystemSkillProvider(
    roots=("/host/extra-skills",), source_id="host-session-skills",
)
bundle = await source.fetch("research-guide", run_id="host-preparation")

# 独立的宿主授权上限：精确匹配 descriptor（含 source_id/name/version）和内容 hash。
# 这个授权本身不使 Skill 出现在任何会话中。
runtime = runtime.model_copy(update={
    "runtime_skill_authorizations": (
        RuntimeSkillAuthorization.from_bundle(bundle, max_bytes=1024 * 1024),
    ),
})
app = await SAgentBuilder().build(runtime=runtime, models=models)
try:
    team = await app.load_agent(team_package, subagents=subagents)
    stream = await app.entrypoint().run_stream(
        StartRun(
            agent_id=team.id,
            resolved_spec_hash=team.composition_hash,
            idempotency_key="team-request-1",
            input=(InputItem(role="user", content=(TextBlock(text="执行调研"),)),),
            config=RunConfig(skill_attachments=(
                RuntimeSkillAttachment.from_bundle(bundle),
            )),
        ),
        context,
        agent=team,
    )
    async for event in stream.events:
        handle_event(event)
    result = await stream.wait()
finally:
    await app.close()
```

每次新 Run 都显式提交 attachment。同一 Session 的新一轮也可在 `StartRun.session_id`
中指定已有 Session，并再次提交需要的 attachment。宿主不需要逐个配置被委派的成员。

## 范围和加载

- `target_agent_id=None`：以接受该 attachment 的当前 Agent 为根，在它及其下级生效。
- `target_agent_id="director"`：只在该 Run 树的 `director` 子 Team 及其后代生效。
  嵌套节点使用冻结团队图中的完整成员 ID，例如 `director.editor`；这些 ID 对应
  `load_agent(..., subagents={...})` 的成员路径。顶层范围推荐省略 target。
- 范围由持久化父 Run 链判断，不依赖字符串前缀，也不修改父级或兄弟的目录。
  将 attachment 附加到一个子 Team 的 Run，只会沿该 Run 向下传播。
- 默认只将 metadata 放进 `available_skills`；正文和附件在 `load_skill` 时读取、
  按现有预算激活。`preload=True` 显式要求每个范围内的成员预加载，仍受激活预算限制。
- 新会话没有 attachment 时不可发现或加载该 Skill。已授权的其他现有 Skill 不受影响。

## 授权和冲突

`RuntimeConfig.runtime_skill_authorizations` 是宿主侧独立白名单，默认空列表即拒绝。
`RuntimeSkillAuthorization.from_bundle(...)` 固定来源 descriptor 和文件内容 hash；
`target_agent_ids=("director",)` 可进一步限制 attachment 根节点，`max_bytes` 限制
单个 bundle 的总字节数。该上限在 `build()` 给初值，之后用
`await app.update_runtime_skill_authorizations(grants)` 整体替换（追加和撤销都走它），
不需要重建 App；不能通过 `load_agent(runtime=...)` 修改，也不参与 Agent revision 的
composition hash，因此更新后已加载的 Agent 继续可用。新上限对之后的提交、子 Run 委派
以及每次执行或恢复（包括已提交的暂停 Run）立即生效；正在执行的循环已加载的 Skill
不会被中途收回。历史 Agent revision 中保存的旧授权不会恢复旧权限。

原有 `enabled_skills` 和 Package Skill 白名单继续控制 Package 内的 Skill。
额外 Skill 通过专用 attachment 授权，两者独立；仅把名字写入 `enabled_skills`
不能获得额外 Skill。仅有宿主授权而未提交 attachment，也不会产生可用性。

attachment 只增加 Skill 目录和标准 `load_skill` 入口，不授予 Shell、网络、文件、
编辑 Skill 或额外委派能力。正常工具加载仍需要调用者既有的 `skill.load` scope，
例如由宿主身份认证层设置的 `RequestContext.actor.scopes`；不会自动补 scope。
`preload=True` 是宿主主动请求的预加载，与现有 Package preload 使用同一机制。
沙箱不允许 materialize 时加载仍会失败。

同名冲突一律拒绝，不静默覆盖：包括多个不同 attachment 使用同名、不同范围或来源
替换继承项，以及与现有 provider 中的同名 Skill 冲突。继承中再次转发完全相同的
attachment 是幂等的。现有 provider 冲突在目录访问/加载前检查；发生冲突时不会
调用模型或物化临时文件。宿主应选择唯一名称。

## 有效期与恢复

当前支持且默认的 `lifetime="run_tree"` 明确表示一次 Run 树，不是 Session 永久配置。

| 操作 | 行为 |
| --- | --- |
| 同一 Run 暂停、审批后 `continue_run` | 保留来源、范围和 preload 状态 |
| 之后委派的新成员 / 新成员续轮 | 继承当前父 Run 的 attachment；按自身祖先范围判断 |
| 同一 Session 新建顶层 Run | 不自动继承；宿主按需再次提交 |
| 取消或完成 | 不向未来顶层 Run 续期；持久化命令保留为审计记录 |
| 进程重启，恢复原 Run | 从持久化 StartRun 恢复，不依赖宿主再次注册 bundle 对象或源文件仍存在 |
| 恢复时宿主删除或收紧授权（重启后或运行中 `update_runtime_skill_authorizations`） | 重新检查当前 App 上限，拒绝继续执行该授权；不会重新启用历史上限 |

`files_base64` 保存经过安全路径校验的文件快照，支持二进制附件，并校验
`content_hash`。源文件之后变化不会替换原 Run 的内容。使用远程 SessionStore 时，
该字段与其他 StartRun 数据一起持久化；自定义存储必须完整保留标准命令字段。

范围隔离指 Skill 发现和激活授权。已发生的对话、工具结果和持久化审计不会被删除；
已物化文件的保留、共享和清理仍由宿主选定的 workspace 策略管理。若多个会话原本
就共享可读取的宿主目录，Skill attachment 不会改变这种已有文件访问权限。

验收测试见 `tests/sagents/v2/test_runtime_team_skills.py`，通过标准 build/load/run 路径
覆盖两层子 Team、按需加载、子树与会话隔离、完整执行策略不变、显式预加载、调用者
scope、内容校验、冲突、取消以及冷启动后的保留和授权收紧。
