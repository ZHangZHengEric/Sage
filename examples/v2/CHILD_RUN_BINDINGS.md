# 子任务模型绑定（公开 v2 API）

通过 `SAgentBuilder` 构建的 team 和 fibre 应用会在创建子 run 前解析并持久化
`RunConfig.model_bindings`。宿主不需要修改 Application 私有字段或实现子任务执行器。

## 默认继承与显式覆盖

父 run 使用公开 resolver 选择模型：

```python
from sagents.v2.package.manifest.resolver import CompositionResolver

resolver = CompositionResolver()
resolved = resolver.resolve(manifest)
config = resolver.resolve_run_config(
    resolved, "main", model_bindings={"primary": "model-b-v2"}
)
# 将 config 传入父 StartRun(config=config, ...)。
```

子任务绑定的优先级为：

1. 子 agent 的 `delegation_model_bindings` 显式覆盖。
2. 父 run 已解析的 `config.model_bindings`。
3. 子 agent 的 `models` 默认值。

`primary` 默认继承；辅助槽位仅在子 agent 也声明该槽位时继承。
父 run 未指定的槽位使用子 agent 默认值。普通 `models.primary` 是默认值，
不会覆盖父 run 的选择。如需固定委派任务的模型，在 manifest 中声明：

```yaml
agents:
  worker:
    name: Worker
    instructions:
      inline: Complete the delegated task.
    models:
      primary: model-a
      alternative: model-b-v2
    delegation_model_bindings:
      primary: model-a
```

最终绑定必须满足子 agent 的策略上限（其 `models` 声明的模型路由）。
覆盖字段不能扩大上限，且只能覆盖已声明的槽位。父 run 选择了子 agent
不允许的模型且没有合法的显式覆盖时，委派报 `manifest.model_override_denied`，
不会创建子 run 或静默回退模型。动态创建的 fibre agent 使用构建时所选 agent
的模型策略和委派覆盖设置。

宿主也可直接调用公开的
`resolver.resolve_child_run_config(resolved, "worker", parent_config=config)`
预览同一解析规则；Builder 已自动接入此方法。

## 配置与恢复边界

Builder 对外部传入的已解析 manifest 建立独立快照。最终子任务绑定在创建
子 run 时写入 SessionStore，实际 `ModelRequest.model_binding` 使用该选择。
审批暂停、恢复以及使用相同配置关闭重建 Application 后，继续读取持久化绑定，
不会重新应用新的默认值或委派覆盖。修改源 manifest 不会重配已构建的应用。
跨进程恢复仍遵守原有 composition hash 兼容性校验；此功能不会放宽该检查。
已有的空绑定历史记录不会被自动猜测或改写。

自行组装底层 `ModeAwareAgentLoopFactory` 的宿主可传入
`child_run_config_resolver`（底层 `LoopChildRunExecutor` 参数名为
`run_config_resolver`）。未提供该回调时，底层执行器仅复制父绑定；没有 manifest
的底层执行器无法替宿主定义模型策略上限。优先使用 Builder 的完整公开构建路径。

## 无网络回归测试

```bash
.venv/bin/pytest -q tests/sagents/v2/test_public_child_model_bindings.py
```

测试通过公开 Builder、manifest、Run 和 SessionStore API，核对持久化配置及
实际模型请求，覆盖并发父任务、team/fibre、动态 fibre 子 agent、覆盖优先级、
越权拒绝、配置快照、审批恢复和关闭重开恢复。使用脚本模型，无需真实模型密钥。
