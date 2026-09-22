---
layout: default
title: 开发
nav_order: 10
lang: zh
ref: v2-DEVELOPMENT
---

{% include lang_switcher.html %}

# 开发

## 源码地图

| 目录 | 职责 |
| --- | --- |
| `sagents/v2/` | 运行时契约、装配、provider 与执行 |
| `app/desktop_v2/` | Flutter 界面与本机 FastAPI sidecar |
| `app/server_v2/` | 多用户服务端与 Vue Web 客户端 |
| `tests/sagents/v2/` | 运行时测试和契约检查 |
| `tests/app/desktop_v2/`、`tests/app/server_v2/` | 宿主集成测试 |
| `docs/en/`、`docs/zh/` | 当前中英文 v2 文档 |

## 验证修改

使用[快速开始](applications/GETTING_STARTED.md)中的 Python 3.12+ 环境，服务端测试需要安装对应 extras：

```bash
python -m pip install -e '.[server-v2]' pytest pytest-asyncio pytest-timeout
python -m pytest tests/sagents/v2 tests/app/desktop_v2 tests/app/server_v2 -q
```

开发时先运行相关测试。真实模型测试需显式配置，可能产生调用费用。注入测试存储的数据库测试不证明生产 MySQL 行为。

```bash
cd app/desktop_v2
flutter analyze
flutter test
```

```bash
cd app/server_v2/web
npm install
npm run build
```

## 文档检查

```bash
.venv/bin/python docs/scripts/check_docs.py
bash docs/scripts/build_jekyll.sh
python3 docs/scripts/check_language_nav.py
```

Jekyll 构建需要 Ruby 和 `docs/Gemfile` 中的依赖。正式页面应有正确的语言元数据、有效本地链接和 v2 源码依据。历史文件放入不参与发布的 `docs/archive/`。不能用旧审查的通过数作为当前可用性保证。
