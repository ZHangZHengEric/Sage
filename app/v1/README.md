# Sage v1（旧版）

仓库默认的 Sage、Desktop、Server、SAgents 和 `sage` 命令使用当前 v2 实现。
本目录保留 v1 应用；v1 运行时位于 `sagents/v1/`，按需单独安装和启动。

## 安装

在仓库根目录、独立的 Python 3.12+ 环境中执行：

```bash
python -m pip install -r app/v1/requirements.txt -e .
```

根目录 `pyproject.toml` 的 `server`、`desktop` extras 属于当前版本。
v1 应用的依赖单独由本目录的 `requirements.txt` 维护。

## 入口

| 用途 | 入口 |
| --- | --- |
| CLI | `sage v1 run "任务"`、`sage v1 chat`、`sage v1 sessions` |
| Terminal | `sage tui --runtime v1` |
| Server | `python -m app.v1.server.main` |
| Desktop | `bash app/v1/desktop/scripts/dev.sh` |
| Python API | `from sagents.v1 import SAgent` |

## 文档与资源

- [旧版部署](deploy/README.md)
- [旧版开发和维护脚本](../../scripts/v1/README.md)
- [旧版示例](../../examples/v1/README.md)
- [历史文档](../../docs/archive/README.md)
- [源码归属与导入迁移](../../docs/VERSIONED_LAYOUT.md)

当前应用与 v1 分别管理配置、会话及工作区；本次入口命名调整不迁移旧版数据。
