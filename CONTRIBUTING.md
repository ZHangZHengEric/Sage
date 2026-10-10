# Contributing to Sage

[English](#english) · [中文](#中文)

## English

Thanks for helping build Sage! First-time contributors are welcome. A clearer sentence, a translation, a runnable example, a regression test, a bug fix, or a model/tool integration can all make a useful PR. We are happy to work with you toward merging focused contributions that fit the project and pass the relevant checks.

### Pick a starting point

- Read the [English README](README.md) and the guide for your component: [runtime](sagents/v2/README.md), [Desktop v2](app/v2/desktop/README.md), or [Server v2](app/v2/server/README.md).
- Browse [open issues](https://github.com/ZHangZHengEric/Sage/issues) and [pull requests](https://github.com/ZHangZHengEric/Sage/pulls) to avoid duplicate work. Ask in an issue if the expected behavior or scope is unclear.
- Small documentation fixes can go straight to a PR. Discuss larger features, new integrations, or architecture changes in an issue first.
- For a bug, include the component/version, operating system, reproduction steps, and expected versus actual behavior. Remove credentials and private data from logs and screenshots.

### Make and check your change

1. Fork the repository, clone your fork, and create a focused branch from `main`.
2. Follow the [README source setup](README.md) for the component you are changing. Python code requires Python 3.12+. Match nearby code and keep unrelated changes out of the PR.
3. Add or update tests for behavior changes and update affected documentation. Keep English and Chinese documentation aligned when both versions exist.
4. Run the relevant checks below from the repository root, unless a different directory is shown. Report the commands and results in your PR, including checks you could not run.

**Documentation** (install PyYAML in your Python environment first):

```bash
python -m pip install pyyaml
python docs/scripts/check_docs.py
```

Also preview changed Markdown and verify links. This script checks the current documentation sources and README links; it is not a universal Markdown linter. The [documentation workflow](.github/workflows/docs.yml) also builds the site.

**Python** (in your Python 3.12+ environment):

```bash
python -m pip install -r requirements.txt
python scripts/checks/check_architecture.py
python -m pytest tests/sagents/v2 -v
```

The last command targets the v2 runtime; select the affected tests under [`tests/`](tests/) for other components. Linux sandbox tests need a compatible bubblewrap installation and host support. See the [CI workflow](.github/workflows/ci-tests.yml) for the full suite matrix and environment setup, including the app suite's A2A dependency. Live model tests may incur costs; do not enable them without your own credentials and intent.

**Desktop v2** (Flutter 3.44.2 is used in CI):

```bash
cd app/v2/desktop
flutter pub get
flutter analyze
flutter test
```

For backend changes, also run the affected Python tests under `tests/app/v2/desktop`.

**Server v2 web** (Node.js 22.12+):

```bash
cd app/v2/server/web
npm ci
npm run build
```

### Open your PR

- Target `main`. Explain what changed and why, and link an issue if there is one.
- Include reproduction steps for fixes, screenshots for UI changes, and test results.
- Keep the PR small enough to review. A draft PR is welcome if you want feedback before it is finished.
- Respond to review feedback and check CI. Review considers correctness, maintainability, and fit with Sage; relevant checks and review need to pass before merge.

Questions are welcome in [GitHub Issues](https://github.com/ZHangZHengEric/Sage/issues). You do not need to understand the entire codebase to contribute.

## 中文

感谢你一起建设 Sage！欢迎第一次参与开源的朋友。改进一句文档、补充翻译、提供可运行的示例、增加回归测试、修复 Bug，或接入模型与工具，都可以成为有价值的 PR。我们很乐意与你一起完善贡献，让符合项目方向、通过相关检查的小改动顺利合并。

### 从哪里开始

- 先阅读[中文 README](README_CN.md)，以及所选组件的指南：[运行时](sagents/v2/README.md)、[Desktop v2](app/v2/desktop/README.md)、[Server v2](app/v2/server/README.md)。
- 查看[现有 Issue](https://github.com/ZHangZHengEric/Sage/issues) 和 [PR](https://github.com/ZHangZHengEric/Sage/pulls)，避免重复工作。不确定预期行为或范围时，可以先在 Issue 中提问。
- 小的文档修正可以直接提交 PR；较大的功能、新集成或架构改动，请先开 Issue 讨论。
- 报告 Bug 时，请注明组件与版本、操作系统、复现步骤、预期和实际结果。日志和截图中不要包含凭据或私人数据。

### 开发与检查

1. Fork 仓库并克隆自己的 fork，从 `main` 创建专注于单个改动的分支。
2. 按 [README 源码配置](README_CN.md)准备对应组件。Python 代码需要 Python 3.12+；遵循周边代码风格，避免混入无关改动。
3. 行为变化应补充或更新测试，并同步相关文档。已有中英文版本的内容，请尽量保持一致。
4. 按上方 English 部分的命令运行受影响组件的检查，并在 PR 中写明命令、结果以及未能运行的检查：
   - 文档：安装 PyYAML 后，从根目录运行 `python docs/scripts/check_docs.py`，预览 Markdown 并检查链接。该脚本检查当前文档源文件和 README 链接，并非通用 Markdown 检查器；文档 CI 还会构建网站。
   - Python：在 Python 3.12+ 环境安装 `requirements.txt`，运行架构检查，并选择 `tests/` 下对应组件的测试。上方示例针对 v2 运行时。
   - Desktop v2：在 `app/v2/desktop` 运行 `flutter pub get`、`flutter analyze`、`flutter test`；后端改动还应运行 `tests/app/v2/desktop` 下相关 Python 测试。CI 使用 Flutter 3.44.2。
   - Server v2 Web：使用 Node.js 22.12+，在 `app/v2/server/web` 运行 `npm ci` 和 `npm run build`。
5. Linux 沙箱测试需要兼容的 bubblewrap 和宿主支持；完整测试矩阵、环境配置及 app 测试的 A2A 依赖见 [CI 工作流](.github/workflows/ci-tests.yml)。真实模型测试可能收费，请仅在明确需要且使用自己的凭据时启用。

### 提交 PR

- 目标分支选择 `main`，说明改了什么、为什么改；如有相关 Issue，请附上链接。
- Bug 修复附复现步骤，界面改动附截图，并记录测试结果。
- 尽量保持 PR 小而清晰；希望提前获得反馈时，欢迎提交草稿 PR。
- 根据评审反馈完善改动并检查 CI。合并会考虑正确性、可维护性和项目方向，并确认相关检查与评审通过。

欢迎在 [GitHub Issues](https://github.com/ZHangZHengEric/Sage/issues) 提问。无需先理解整个代码库，也可以开始贡献。
