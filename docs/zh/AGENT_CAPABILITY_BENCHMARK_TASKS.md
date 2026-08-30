# 通用 Agent 能力基准任务集

本文档提供一组与任何具体业务代码无关的常见 Agent 任务，用于比较重构前后 Agent 在文件操作、代码实现、调试、测试、数据处理、约束遵循和结果汇报方面的能力。

如果只想运行一次评测，优先使用下方的 **C01 单题综合评测**。它不要求评测者预先创建代码或数据：只需给 Agent 一个空目录并复制完整任务正文，固定种子数据、程序、测试和报告均由 Agent 在任务过程中创建。后续简单和中等任务仅用于对某项能力进行专项复测。

任务默认在一次性的空目录中执行，不需要网络，也不依赖已有项目。除非题目另有说明，推荐使用 Python 3 标准库和 `pytest`。每道题应启动一个全新的 Agent 会话，避免前一道题的上下文影响结果。

## 一、建议评测方法

### 1. 环境规则

- 每题创建独立目录，例如 `agent-benchmark/S01`、`agent-benchmark/M01`。
- 将任务正文原样发给 Agent，不追加实现提示。
- 不允许 Agent 读取其他题目的答案或目录。
- 默认禁止联网和安装新依赖；确有需要时，题目会明确说明。
- 保留 Agent 的完整工具调用、最终回复、生成文件和测试输出。
- 如果 Agent 主动发现信息不足，允许其提出澄清问题；不应因合理提问直接扣分。

### 2. 通用评分表

每题满分 10 分：

| 维度 | 分值 | 判断标准 |
| --- | ---: | --- |
| 任务结果 | 4 | 核心交付物正确，满足明确需求 |
| 验证质量 | 2 | 执行了与风险匹配的检查或测试，并如实汇报 |
| 约束遵循 | 2 | 未越界修改、未使用被禁止方式、未遗漏格式要求 |
| 工作过程 | 1 | 能有效检索、定位、分解问题，没有明显无效循环 |
| 最终汇报 | 1 | 简洁说明改动、验证结果和剩余问题，不虚构执行记录 |

建议同时记录以下退化信号：

- 没有查看现状便直接覆盖文件。
- 修改了题目范围外的文件。
- 遇到一次失败便停止，未尝试定位原因。
- 没有运行测试却声称测试通过。
- 为简单问题引入大量抽象或第三方依赖。
- 忽略数据边界、幂等性、路径安全或兼容性要求。
- 已完成任务但继续反复修改，最终引入回归。

## 二、C01 单题综合评测（推荐）

这是默认推荐题。它在一次任务中覆盖：任务规划、目录检查、精确文件创建、CSV 解析、输入校验、数据规范化、CLI 设计、持久化、原子写入、幂等性、错误处理、单元测试、集成测试、文档和最终汇报。建议限时 35～60 分钟。

### 使用方式

1. 为 Agent 提供一个空目录。
2. 将下面“任务正文”完整复制给 Agent。
3. 不需要评测者提前创建任何文件或安装任何依赖。
4. Agent 完成后，依据后面的“评测者验收表”评分。

### 任务正文

````text
请在当前空目录完成一个离线 Worklog 任务管理器。你需要自己创建固定种子数据、实现程序、测试、文档和示例报告，并实际完成验证。

开始要求：
- 先检查当前目录，确认不会覆盖已有文件；如果目录并非空目录，先说明情况并避免修改不相关文件。
- 给出一个简短计划后继续执行，不要等待确认。
- 禁止联网、禁止安装依赖、禁止修改当前目录之外的文件。
- 运行时代码只使用 Python 3 标准库；测试可以使用环境中已有的 pytest。

第一步：创建固定输入

创建 input/work_items.csv，内容必须与下面完全一致，包括顺序和无效记录：

```csv
id,title,owner,status,estimate_hours,spent_hours,tags
T-001,Write release notes,Alice,done,3,2.5,"Docs, Release"
T-002,Fix login retry,Bob,in_progress,5,6,"Backend, urgent"
T-003,Update screenshots,Chen,todo,2,0,"Docs, UI"
T-004,Prepare demo,Alice,done,1.5,1.5,"Release"
T-002,Duplicate retry task,Bob,todo,2,0,"backend"
T-005,Waiting for approval,Dana,waiting,2,0,"Process"
T-006,Invalid estimate,Eve,todo,-1,0,"Planning"
T-007,Invalid spent,Fred,todo,1,not_available,"Planning"
T-008,"Review API, examples",Chen,todo,4,1,"API, Docs, api"
```

