---
layout: default
title: 快速开始
nav_order: 1
lang: zh
ref: v2-applications-GETTING_STARTED
parent: 应用入口
---

{% include lang_switcher.html %}

# 快速开始

## 安装

使用 Python 3.12+。macOS/Linux 下运行：

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Windows 使用 `py -3.12 -m venv .venv` 创建环境，在 PowerShell 中执行 `.venv\Scripts\Activate.ps1` 激活。

## 一个 Python 文件即可运行

**不需要创建 `sage.yaml` 文件。** `SageManifestLoader.loads()` 将 YAML 字符串解析为 manifest，再直接传给 `SAgentBuilder.build()`。

保存为 `quickstart.py`，把 `your-model` 替换为账号可用的模型：

```python
"""Set MODEL_API_KEY and replace your-model below; no sage.yaml file is needed."""

from typing import cast

from sagents.v2.composition.loaded_agents import ApplicationEntrypoint

import asyncio
from uuid import uuid4

from sagents.v2 import ActorRef, RequestContext, SAgentBuilder, StartRun
from sagents.v2.contracts.commands import InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import PrincipalType
from sagents.v2.package.manifest import SageManifestLoader

AGENT_YAML = """
schema_version: sage/v2
kind: application
metadata: {id: example.assistant, version: 1.0.0, name: Assistant}
agents:
  main:
    name: Assistant
    instructions: {inline: "Be helpful and concise."}
    models: {primary: primary}
entrypoint: {agent: main}
"""

MODELS_YAML = """
credentials:
  api-key: {source: env, key: MODEL_API_KEY}
models:
  primary:
    provider: openai-responses
    base_url: https://api.openai.com/v1
    credential: api-key
    model: your-model
"""


async def main(*, runtime=None, registrations=()):
    from sagents.v2.composition.defaults import default_runtime
    manifest = SageManifestLoader().loads(AGENT_YAML)
    builder = SAgentBuilder()
    for registration in registrations:
        builder.register(registration)
    app = await builder.build(runtime=runtime or default_runtime("runtime"), models_config_text=MODELS_YAML)
    try:
        agent = await app.load_agent(manifest)
        context = RequestContext(actor=ActorRef(
            principal_id="user-1", principal_type=PrincipalType.USER,
        ))
        stream = await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(StartRun(
            agent_id=agent.id,
            input=(InputItem(role="user", content=(TextBlock(text="Say hello!"),)),),
            resolved_spec_hash=agent.composition_hash,
            idempotency_key=str(uuid4()),
        ), context, agent=agent)
        async for event in stream.events:
            print(event.model_dump_json())
        print((await stream.wait()).state)
    finally:
        await app.close()


if __name__ == "__main__":
    asyncio.run(main())
```

```bash
export MODEL_API_KEY="your-api-key"
python quickstart.py
```

程序输出运行事件和最终 Run 状态，会真实调用模型，并在 `runtime/` 中保存 Session 数据。示例未启用文件或 Shell 工具。PowerShell 使用 `$env:MODEL_API_KEY="your-api-key"` 设置密钥。

也可以从仓库根目录运行[可执行示例](https://github.com/ZHangZHengEric/Sage/blob/main/examples/v2/quickstart.py)：`python -m examples.v2.quickstart`。

## 选择配置输入

| 输入方式 | 用法 |
| --- | --- |
| YAML 字符串 | `await app.load_agent(SageManifestLoader().loads(yaml_text))` |
| Python 字典 | `await app.load_agent(SageManifest.model_validate(config))` |
| 包文件 | `await app.load_agent("path/to/sage.yaml")` |
| 已解析的包 | `await app.load_agent(resolved_manifest)` |

两个 manifest 类型均从 `sagents.v2.package.manifest` 导入。直接传给 `app.load_agent()` 的字符串是**路径**，不会自动识别为 YAML 内容。字符串配置应使用内联指令；文件加载会以包目录为基准解析指令文件，并限制文件位于包目录内。

下一步：[配置](../CONFIGURATION.md)、[工具接入](../MCP_SERVERS.md)、[运行时 API](../api/API_REFERENCE.md)。
