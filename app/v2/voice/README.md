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

打开「设置」，填写 OpenAI 兼容模型的 API Base URL、模型 ID、API Key，以及百炼或火山引擎的语音 API Key。语音配置同时用于识别和合成。点击麦克风并允许访问，开始连续对话。说话可打断播报。点击停止可以关麦，再次打开麦克风时继续同一对话。从右下角进入工作台可查看对话、发送文字、手动打断并检查本轮语音耗时。设置页包含语音识别、智能体和语音合成三个分类。智能体页可选填 System Prompt、思考强度、温度和最大输出 Token 数。提示词留空时使用 Sage Voice 的内置提示词，模型参数的取值由所用端点支持情况决定。界面语言可跟随系统，也可切换为简体中文或 English。

设置保存在 `~/Library/Application Support/Sage Voice/settings.json`，文件权限为 `0600`。当前对话上下文与界面记录仅在应用运行期间保留。配置的语音服务收到麦克风音频和待合成文本，模型服务收到识别后的对话文本。

## 接入方式

- Flutter 负责语音界面、实时字幕、转写记录和 macOS 麦克风授权。它通过子进程管道控制 Python 语音引擎。
- 音频链路使用仓库内随附的 Lalk 派生代码和资源。安装只需要公开 Python 依赖。VoiceProcessingIO 提供全双工输入输出和回声消除，Silero VAD、Adaptive Input Level Gate 和 Smart Turn V3 负责检测回合，本地管线协调流式 ASR、TTS 和打断。来源与授权见 [语音管线说明](backend/voice_pipeline/NOTICE.md)。
- Agent 使用标准 `SAgentBuilder.build`、`app.load_agent` 和 `app.entrypoint().run_stream`。适配层将正文增量送给本地语音管线，在打断或关闭时取消仍在运行的 Run。每个语音回合使用同一 SAgents Session。
- 使用临时 SessionStore 和确定性续跑策略，上下文使用窗口裁剪。长期记忆、会话记忆与技能默认关闭。支持工具调用的模型可在「智能体」设置中逐项启用 Sage 内置工具。文件与命令工具使用 Voice 启动期间的临时工作区。网页工具通过 Sage 沙箱访问公开 HTTP(S) 地址。启用图片分析需使用支持图片输入的模型。同时启用目标提交和目标完成后，可以用 `/goal 任务内容` 发起目标模式。

## 工具进度播报

正文会边生成边送去合成。已知工具执行超过 1.2 秒且正文未到时，可以播一句具体进度。整轮等待 4 秒仍无正文时，可以播一句通用提示。每轮最多播一句。监控区会标明首声是否包含进度提示，并单独显示 Agent 首段正文的耗时。

在「设置 → 智能体 → 工具」中可逐项启用工具。展开工具可查看介绍和参数，并编辑中英文进度播报。文件读写和更新的播报可使用 `{target}` 代入文件名。单独修改播报规则会保留当前对话，新规则在下次开启麦克风时生效。