创建后重新读取该文件，确认共有 9 条数据记录。此后不得修改种子文件。

第二步：实现 CLI

至少交付以下文件：

- worklog.py
- test_worklog.py
- README.md
- input/work_items.csv

CLI 命令：

```text
python worklog.py import INPUT.csv
python worklog.py list [--owner OWNER] [--status STATUS] [--tag TAG] [--json]
python worklog.py add --id ID --title TITLE --owner OWNER --status STATUS --estimate HOURS [--spent HOURS] [--tags TAG1,TAG2]
python worklog.py complete ID [--spent HOURS]
python worklog.py report --output PATH
```

数据默认保存到当前目录的 worklog.json；环境变量 WORKLOG_FILE 可以覆盖数据文件位置。

数据规则：

1. id 必须匹配 `T-` 加三位数字，并且唯一。
2. title 和 owner 去除首尾空格后不能为空。
3. status 只能是 todo、in_progress、done。
4. estimate_hours 和 spent_hours 必须是大于等于 0 的十进制数；不得依赖二进制浮点完成汇总。
5. tags 按逗号拆分，去除首尾空格、转为小写、删除空项、去重并升序排列。
6. import 遇到无效行时继续处理其余行；同一输入中 id 重复时保留第一条有效记录，后续重复行记为拒绝。
7. import 输出 `import_errors.json`，文件放在数据文件所在目录；逐条记录被拒绝的 CSV 行号、原始 id 和稳定、可读的错误原因。没有错误时写出空数组。
8. import 成功时在 stdout 报告 imported、skipped 和 rejected 数量。
9. 对同一 CSV 重复 import 必须幂等：与已有任务规范化后完全一致的记录记为 skipped，不得改写；相同 id 但内容不同的记录记为 rejected。重复导入固定种子时应得到 imported=0、skipped=5、rejected=4。
10. 所有列表和 JSON 数组按 id 升序输出，保证结果稳定。

命令行为：

- list 的 owner 匹配忽略大小写；status 和 tag 做规范化后的精确匹配。
- list --json 的 stdout 只能包含合法 JSON；诊断信息不得混入 stdout。
- add 遇到重复 id 或非法字段时返回非零退出码，显示清晰错误，且不能改变数据文件。
- complete 将任务状态改为 done；提供 --spent 时同时更新 spent_hours。未知 id 或非法 spent 返回非零退出码且不能改变数据文件。
- report 生成 Markdown，依次包含“摘要、状态统计、负责人统计、超出预估、任务明细”五个二级标题。
- “超出预估”列出 spent_hours 大于 estimate_hours 的任务；没有时明确写“无”。
- 报告包含总任务数、总预估工时和总已用工时，数值去除无意义的尾随零。
- 数据写入必须使用同目录临时文件加原子替换；失败时不能留下半个 JSON。
- 数据文件不存在时，list、add 和 import 可以从空状态开始；数据文件存在但不是合法 JSON 时必须清晰失败，不得覆盖损坏文件。

第三步：测试

使用 pytest 编写自动化测试，至少覆盖：

- 固定种子数据导入后 5 条成功、0 条跳过、4 条拒绝；
- 重复 import 得到 0 条成功、5 条跳过、4 条拒绝，且数据文件内容不变；
- 标签规范化与带逗号的 CSV 标题；
- list 的 owner、status、tag 过滤及确定性顺序；
- list --json 的 stdout 可直接解析；
- add 成功、重复 id 和非法数据；
- complete 成功、未知 id 和非法 spent；
- 报告的汇总数字、标题顺序和超出预估任务；
- 损坏 JSON 数据文件不会被覆盖；
- CLI 的成功与失败退出码；
- WORKLOG_FILE 能让测试使用临时目录，不污染当前目录。

测试不得访问网络，不得依赖测试执行顺序，不得使用当前真实 worklog.json。测试结束后不能遗留后台进程。

第四步：文档与验收

README.md 必须包含：功能简介、运行要求、全部命令说明、至少一套从 import 到 report 的完整示例、数据与错误处理规则、测试命令。

完成实现后，执行以下验收流程，使用临时数据文件，不能污染默认 worklog.json：

1. 运行完整 pytest 测试。
2. 使用固定 CSV 执行 import。
3. 执行 list --json，并使用 Python JSON 解析器验证 stdout。
4. 生成 report.md。
5. 重新读取 import_errors.json 和 report.md，核对数量与汇总。

固定数据的预期结果：

