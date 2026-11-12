# Sage Voice

Sage v2 的独立 Flutter 语音对话应用。首版面向 Apple Silicon Mac（macOS 15+），从 Sage 源码运行。

## 运行

需要附带 Dart 3.12.2 或更新版本的 Flutter SDK、Xcode 和 arm64 Python 3.12。从 Sage 仓库根目录执行：

```sh
python3.12 -m venv .venv-voice
.venv-voice/bin/python -m pip install -e . -r app/v2/voice/requirements.txt
cd app/v2/voice
flutter pub get
flutter run -d macos
```

如果使用已有的专用 Python 环境，可在运行 Flutter 前将 `SAGE_VOICE_PYTHON` 指向该环境的 Python 可执行文件。使用 `flutter build macos` 可构建 macOS 应用，当前构建依赖 Sage 源码和该 Python 环境。语音管线、VoiceProcessingIO 动态库和本地回合检测模型随 Sage 源码提供。

打开「设置」，填写 OpenAI 兼容模型的 API Base URL、模型 ID、API Key，以及百炼或火山引擎的语音 API Key。语音配置同时用于识别和合成。点击麦克风并允许访问，开始连续对话。说话可打断播报。点击停止可以关麦，再次打开麦克风时继续同一对话。从右下角进入工作台可查看对话、发送文字、手动打断并检查本轮语音耗时。设置页按语音识别、智能体和语音合成三个环节组织。

设置保存在 `~/Library/Application Support/Sage Voice/settings.json`，文件权限为 `0600`。当前对话上下文与界面记录仅在应用运行期间保留。配置的语音服务收到麦克风音频和待合成文本，模型服务收到识别后的对话文本。

## 接入方式

- Flutter 负责语音界面、实时字幕、转写记录和 macOS 麦克风授权。它通过子进程管道控制 Python 语音引擎。
- 音频链路使用仓库内随附的 Lalk 派生代码和资源。安装只需要公开 Python 依赖。VoiceProcessingIO 提供全双工输入输出和回声消除，Silero VAD、Adaptive Input Level Gate 和 Smart Turn V3 负责检测回合，本地管线协调流式 ASR、TTS 和打断。来源与授权见 [语音管线说明](backend/voice_pipeline/NOTICE.md)。
- Agent 使用标准 `SAgentBuilder.build`、`app.load_agent` 和 `app.entrypoint().run_stream`。适配层将正文增量送给本地语音管线，在打断或关闭时取消仍在运行的 Run。每个语音回合使用同一 SAgents Session。
- 使用临时 SessionStore 和确定性续跑策略，上下文使用窗口裁剪。长期记忆、会话记忆与技能默认关闭。支持工具调用的模型可在「智能体」设置中启用只读的本机时间查询。
- 正文会边生成边送去合成。已知工具执行超过 1.2 秒且正文未到时，可以播一句具体进度。整轮等待 4 秒仍无正文时，可以播一句通用提示。每轮最多播一句。监控区会标明首声是否包含进度提示，并单独显示 Agent 首段正文的耗时。

在「设置 → 智能体 → 工具进度播报」选择工具，可修改中英文播报、关闭该工具的专属提示或恢复默认。工具名称沿用 Sage Desktop 的映射。文件工具和网页工具可用 `{target}` 读出文件名或域名。缺少适用的参数时使用默认短句。
