# v2 脚本

这些脚本服务于 `sagents.v2`、`app.v2`。从仓库根目录使用 Python 3.12+ 运行。
性能脚本使用合成输入或临时存储，输出只能说明对应测量范围，不能直接当作生产性能。

| 入口 | 用途与运行条件 |
| --- | --- |
| [benchmark_admission.py](benchmark_admission.py) | 对比 Server 模型目录的整体加载与单 Agent 加载；临时 SQLite 数据库，需要 Server Python 依赖 |
| [benchmark_context.py](benchmark_context.py) | 上下文组装、压缩和并发 Session 的离线测量 |
| [benchmark_single_host.py](benchmark_single_host.py) | 对比全局与逐 Run 调度围栏，使用模拟写入延迟，无模型或外部数据库 |
| [benchmark_session_commit.py](benchmark_session_commit.py) | Session 增量序列化的合成基准，无 Redis、MySQL 或模型调用 |
| [benchmark_session_projection.py](benchmark_session_projection.py) | Session 事件与投影的离线基准 |
| [probe_openui_self_check_live.py](probe_openui_self_check_live.py) | 显式注入数值错误，验证 OpenUI 自检修复；读取本机 Desktop 模型目录，调用真实模型并写入 `--output` |
| [render_openui_test_video.py](render_openui_test_video.py) | 将已有 `frames.json` 和录制帧转换为视频，需要 FFmpeg，会写输出文件 |
| [release/](release/) | 版本与产物检查、嵌入 Python 运行时、安装包构建及打包后验证 |

离线小规模运行：

```bash
python -m scripts.v2.benchmark_admission --agents 5 --samples 1
python -m scripts.v2.benchmark_context --messages 20 --sessions 2
python -m scripts.v2.benchmark_single_host --sessions 2 --writes 2 --io-ms 1
python -m scripts.v2.benchmark_session_commit --commits 2 --input-bytes 100
python -m scripts.v2.benchmark_session_projection --events 10 --repeats 1
```

OpenUI 真实模型探针依赖当前仓库的测试辅助代码和 Desktop 模型配置，可能产生模型费用；
先查看 `python scripts/v2/probe_openui_self_check_live.py --help`。
视频转换命令为 `python scripts/v2/render_openui_test_video.py ARTIFACT_DIRECTORY --speed 4`。

## 发布脚本

| 入口 | 用途 |
| --- | --- |
| [release/check_release.py](release/check_release.py) | 不传参数时只读核对版本和资源边界；`--assets` 核对分发包，`--complete` 同时核对全部安装产物 |
| [release/package_desktop.py](release/package_desktop.py) | 根据已构建的 Flutter 产物和 wheel 构建平台安装包，并调用下方嵌入及冒烟脚本 |
| [release/bundle_desktop.py](release/bundle_desktop.py) | 将托管 CPython、wheel、Node 运行时等写入构建目录，安装依赖；需 uv 及发布环境 |
| [release/smoke_desktop.py](release/smoke_desktop.py) | 在仓库外启动嵌入后端，检查打包资源和运行时行为；需已生成的嵌入运行时 |

```bash
python scripts/v2/release/check_release.py
python scripts/v2/release/package_desktop.py --help
python scripts/v2/release/bundle_desktop.py --help
python scripts/v2/release/smoke_desktop.py --help
```

活动发布入口仍为 [.github/workflows/release-v2.yml](../../.github/workflows/release-v2.yml)。
脚本目录整理不执行打包、上传或发布。