- 首次导入 imported = 5、skipped = 0、rejected = 4；第二次导入 imported = 0、skipped = 5、rejected = 4。
- 状态统计：todo=2、in_progress=1、done=2。
- 总预估工时 = 15.5。
- 总已用工时 = 11。
- 超出预估的任务只有 T-002。
- T-008 的标题必须完整保留为 `Review API, examples`，tags 为 api、docs。

最终回复必须包含：

- 创建或修改的文件；
- 关键实现取舍；
- 实际执行过的测试和验收命令及结果；
- 是否存在未完成项。

不要声称没有实际运行的命令已经通过。如果某一步失败，应先定位并尝试修复，再如实汇报。
````

### 评测者验收表

C01 满分 100 分，便于观察细粒度差异：

| 维度 | 分值 | 核心检查项 |
| --- | ---: | --- |
| 种子与范围 | 8 | CSV 精确、9 条记录、未修改种子、未越界写文件 |
| 导入与校验 | 15 | 5/4 结果、行号和原因、重复 ID、不中断后续行 |
| CLI 完整性 | 15 | 五类命令可用、过滤准确、退出码和 stdout 合同正确 |
| 数据正确性 | 12 | Decimal 语义、标签规范化、稳定排序、标题含逗号不丢失 |
| 持久化可靠性 | 12 | 环境变量隔离、原子替换、幂等、损坏 JSON 不覆盖 |
| 报告正确性 | 10 | 五个标题有序、状态和工时准确、T-002 被识别 |
| 测试质量 | 15 | 覆盖要求完整、测试隔离、包含 CLI 集成测试、无网络 |
| 文档质量 | 5 | 命令、规则和完整示例准确，不虚构功能 |
| 执行过程 | 4 | 先检查和规划，失败后能定位，没有明显无效循环 |
| 最终汇报 | 4 | 文件、取舍、真实命令结果和未完成项完整准确 |

建议重点观察以下“一票警报”，出现时即使最终输出看似正确也应记录：

- 覆盖或修改种子 CSV 来让测试通过。
- 只测试内部函数，没有测试 CLI 退出码和标准输出。
- 使用 float 后通过硬编码或格式化掩盖计算问题。
- import 第二次运行产生重复数据或改写已有任务。
- 损坏 JSON 时静默重建，造成数据丢失。
- `--json` 输出混入说明文字。
- 测试使用默认 worklog.json，污染工作目录或相互影响。
- 未执行测试却在最终回复中声称全部通过。

### 快速分级参考

| 分数 | 参考结论 |
| ---: | --- |
| 90～100 | Agent 能稳定完成多步骤工程任务，约束与验证能力良好 |
| 75～89 | 核心能力正常，但在边界、测试或汇报上有少量遗漏 |
| 60～74 | 能产出主体功能，但可靠性或自主验证明显不足 |
| 40～59 | 需要频繁人工纠偏，多步骤闭环能力可能退化 |
| 0～39 | 无法稳定完成任务，存在严重越界、错误交付或虚假验证 |

## 三、简单任务（可选专项复测）

简单任务适合检查基础工具使用和单步闭环能力，建议每题限时 5～12 分钟。

### S01：将原始记录整理为结构化会议纪要

能力点：指令遵循、信息提取、Markdown 写作、避免臆造。

任务正文：

```text
请在当前目录创建 meeting_notes.md，将下面的原始记录整理为会议纪要。

原始记录：
- 会议时间：2026-08-28 10:00
- 参会人：Alice、Bob、陈晨
- Alice：新版帮助中心计划 9 月 10 日上线。
- Bob：搜索索引迁移还需要两天，负责人是 Bob，截止 9 月 2 日。
- 陈晨：中文文案已经完成，英文文案缺少最终校对。
- 决定：上线前必须完成搜索迁移和英文校对。
- Alice 将在 9 月 3 日前确认上线检查清单。
- 英文校对由陈晨负责，截止 9 月 4 日。
- 下次会议：2026-09-05 10:00。

文件必须依次包含以下二级标题：会议信息、关键结论、行动项、风险、下次会议。
行动项使用 Markdown 表格，列为“负责人、事项、截止日期、状态”，并按截止日期升序排列；未提供的状态统一写“待处理”。
只能使用原始记录中的事实，不得补充推测。创建后重新读取文件，确认标题和行动项无遗漏。
最终回复只说明文件路径和检查结果。
```

验收重点：5 个标题顺序正确；3 个行动项完整且排序正确；没有虚构风险负责人或完成状态。

### S02：创建一个最小静态网页

能力点：多文件创建、相对路径、基础 HTML/CSS、交付验证。

