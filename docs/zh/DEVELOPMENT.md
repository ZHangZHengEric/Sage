---
layout: default
title: 开发
nav_order: 10
description: "贡献流程与源码位置"
lang: zh
ref: development
---

{% include lang_switcher.html %}

# 开发

## 仓库主要区域

- `sagents/`：运行时与编排
- `app/server/`：主后端与 Web 应用
- `app/desktop/`：桌面后端、UI 和构建脚本
- `examples/`：可运行示例与演示
- `mcp_servers/`：内置 MCP Server 实现
- `app/skills/`：内置 Skill 内容与辅助资源

## 本地开发流程

### 后端

```bash
pip install -r requirements.txt
python -m app.server.main
```

当你要开发主后端，而不是轻量示例时，走这条路径。

### Web 前端

```bash
cd app/server/web
npm install
npm run dev
```

常见前端环境变量：

- `VITE_SAGE_API_BASE_URL`
- `VITE_SAGE_WEB_BASE_PATH`

### 桌面端

当你修改桌面功能时，除了桌面 UI 外，也要同时关注 `app/desktop/core/` 下的本地后端逻辑。

### 文档站

文档站依赖 GitHub Pages 的 Jekyll 依赖链，建议使用 `docs/.ruby-version` 固定的 Ruby 版本来构建。

使用 RVM：

```bash
source ~/.rvm/scripts/rvm
rvm use 3.2.9
cd docs
bundle config set path vendor/bundle
bundle install
bundle exec jekyll serve
```

如果只想做一次构建验证：

```bash
source ~/.rvm/scripts/rvm
rvm use 3.2.9 do bash -lc 'cd docs && bundle exec jekyll build'
```

## 开发建议

- 优先确认你修改的是哪一层：运行时、服务端、前端还是桌面。
- 先从最小可运行入口验证，再逐步进入完整应用链路。
