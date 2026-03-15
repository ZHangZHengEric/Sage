---
name: "ppt-maker"
description: "生成高颜值、可编辑的原生PPTX。支持主题、图表、布局自动优化。"
---

# HTML PPT Maker

**目标**：将受约束的 HTML/XML 转换为原生 PPTX（文本/形状/表格/图表均为可编辑元素）。

## 1. 核心约束 (Core Constraints)

1.  **根节点**：每个文件必须包含 `<ppt-slide>`。
2.  **坐标系统**：使用英寸 (Inches)，默认 13.333 x 7.5 (16:9)。
3.  **组件多样性 (Component Diversity)**：**整套 PPT (Presentation) 必须包含除图片外的所有组件类型**（即必须至少出现一次 `ppt-text`, `ppt-rect`, `ppt-table`, `ppt-chart`, `ppt-notes`）。图片 `ppt-image` 是可选的。
4.  **布局平衡 (Layout Balance)**：**严禁右侧大面积留白**。使用 `ppt-rect` (色块/卡片) 或 `ppt-chart` 平衡视觉重心。
5.  **字数限制 (Text Limits)**：每页 PPT 中文不超过 100 字，英文不超过 50 个单词。
6.  **标题一致性 (Title Consistency)**：有标题的页面必须使用**一致的标题位置与字号**，不得在同一套 PPT 中随意变化。
7.  **阅读顺序 (Reading Order)**：文字阅读顺序从左到右，整体尽量居中或左对齐，**不接受右对齐**；列表文字尽量左对齐。
8.  **模板与占位 (Template & Placeholder)**：模板仅作参考，必须结合实际内容灵活调整；不允许保留任何占位文字或占位图片。
9.  **每个PPT页面单独一个文件**：不要把所有的xml 都放到一个文件中。**必须使用 `ppt_manager.py add` 命令逐个添加页面，不要直接写入文件**。

## 2. 组件参考 (Component Reference)

**Agent 必须严格参考以下 XML 结构生成代码。**

### 2.1 页面容器 (Slide)
```xml
<!-- 推荐使用 tech-dark 主题，开启自动背景 -->
<ppt-slide width="13.333" height="7.5" theme="tech-dark" auto-bg="true">
  <!-- 内容组件 -->
</ppt-slide>
```
*   **Themes**: `tech-dark` (默认), `corporate`, `minimal-swiss`, `academic`, `data-future`, `luxury-gold`, `soft-pastel`.

### 2.2 文本 (Text) - 支持 Markdown
```xml
<ppt-text x="1" y="0.8" w="11.333" h="1"
          font-size="32" bold="true" align="left" color="#111827"
          font-name="Aptos" class="title">
  这里是标题，支持 **加粗** 和 *斜体*。
</ppt-text>
```
*   **Attrs**: `x, y, w, h`, `font-size`, `bold`, `italic`, `underline`, `color`, `align` (left/center/right), `valign` (top/middle/bottom), `line-spacing`.
*   **约束**: `ppt-text` 若叠放在 `ppt-rect` 上，必须完全位于矩形边框内。

### 2.3 形状 (Rect/Shape) - 用于卡片背景或装饰
```xml
<!-- 卡片背景示例：先画背景，再在上面画文字 -->
<ppt-rect x="1" y="2" w="5" h="4"
          fill="#1F2937" fill-opacity="1"
          line="#374151" line-width="1"
          shape="rounded" radius="0.2" class="card"/>
```
*   **Attrs**: `fill` (hex), `fill-opacity`, `line` (hex), `line-width`, `shape` (rounded/rect/oval).

### 2.4 表格 (Table) - 原生可编辑
```xml
<ppt-table x="1" y="2" w="11" h="4" font-size="14"
           header-fill="#111827" cell-fill="#0F172A"
           col-widths="3,4,4">
  <ppt-row>
    <ppt-cell>Header 1</ppt-cell>
    <ppt-cell>Header 2</ppt-cell>
  </ppt-row>
  <ppt-row>
    <ppt-cell>Value A</ppt-cell>
    <ppt-cell>Value B</ppt-cell>
  </ppt-row>
</ppt-table>
```

### 2.5 图表 (Chart) - 原生可编辑
```xml
<ppt-chart x="7" y="2" w="5.3" h="4" type="column" title="Quarterly Sales">
  Region, Q1, Q2, Q3, Q4
  North, 20, 35, 30, 45
  South, 25, 32, 34, 20
</ppt-chart>
```
*   **Attrs**: `type` (column/bar/line/pie/area/scatter/radar), `title`, `legend` (true/false).
*   **Data**: CSV 格式，第一行为表头。

### 2.6 图片 (Image)
```xml
<ppt-image x="9" y="0.5" w="3" h="1" src="assets/logo.png"/>
```