任务正文：

```text
请在当前目录创建 mini_site，包含 index.html、styles.css 和 README.md。

要求：
1. 页面标题为“Focus Timer”。
2. 页面包含一个 25:00 的计时器展示、一个“开始”按钮和三条使用说明。
3. HTML 使用语义化标签，并通过相对路径加载 styles.css。
4. CSS 实现居中卡片、清晰的按钮悬停状态，并兼容窄屏；不要使用外部字体、图片或框架。
5. 不写 JavaScript，按钮不需要实际计时功能。
6. README.md 说明如何直接在浏览器打开页面，并列出文件结构。

完成后检查三个文件都存在，HTML 引用的本地资源路径有效。不要启动长期运行的服务器。
```

验收重点：文件齐全；无外部依赖；HTML/CSS 链接有效；没有擅自加入 JavaScript。

### S03：修复一个边界条件错误

能力点：读取代码、复现失败、最小修复、回归测试。

评测者准备：在空目录创建 `stats.py` 和 `test_stats.py`。

`stats.py`：

```python
def median(values):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median requires at least one value")
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return ordered[middle - 1] + ordered[middle] / 2
```

`test_stats.py`：

```python
import pytest

from stats import median


def test_odd_count():
    assert median([9, 1, 5]) == 5


def test_even_count():
    assert median([1, 3, 7, 9]) == 5


def test_does_not_modify_input():
    values = [3, 1, 2]
    median(values)
    assert values == [3, 1, 2]


def test_empty():
    with pytest.raises(ValueError):
        median([])
```

任务正文：

```text
当前目录有一个小型 Python 模块及其测试，其中一个边界条件实现错误。请先运行测试复现问题，再定位根因并进行最小修复。

要求：
- 不改变公开函数名和异常行为。
- 不删除或弱化现有测试。
- 为本次错误补充至少一个有效测试用例。
- 修复后运行完整测试。
- 最终说明根因、改动和实际测试结果。
```

验收重点：偶数个值的中位数必须为中间两项之和除以 2；测试不是重复已有断言；无无关重构。

### S04：清洗并汇总 CSV 数据

能力点：结构化数据处理、数值计算、输出一致性。

评测者准备 `sales.csv`：

```csv
date,region,product,quantity,unit_price
2026-08-01,East,Notebook,2,12.50
2026-08-01,West,Pen,10,1.20
2026-08-02,East,Pen,5,1.20
2026-08-03,North,Notebook,1,12.50
2026-08-03,West,Notebook,3,12.50
2026-08-04,East,Pen,not_available,1.20
2026-08-05,West,Pen,4,1.20
```

任务正文：

```text
请分析当前目录的 sales.csv，并生成 analyze_sales.py、summary.csv 和 report.md。

要求：
- 仅使用 Python 标准库。
- quantity 或 unit_price 不是合法数字的行视为无效行，不参与收入计算。
- summary.csv 按 region 升序输出，列为 region、valid_orders、units、revenue。
- revenue = quantity * unit_price，统一保留两位小数。
- report.md 写出总有效订单数、总收入、收入最高的地区和无效行数。
- 地区收入相同则按地区名称升序选择“收入最高的地区”。
- 脚本重复运行必须生成相同结果，不得修改 sales.csv。

完成后运行脚本并核对两个输出文件。
```

验收重点：无效行数为 1；金额使用十进制安全方式或能稳定得到正确的两位小数；输出顺序确定。

### S05：规范化 JSON 配置

能力点：JSON 读写、去重、稳定排序、保留未知字段。

评测者准备 `input.json`：

```json
{
  "name": "  Demo Service  ",
  "tags": ["API", "api", " Stable ", "", "stable", "Tools"],
  "ports": [8080, "8080", 3000, 8080],
  "metadata": {"owner": "team-a", "priority": 2}
}
```

任务正文：

```text
请创建 normalize_config.py，读取 input.json 并写出 normalized.json。

规则：
- name 去除首尾空格。
- tags 去除首尾空格、转为小写、删除空值、去重并升序排列。
- ports 接受整数或仅包含数字的字符串，转换为整数、去重并升序排列。
- 顶层和嵌套的其他字段原样保留。
- 输出使用 UTF-8、两个空格缩进，并以换行结尾。
- 输入文件不得被修改，脚本重复执行结果必须稳定。

请运行脚本，再使用 Python 重新解析 normalized.json，确认它是有效 JSON。最终汇报生成文件和验证结果。
```

验收重点：保留 `metadata`；tags 和 ports 结果准确；输出确定且有效。

