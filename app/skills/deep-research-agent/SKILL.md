---
name: deep-research-agent
description: 深度研究技能，用于系统性调研与分析。适用于研究、调研、竞品分析、市场分析或结构化信息收集等需求。
---

# 深度研究 Agent

以增量方式开展系统化研究并输出。

## 工作流

```
1. 大纲 → 2. 初始化 → 3. 研究 → 4. 更新 → 5. JSON → 6. HTML
```

### 1. 创建大纲（必须）

研究前先向用户展示大纲：
- 研究目标
- 需要回答的关键问题
- 需要探索的信息来源
- 预期交付物

**获得用户确认后再继续。**

### 2. 初始化研究环境

运行初始化脚本，使用绝对路径创建工作目录：

```bash
python skills/deep-research-agent/scripts/init_research.py <absolute_template_path> <absolute_project_path>
```

**用法：** `python init_research.py <absolute_template_path> <absolute_project_path>`

**模板（研究方向模板）：**

不同研究类型使用对应的 Markdown 模板：

模板统一放在 `deep-research-agent/templates` 目录下，初始化时只需选择对应模板文件路径。

**创建内容：**
- `report.md` - 复制选定模板（位于项目目录）
- `materials/` - 原始资料与笔记目录（包含 raw/ 与 notes/）

> **重要：** 不要用 mkdir 或 Write tool 手动创建目录，必须通过初始化脚本生成结构。

### 3. 执行研究（增量）

**搜索并立即保存：**

每条有价值的信息都要 **先保存到 materials 目录：**

```python
file_write(
    file_path="{project_path}/materials/raw/source_001.md",
    content="""## 来源: [标题]
- URL: [链接]
- 时间: [日期]

### 关键信息
- [要点1]
- [要点2]

### 数据
- [数据点]

### 引用原文
> [原文摘录]
"""
)
```

**研究策略：**
- 按章节/小节搜索
- 立即保存来源到 `materials/`
- 标注与报告章节的关联

### 4. 按章节更新报告

当某一节内容充足时，**立即更新报告：**

```python
file_update(
    file_path="{project_path}/report.md",
    search_pattern="## 1. 研究背景与目标\n\n{研究背景说明}",
    replacement="""## 1. 研究背景与目标

### 1.1 研究背景

[基于materials/中的资料，撰写详细背景]

[包含数据支撑、引用来源]

### 1.2 研究目标

[具体目标]

### 1.3 研究范围

[范围界定]"""
)
```

**更新规则：** 某一节有 3+ 可靠来源即可撰写。

### 5. 完成研究数据

**在生成最终输出前，必须执行以下检查：**

1. **清理模板内容**：检查 `report.md` 中是否还有未填充的模板占位符（如 `{研究背景说明}`、`{在此填写...}` 等），**全部删除**
2. **确认章节完整性**：确保所有章节都已用实际研究内容替换，没有空章节
3. **删除未使用章节**：如某些章节无相关内容，直接删除该章节标题

**然后生成**包含结构化数据的 `research_data.json`：

```json
{
  "topic": "...",
  "created_at": "...",
  "outline": {...},
  "materials_count": 15,
  "sections_completed": ["1.1", "1.2", "3.1"],
  "key_findings": [...],
  "sources": [...]
}
```

## 输出结构

```
{user_specified_project_path}/
├── report.md               # 主报告（增量更新）
├── report.html             # 阅读友好的 HTML 版本
├── research_data.json      # 结构化数据
└── materials/
    ├── raw/                # 原始来源
    ├── notes/              # 按章节整理的笔记
    └── ...
```

## 关键原则

1. **先保存**：所有来源立即写入 `materials/`
2. **尽早更新**：内容成熟就写入报告
3. **按章节推进**：不要等全部研究完成
4. **引用来源**：报告内引用 materials/ 文件
5. **结构一致**：`research_data.json` 与报告保持一致
6. **HTML 输出**：最终必须将 report.md 转为 HTML，使用 `scripts/md_to_html.py` 生成。
   - 命令：`python skills/deep-research-agent/scripts/md_to_html.py /absolute/path/report.md`
   - 默认输出为 report.html，可用 `--out` 指定输出路径。

## 模板选择指南

模板位置：`deep-research-agent/templates`。无需在此列出具体模板名称。
