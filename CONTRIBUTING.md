# Contributing to Sage

Thanks for helping build Sage! First-time contributors are welcome. A clearer sentence, a translation, a runnable example, a regression test, a bug fix, or a model/tool integration can all make a useful PR. We are happy to work with you toward merging focused contributions that fit the project and pass the relevant checks.

## Pick a starting point

Please use English for issues, pull requests, and general repository documentation. Keep translations in their dedicated language files.

- Read the [English README](README.md) and the guide for your component: [runtime](sagents/v2/README.md), [Desktop v2](app/v2/desktop/README.md), or [Server v2](app/v2/server/README.md).
- Browse [open issues](https://github.com/ZHangZHengEric/Sage/issues) and [pull requests](https://github.com/ZHangZHengEric/Sage/pulls) to avoid duplicate work. Ask in an issue if the expected behavior or scope is unclear.
- Small documentation fixes can go straight to a PR. Discuss larger features, new integrations, or architecture changes in an issue first.
- For a bug, include the component/version, operating system, reproduction steps, and expected versus actual behavior. Remove credentials and private data from logs and screenshots.

## Make and check your change

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

## Open your PR

- Target `main`. Explain what changed and why, and link an issue if there is one.
- Include reproduction steps for fixes, screenshots for UI changes, and test results.
- Keep the PR small enough to review. A draft PR is welcome if you want feedback before it is finished.
- Respond to review feedback and check CI. Review considers correctness, maintainability, and fit with Sage; relevant checks and review need to pass before merge.

Questions are welcome in [GitHub Issues](https://github.com/ZHangZHengEric/Sage/issues). You do not need to understand the entire codebase to contribute.