### S06：为现有函数补充单元测试

能力点：测试设计、边界覆盖、识别规格与实现的关系。

评测者准备 `slug.py`：

```python
import re


def slugify(value: str, max_length: int = 40) -> str:
    if max_length < 1:
        raise ValueError("max_length must be positive")
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:max_length].rstrip("-")
```

任务正文：

```text
请为 slug.py 中的 slugify 编写 pytest 测试，保存为 test_slug.py。

至少覆盖：
- 普通英文短语；
- 连续标点与首尾空格；
- 空字符串；
- max_length 截断；
- 截断后不能以连字符结尾；
- 非法 max_length；
- 重复调用结果一致。

不要修改 slug.py，除非测试证明实现违反上述明确行为；如果确需修改，必须在最终回复解释。完成后运行测试。
```

验收重点：断言有意义且互不重复；异常测试准确；没有为了让测试通过而弱化断言。

### S07：从日志中提取错误摘要

能力点：文本检索、关联信息、精确汇总、不修改源数据。

评测者准备 `app.log`：

```text
2026-08-30T09:00:01Z INFO request_id=r1 route=/health status=200
2026-08-30T09:01:12Z INFO request_id=r2 route=/orders status=200
2026-08-30T09:01:13Z ERROR request_id=r3 route=/orders code=DB_TIMEOUT message="database timed out"
2026-08-30T09:01:14Z WARN request_id=r3 retry=1
2026-08-30T09:02:20Z ERROR request_id=r4 route=/login code=INVALID_TOKEN message="token expired"
2026-08-30T09:03:30Z ERROR request_id=r5 route=/orders code=DB_TIMEOUT message="database timed out"
2026-08-30T09:03:31Z INFO request_id=r5 recovery=success
```

任务正文：

```text
请读取 app.log，生成 incident_summary.md。

文件需要包含：
1. ERROR 总数和不同 request_id 数量；
2. 按错误 code 汇总的 Markdown 表格，列为 code、count、request_ids；
3. 每个错误请求是否出现后续恢复记录；
4. 一句基于日志事实的结论。

request_ids 在单元格中按字典序排列，以英文逗号连接。不得修改 app.log，不得把 WARN 当作 ERROR，也不要推断日志没有提供的信息。生成后复查所有 ERROR 行均已计入。
```

验收重点：ERROR 为 3 条、不同请求为 3 个；只有 r5 有明确恢复记录；结论不把“无恢复记录”表述为“恢复失败”。

### S08：同步命令行帮助与 README

能力点：以实现为事实来源、文档维护、范围控制。

评测者准备 `convert.py`：

```python
import argparse


def parser():
    result = argparse.ArgumentParser(description="Convert text files")
    result.add_argument("source")
    result.add_argument("--output", "-o", default="output.txt")
    result.add_argument("--uppercase", action="store_true")
    return result


if __name__ == "__main__":
    parser().parse_args()
```

同时准备过期的 `README.md`：

```markdown
# Text Converter

Usage: `python convert.py SOURCE --dest FILE`

Options:
- `--dest`: output path
- `--lowercase`: convert output to lowercase
```

任务正文：

```text
README.md 中的命令行说明已经过期。请把 convert.py 的实际 --help 输出作为事实来源，修正文档。

要求：
- 不修改 convert.py 的程序逻辑。
- README 必须包含正确的基本用法、参数说明和两个有效示例。
- 不要描述代码中不存在的功能。
- 运行 --help 验证文档中的选项名称。
- 最终回复说明修改内容和验证命令。
```

验收重点：移除 `--dest`、`--lowercase`；准确记录 `--output/-o` 和 `--uppercase`。

## 四、中等难度任务（可选专项复测）

中等任务检查多步骤执行、跨文件修改、错误恢复和非功能约束，建议每题限时 15～35 分钟。

### M01：实现持久化书签 CLI

能力点：需求分解、CLI、持久化、原子写入、测试。

任务正文：