### 2.7 演讲备注 (Notes)
```xml
<ppt-notes>
  本页重点讲解市场增长率，强调 Q3 的转折点。
</ppt-notes>
```

## 3. 布局与视觉高级指南 (Advanced Layout & Visuals)

为了打造**内容饱满、每一页都不单调**的专业级 PPT，请遵循以下原则：

### 3.1 核心原则：饱满与差异 (Fullness & Variety)
1.  **拒绝空洞**：每一页都必须有“视觉锚点”（Visual Anchors）。如果内容较少，使用大尺寸的 `ppt-chart`、高质量 `ppt-image` 或装饰性 `ppt-rect` 卡片来占据空间。
2.  **布局轮换**：**相邻的两页严禁使用完全相同的布局结构**。必须在以下几种布局模式中切换，以保持观众的注意力。

### 3.2 推荐的高级布局模式 (Premium Layout Patterns)

#### A. 黄金分割/不对称布局 (Asymmetric Split)
*   **结构**：左 60% 内容 + 右 40% 视觉（或反之）。
*   **用法**：主内容区放置核心论点，侧边栏使用深色背景 (`ppt-rect`) 放置补充数据、引用或图标。
*   **效果**：打破对称的沉闷感，显得现代且高级。

#### B. 悬浮卡片网格 (Floating Cards Grid)
*   **结构**：背景层 (`ppt-rect` 全屏或半屏) + 浮动的白色卡片 (`ppt-rect` with shadow)。
*   **配置**：
    *   **3列布局**：用于展示三个核心特性。
    *   **2x2 矩阵**：用于 SWOT 分析或四象限对比。
    *   **Bento Grid (便当盒布局)**：一大配两小，错落有致。

#### C. 沉浸式数据 (Immersive Data)
*   **结构**：全宽图表 (`ppt-chart`) 占据下半部分或右半部分，标题和关键结论悬浮在图表上方或旁侧。
*   **要点**：图表不要做太小，大胆地撑满区域。

#### D. 图文穿插 (Interleaved Flow)
*   **结构**：
    *   Page N: 左文右图。
    *   Page N+1: 上图下文（或右文左图）。
*   **目的**：创造阅读的节奏感。

### 3.3 视觉微调技巧 (Visual Polish)
*   **容器化 (Containerize)**：**不要让文本直接漂浮在背景上**。总是使用 `<ppt-rect>` 创建半透明或实色的容器来承载文本，增加层级感。
*   **留白控制**：虽然要求“饱满”，但是指**视觉元素**的饱满，而非文字堆砌。保持元素间距 (Padding) 至少 0.3 英寸。
*   **装饰元素**：在空白处添加细线条 (`ppt-rect` height="0.05")、半透明圆点或页码标记，增加精致感。

## 4. 最佳实践流程 (Best Practice Workflow)

为了确保 PPT 的专业度和美观度，**Agent 必须遵循以下流程**：
### Step 0: 初始化项目

**获取到项目后，优先初始化PPT项目的文件夹，这个过程需要确定主题**

```
python {ppt-maker-folder-path}/scripts/ppt_manager.py init /path/to/project --theme tech-dark
```

### Step 1: 编写 PPT 大纲 (Outline First)
**在开始写 XML 之前，必须先编写 PPT 大纲文档**。这是确保 PPT 结构清晰、内容完整的关键步骤。

#### 大纲文档应包含：
1.  **文档信息**: 主题、标题、目标受众、预计时长
2.  **每页规划**:
    *   Slide 编号和页面类型 (cover/agenda/content/etc.)
    *   使用的布局 (layout) 和变种 (variant)
    *   页面标题和核心内容
    *   数据/图表信息
    *   设计要点和特殊要求
3.  **设计规范**: 配色方案、字体规范、布局原则

#### 大纲示例格式：
```markdown
## Slide 1: 封面 (cover)
**布局**: cover - variant1
**内容**:
- 标题: Q4 产品发布计划
- 副标题: 战略升级 · 用户体验革新
- 作者: 产品部
- 日期: 2024年12月

**设计要点**:
- 使用深色科技风格
- 标题居中，大号字体
```

#### 为什么先写大纲？
- ✅ 提前规划内容结构，避免遗漏关键信息
- ✅ 确保页面之间的逻辑连贯性
- ✅ 合理分配布局类型，避免单调重复
- ✅ 减少 XML 编写时的反复修改

---
### Step 2 逐页生成PPT页面
#### Step 2.1: 获取对应页面的高质量模板
**不要从零开始写 XML**。使用 `get_template.py` 工具获取预设的、经过验证的优秀布局模板。

