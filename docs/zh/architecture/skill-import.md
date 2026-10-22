---
layout: default
title: 技能远程导入
nav_order: 17
lang: zh
ref: v2-detail-skill-import
parent: 架构
---

{% include lang_switcher.html %}

# 技能远程导入

## 支持的来源

Server 技能页面支持本地 ZIP、在线 ZIP 和 Skills CLI 导入。在线 ZIP 接受公开 HTTPS 地址的 443 端口。Skills CLI 接受公开 GitHub 来源，解析到固定 commit 后下载仓库 ZIP，校验选中的技能，再通过固定版本的 CLI 做项目级复制和目录发布。

服务端需要 Node.js 22.20+、npx，以及 GitHub 和 npm registry 网络访问。远程下载在重定向时重新校验 DNS，拒绝本机、私网及保留地址。

## 预览与发布

先调用 `POST /api/skill-import-previews` 发现候选，查看技能路径、摘要与冲突；选择后调用 `POST /api/skill-imports` 发布。同名更新需要明确选择，并核对预期版本与内容摘要。相同内容复用已有版本，逐项返回成功、未变更、冲突或失败。

导入复用既有 Skill 版本和制品目录。发布不代表自动绑定到所有智能体，也不安装插件、注册 MCP 或扩大工具授权。运行时仍由宿主授权和绑定。

## 范围限制

当前入口不提供技能市场、私有仓库、独立 Git 地址输入、来源自动更新或团队 HTTP 目录。下载及发布需要实际网络可用；不要从预览成功推断后续发布或使用必然成功。

[导入页面](../../../app/v2/server/web/src/views/Skills.vue) · [HTTP 路由](../../../app/v2/server/routers/skills.py) · [来源解析](../../../app/v2/server/skills/import_sources.py) · [目录与版本](../../../app/v2/server/skills/service.py)