```text
请在当前空目录实现一个只依赖 Python 标准库的书签管理 CLI。

交付文件至少包含 bookmarks.py、test_bookmarks.py 和 README.md。

命令：
- python bookmarks.py add URL --title TITLE [--tags TAG1,TAG2]
- python bookmarks.py list [--tag TAG] [--json]
- python bookmarks.py remove URL

行为要求：
1. 数据默认保存在当前目录的 bookmarks.json。
2. URL 是唯一键；重复 add 更新标题和标签，但保留原始 created_at。
3. 标签需要去除空格、转小写、去重并排序。
4. list 默认按 created_at 升序；--tag 做精确标签过滤。
5. --json 输出必须是可解析 JSON，普通输出应适合人阅读。
6. remove 不存在的 URL 时返回非零退出码和清晰错误，但不能损坏数据文件。
7. 数据写入采用临时文件加原子替换，尽量避免中途失败留下半个 JSON。
8. 可通过 BOOKMARKS_FILE 环境变量覆盖存储位置，方便测试。

请编写覆盖新增、更新、过滤、删除失败和持久化的测试。运行完整测试，并在 README 中给出使用示例。不要安装第三方运行时依赖；测试可以使用环境中已有的 pytest。
```

验收重点：CLI 真实可运行；更新不改变 `created_at`；原子替换；错误退出码正确；测试隔离真实工作目录。

### M02：修复路径穿越漏洞

能力点：安全边界、漏洞复现、跨平台路径处理、负向测试。

评测者准备 `files.py`：

```python
from pathlib import Path


def read_document(root: Path, requested_path: str) -> str:
    path = root / requested_path
    return path.read_text(encoding="utf-8")
```

以及 `test_files.py`：

```python
from pathlib import Path

from files import read_document


def test_reads_nested_document(tmp_path: Path):
    docs = tmp_path / "docs"
    nested = docs / "guides"
    nested.mkdir(parents=True)
    (nested / "start.txt").write_text("hello", encoding="utf-8")
    assert read_document(docs, "guides/start.txt") == "hello"
```

任务正文：

```text
read_document 应只允许读取 root 目录内部的普通文件，但当前实现存在路径穿越风险。请复现并修复。

要求：
- 保持 read_document(root, requested_path) 的函数签名。
- 合法的嵌套相对路径继续工作。
- 拒绝 ../、绝对路径和通过符号链接逃出 root 的路径。
- 目录路径也必须拒绝。
- 越界或非法请求统一抛出 ValueError，文件不存在仍保留 FileNotFoundError。
- 不使用字符串前缀判断路径归属。
- 补充覆盖正常、父目录穿越、绝对路径、相似目录名前缀、符号链接和目录路径的测试。

先运行现有测试，再实施最小修复并运行完整测试。最终说明安全根因和平台相关注意事项。
```

验收重点：使用解析后的路径归属判断；能阻止 symlink escape；没有把不存在文件错误错误地改成 ValueError。

### M03：实现向后兼容的配置迁移器

能力点：模式迁移、幂等性、未知字段保留、备份与测试。

任务正文：

```text
请实现 migrate_config.py，将旧版 JSON 配置迁移到 version=2。

旧版示例：
{
  "version": 1,
  "server": {"host": "127.0.0.1", "port": 8080},
  "debug": true,
  "plugins": ["search", "export"],
  "custom": {"owner": "team-a"}
}

新版规则：
- version 改为 2。
- server 移到 runtime.server，内容保持不变。
- debug 移到 runtime.logging.level：true 对应 "debug"，false 对应 "info"。
- plugins 的字符串元素改为 {"name": 原值, "enabled": true}。
- 未识别字段必须原样保留。

CLI：python migrate_config.py PATH [--check]

要求：
1. 普通模式迁移前创建 PATH.bak；如果备份已存在，不覆盖它。
2. 使用临时文件和原子替换写回 PATH。
3. --check 只报告是否需要迁移，不修改任何文件；需要迁移时退出码为 1，不需要时为 0。
4. 对 version=2 重复执行不得改变内容，也不得创建新备份。
5. 缺失 version、未知 version、非法 JSON 必须给出清晰错误且不修改原文件。
6. 嵌套的未知字段也不能丢失。

请编写 pytest 测试覆盖迁移、幂等、check 模式、备份、未知字段和错误输入，并写一份简短 README。只使用 Python 标准库实现运行时代码。
```

验收重点：迁移不丢数据；备份语义准确；检查模式无副作用；失败不会留下部分写入。

### M04：关联多份服务日志生成事故报告

能力点：跨文件检索、时间线重建、确定性输出、事实与推断区分。

评测者准备三个文件：

`gateway.log`：

```text
2026-08-30T10:00:00.100Z request=r10 event=received path=/checkout
2026-08-30T10:00:00.250Z request=r10 event=upstream_call service=orders
2026-08-30T10:00:03.500Z request=r10 event=response status=504
2026-08-30T10:01:00.000Z request=r11 event=received path=/health
2026-08-30T10:01:00.020Z request=r11 event=response status=200
```

`orders.log`：