##### 可用主题 (Themes)
*   `academic` (学术/教育)
*   `corporate` (企业/商务)
*   `data-future` (数据/科技)
*   `eco-nature` (生态/自然)
*   `luxury-gold` (高端/黑金)
*   `minimal-swiss` (极简/瑞士风格)
*   `soft-pastel` (柔和/粉彩)
*   `tech-dark` (深色科技 - 默认)
*   `vibrant-creative` (活力/创意)
*   `warm-retro` (复古/暖色)

##### 可用布局 (Layouts)
*   `cover` (封面), `agenda` (目录), `section_header` (章节页)
*   `content_split` (图文分栏), `content_cards` (卡片布局)
*   `data_chart` (数据图表), `comparison` (对比分析), `timeline` (时间轴)
*   `steps` (步骤/流程), `process` (循环/进程), `table` (表格)
*   `team` (团队介绍), `gallery` (图片展示), `pricing` (价格表)
*   `budget` (预算/财务), `quote` (引用/金句), `thank_you` (封底)

```bash
# 获取特定布局的模板代码 (例如 tech-dark 主题的封面)
python {ppt-maker-folder-path}/scripts/get_template.py --theme tech-dark --layout cover

# 获取双栏内容页模板
python {ppt-maker-folder-path}/scripts/get_template.py --theme tech-dark --layout content_split
```

#### Step 2.2: 基于大纲和模板生成该页面的 XML (Generate from Outline)

**重要：必须使用 `ppt_manager.py` 工具添加页面，不要直接写入文件！**

工作流程：
1.  **选择模板**：根据大纲选择合适的布局模板
2.  **生成 XML**：参考模板结构，编写符合内容的页面 XML
3.  **添加页面**：使用 `ppt_manager.py add` 命令添加页面（自动验证和修复）
4.  **检查结果**：
    *   如果成功，继续下一页
    *   如果失败，根据返回的错误信息调整 XML，然后重试

```bash
# 添加页面（自动验证，失败会返回详细错误信息）
python {ppt-maker-folder-path}/scripts/ppt_manager.py add /path/to/project \
  --name "slide_name" \
  --xml '<ppt-slide>...</ppt-slide>'
```

**注意事项**：
- 不要直接写入 slides/ 目录下的文件
- 每个页面必须通过 `ppt_manager.py add` 添加
- 验证失败时根据错误提示调整，而不是跳过验证

### Step 3: 自我检查 (Self-Check)
*   [ ] 是否包含了 `ppt-rect` 等装饰元素？（拒绝裸奔）
*   [ ] 这一页的布局是否和上一页明显不同？（拒绝单调）
*   [ ] 右侧是否过于空旷？（拒绝留白）

## 5. 快速使用 (Quick Start)

```bash
# 初始化
python {ppt-maker-folder-path}/scripts/ppt_manager.py init /path/to/project --theme tech-dark

# 添加新页面（自动验证和修复，添加到末尾）
python {ppt-maker-folder-path}/scripts/ppt_manager.py add /path/to/project --name "content" --xml '<ppt-slide>...</ppt-slide>'

# 更新第 3 页（自动验证和修复）
python {ppt-maker-folder-path}/scripts/ppt_manager.py update /path/to/project --position 3 --xml '<ppt-slide>...</ppt-slide>'

# 在第 2 页前插入新页面（自动验证和修复，插入后原第2页及之后的页面自动后移）
python {ppt-maker-folder-path}/scripts/ppt_manager.py insert /path/to/project --position 2 --name "new_slide" --xml '<ppt-slide>...</ppt-slide>'

# 删除第 5 页
python {ppt-maker-folder-path}/scripts/ppt_manager.py remove /path/to/project --position 5

# 查看第 2 页内容
python {ppt-maker-folder-path}/scripts/ppt_manager.py view /path/to/project --position 2

# 列出所有页面
python {ppt-maker-folder-path}/scripts/ppt_manager.py list /path/to/project

# 生成 PPT
python {ppt-maker-folder-path}/scripts/ppt_manager.py build /path/to/project --out result.pptx

# 反向解析 PPTX 为项目
python {ppt-maker-folder-path}/scripts/ppt_to_project.py input.pptx output_dir
```

### 5.1 自动验证和修复

`ppt_manager.py` 会在添加/更新页面时自动进行：

1. **XML 格式验证**：检查根节点、内容元素、语法
2. **自动修复**：
   - 缺失 width/height → 添加默认值 (13.333 x 7.5)
   - 负数坐标 → 调整为 0
   - 坐标超出边界 → 调整为合理值
   - 尺寸溢出 → 调整为合适值
   - 缺少文本颜色 → 添加主题默认颜色
3. **渲染验证**：使用 HtmlPptConverter 验证最终效果

如果验证失败，会返回详细的错误信息和调整建议。