```text
2026-08-30T10:00:00.300Z request=r10 event=reserve_start cart=c7
2026-08-30T10:00:02.900Z request=r10 event=reserve_failed reason=inventory_timeout
```

`inventory.log`：

```text
2026-08-30T10:00:00.450Z request=r10 event=query sku=s1
2026-08-30T10:00:02.800Z request=r10 event=timeout elapsed_ms=2350
```

任务正文：

```text
请分析当前目录的 gateway.log、orders.log 和 inventory.log，生成 build_incident_report.py 和 incident_report.md。

要求：
- 脚本解析三个日志文件，并按 ISO 时间升序生成 r10 的统一时间线。
- 每一行时间线必须标明来源服务、时间和事件。
- 报告分为“摘要、时间线、已确认事实、合理推断、未知信息”。
- “已确认事实”只能来自日志直接证据。
- 可以把库存查询超时与订单预留失败的关系列为合理推断，但不能写成已证明根因。
- 明确指出日志不能回答的至少两个问题。
- 脚本重复运行输出必须一致；不得修改原始日志。
- 为解析和排序逻辑编写测试。

请运行脚本和测试，最终汇报结果。
```

验收重点：时间线共 7 条 r10 记录且顺序正确；区分事实、推断和未知信息；不把 r11 混入事故时间线。

### M05：提取重复逻辑并保持兼容

能力点：代码检索、重构、兼容性、回归测试、克制修改。

评测者准备：

`customer.py`：

```python
def normalize_contact(email: str) -> str:
    value = email.strip().lower()
    if value.count("@") != 1:
        raise ValueError("invalid email")
    local, domain = value.split("@")
    if not local or "." not in domain:
        raise ValueError("invalid email")
    return value
```

`newsletter.py`：

```python
def normalize_subscriber(address: str) -> str:
    value = address.strip().lower()
    if value.count("@") != 1:
        raise ValueError("invalid email")
    local, domain = value.split("@")
    if not local or "." not in domain:
        raise ValueError("invalid email")
    return value
```

`test_contacts.py`：

```python
import pytest

from customer import normalize_contact
from newsletter import normalize_subscriber


@pytest.mark.parametrize("function", [normalize_contact, normalize_subscriber])
def test_normalizes(function):
    assert function(" User@Example.COM ") == "user@example.com"


@pytest.mark.parametrize("function", [normalize_contact, normalize_subscriber])
def test_rejects_invalid(function):
    with pytest.raises(ValueError, match="invalid email"):
        function("invalid")
```

任务正文：

```text
customer.py 和 newsletter.py 存在重复的邮箱规范化逻辑。请提取共享实现，同时保持两个现有公开函数、参数名、返回值和异常信息兼容。

额外规则：
- 域名部分大小写不敏感，应转为小写。
- 本地部分必须保留原始大小写，只去除整个地址首尾空格。
- 不要尝试实现完整 RFC 邮箱解析，也不要引入第三方依赖。
- 共享实现放在一个职责清晰的新模块中。
- 扩展测试，证明两个旧入口行为一致、兼容，并覆盖本地部分大小写。
- 检查项目中所有调用点后再修改，避免遗漏。

先运行测试建立基线，再重构并运行完整测试。最终说明原实现与新规则之间的行为变化。
```

验收重点：两个旧入口仍可导入；本地部分 `User` 不应被小写；异常消息兼容；没有循环导入。

### M06：实现确定性的并发校验工具

能力点：并发、稳定输出、局部失败、测试替身。

任务正文：

```text
请实现 check_urls.py、test_check_urls.py 和 README.md。

check_urls.py 读取一个文本文件，每行一个 URL，忽略空行和以 # 开头的注释，并发执行 HTTP HEAD 请求。

要求：
- 运行时代码只使用 Python 标准库。
- CLI：python check_urls.py urls.txt [--workers N] [--timeout SECONDS] [--json]
- workers 默认 4，必须大于 0。
- 每个 URL 的结果包含 url、ok、status、elapsed_ms、error。
- 单个请求失败不能中止其他请求。
- 输出顺序必须与输入中首次出现的顺序一致；重复 URL 只请求一次。
- HTTP 2xx 和 3xx 视为 ok。
- --json 输出必须保持机器可解析，诊断信息不得混入 stdout。
- 如果任意 URL 失败，进程最终退出码为 1，否则为 0。
- 测试不能访问公网；使用本地临时 HTTP 服务或 mock。
- 正常结束后不能遗留后台线程或服务器进程。

请覆盖去重、顺序、成功、HTTP 错误、连接错误、非法 workers 和退出码。运行测试并在 README 中给出示例。
```

验收重点：确实并发但结果确定；测试完全离线；错误隔离；标准输出合同正确。

### M07：实现可恢复的批处理任务

能力点：检查点、幂等性、故障恢复、原子状态、集成测试。

任务正文：

```text
请实现 batch_processor.py，用于将 input 目录中的 .txt 文件转换后写入 output 目录。

转换规则：去除每行首尾空格、删除空行、将剩余行转为大写，并保证输出以一个换行结尾。

CLI：python batch_processor.py INPUT_DIR OUTPUT_DIR [--state STATE_FILE] [--fail-after N]

要求：
1. 按相对路径字典序处理所有 .txt 文件，并在 output 中保留子目录结构。
2. 默认状态文件为 OUTPUT_DIR/.batch-state.json。
3. 每成功处理一个文件后原子更新状态，记录输入文件的 SHA-256 和完成状态。
4. 再次运行时，输入哈希未变化且输出仍存在的文件应跳过。
5. 输入内容改变或输出丢失时必须重新处理。
6. --fail-after N 用于测试：本次运行成功写入 N 个文件后主动抛出错误。
7. 中断后重新运行应从已完成位置继续，不重复改写可跳过文件。
8. 写输出和状态时都使用临时文件加原子替换。
9. 非 txt 文件不处理，状态文件自身不能被当作输入。

请编写测试覆盖首次运行、跳过、输入变化、输出丢失、嵌套目录和故障恢复。不得依赖 sleep 判断文件是否被重写，可以使用内容、mock 或纳秒时间戳。运行完整测试并写 README。
```

验收重点：恢复语义真实有效；检查点在成功后更新；失败不会把未完成文件标成完成；测试不脆弱。

### M08：构建一个小型本地任务 API

能力点：HTTP 服务、验证、状态持久化、并发安全、端到端测试。

任务正文：

```text
请使用 Python 标准库实现一个本地任务 API，交付 server.py、test_server.py 和 README.md。

接口：
- POST /tasks，JSON 请求体为 {"title": "..."}，创建任务并返回 201。
- GET /tasks，返回全部任务。
- GET /tasks/{id}，返回单个任务。
- PATCH /tasks/{id}，允许更新 title 或 completed。
- DELETE /tasks/{id}，删除成功返回 204。

要求：
1. 数据持久化到 JSON 文件，可通过 TASKS_FILE 环境变量覆盖。
2. 任务字段为 id、title、completed、created_at；id 在单个数据文件中不可重复。
3. title 去除首尾空格后不能为空；completed 必须是布尔值。
4. 不存在资源返回 404，非法 JSON 或字段返回 400，不支持的方法返回合适状态码。
5. Content-Type 为 application/json 的响应必须是合法 JSON。
6. 并发请求不能丢失已成功写入的任务；文件写入使用临时文件和原子替换。
7. CLI 支持 --host 和 --port，其中 --port 0 可让操作系统选择空闲端口。
8. 测试必须在本机临时端口运行，不能访问公网，结束后关闭服务并清理线程。
9. README 给出启动方式和 curl 示例。

请先给出简短实现计划，再完成实现、端到端测试和验证。不要安装 Web 框架。
```

验收重点：HTTP 状态和验证准确；测试能真实发请求；并发写入有保护；服务测试后完全退出。

## 五、推荐组合

如果不想一次跑完全部任务，可以使用以下组合：

| 组合 | 任务 | 主要覆盖面 |
| --- | --- | --- |
| 单题综合 | C01 | 一次覆盖规划、实现、数据、CLI、可靠性、测试和汇报 |
| 10 分钟冒烟 | S01、S03 | 指令遵循、文件写入、基础调试 |
| 30 分钟基础 | S02、S04、S07 | 多文件、数据处理、事实提取 |
| 60 分钟编码 | S03、S06、M01 | 修复、测试设计、完整小功能 |
| 安全与可靠性 | M02、M03、M07 | 路径安全、迁移、故障恢复 |
| 综合能力 | S01、S04、M02、M05、M08 | 文档、数据、安全重构、HTTP 集成 |

## 六、结果记录模板

每次评测可复制以下表格：

```markdown
| 任务 | 结果 0-4 | 验证 0-2 | 约束 0-2 | 过程 0-1 | 汇报 0-1 | 总分 | 用时 | 备注 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| S01 |  |  |  |  |  |  |  |  |
```

除了总分，建议重点比较：首次成功率、平均工具调用次数、无效重复次数、测试真实性、越界修改次数，以及任务完成后是否能及时停止。
