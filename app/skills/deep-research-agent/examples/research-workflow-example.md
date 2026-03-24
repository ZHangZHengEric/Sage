# 增量式调研工作流示例

## 场景
用户请求："帮我做一个关于AI在医疗领域应用的深度调研"

---

## Step 1: 确定大纲并选择模板

### 1.1 向用户呈现调研大纲

```markdown
## AI医疗应用调研大纲

### 调研目标
全面了解人工智能在医疗领域的应用现状、市场规模、技术趋势

### 核心研究问题
1. AI医疗市场的整体规模和发展趋势如何？
2. 主要的应用场景和技术方案有哪些？
3. 市场的主要参与者和竞争格局如何？
4. 政策环境和监管要求是什么？
5. 面临的挑战和未来机遇有哪些？

### 章节规划
- 执行摘要
- 行业概览（定义、发展历程、产业链）
- 市场环境分析（PEST、规模、细分）
- 竞争格局分析（参与者、份额、策略）
- 技术发展趋势（现状、演进、壁垒）
- 风险与机遇
- 结论与建议

### 信息收集方向
- 全球及中国AI医疗市场规模数据
- 医学影像、药物研发、智能诊断等应用场景
- 主要企业（Google Health、IBM Watson Health等）
- 各国监管政策和FDA/NMPA审批情况

请确认这个大纲是否符合您的需求？
```

### 1.2 用户确认后，初始化研究目录

根据主题性质（行业研究），选择模板：`industry-research-template.md`

运行脚本初始化：

```bash
python /app/agent_workspace/session_1770980272542/agent_workspace/skills/deep-research-agent/scripts/init_research.py \
  --name "ai_medical_research" \
  --topic "AI医疗应用深度调研" \
  --template industry \
  --output ./output
```

生成的目录结构：

```
./output/
└── ai_medical_research/
    ├── report.md              # 报告文档（已copy模板）
    ├── research_data.json     # 结构化数据
    └── materials/             # 资料文件夹
        ├── raw/               # 原始资料
        ├── processed/         # 整理后的资料
        └── quotes/            # 引用片段
```

---

## Step 2: 逐章节调研与增量更新

### 2.1 开始第一章：行业概览

搜索关键词："AI医疗行业定义"、"AI医疗发展历程"、"AI医疗产业链"

**发现有价值的信息时，立即保存到资料文件夹：**

```python
# 保存原始资料
file_write(
    file_path="./output/ai_medical_research/materials/raw/market_size_2024.md",
    content="""## 全球AI医疗市场规模数据

来源: Frost & Sullivan Report 2024
URL: https://example.com/report

- 2023年全球AI医疗市场规模：150亿美元
- 2025年预测：450亿美元
- 年复合增长率：40%+
- 亚太地区增长最快，中国占35%份额
"""
)

# 保存关键引用
file_write(
    file_path="./output/ai_medical_research/materials/quotes/quote_001.md",
    content="""> "AI医疗市场正处于爆发期，医学影像识别是目前最成熟的应用领域，占比超过40%。"
> 
> —— Frost & Sullivan, Global AI in Healthcare Market Report 2024
"""
)
```

**章节内容足够丰富后，立即更新报告：**

```python
file_update(
    file_path="./output/ai_medical_research/report.md",
    search_pattern="### 1.1 行业定义",
    replacement="""### 1.1 行业定义

人工智能医疗（AI in Healthcare）是指将人工智能技术应用于医疗健康领域的总称。根据应用场景和技术类型，可分为以下几个主要类别：

**按应用场景分类：**
- **医学影像AI**: 利用计算机视觉技术辅助医生进行影像诊断，包括CT、MRI、X光、病理切片等
- **临床决策支持**: 基于知识图谱和机器学习提供诊断建议和治疗方案推荐
- **药物研发AI**: 应用AI加速靶点发现、分子设计、临床试验优化
- **智能健康管理**: 可穿戴设备数据分析、慢病管理、健康风险评估

**按技术类型分类：**
- **机器学习**: 监督学习、无监督学习、强化学习在医疗数据上的应用
- **深度学习**: CNN用于影像分析，RNN/LSTM用于时序数据分析
- **自然语言处理**: 电子病历分析、医学文献挖掘、智能问诊

[来源: Frost & Sullivan Healthcare AI Industry Report 2024]
"""
)

file_update(
    file_path="./output/ai_medical_research/report.md",
    search_pattern="### 1.2 发展历程",
    replacement="""### 1.2 发展历程

AI医疗的发展经历了三个主要阶段：

**第一阶段：规则驱动（1970s-2000s）**
- 基于专家系统的临床决策支持
- MYCIN系统（1976）是早期代表，用于血液感染诊断
- 局限性：知识获取瓶颈、规则维护困难

**第二阶段：数据驱动（2000s-2015）**
- 机器学习算法在医疗数据上的应用
- IBM Watson Health（2015）推出肿瘤治疗方案推荐
- 数据孤岛、标注成本高成为主要挑战

**第三阶段：深度学习（2015至今）**
- 2015年：深度学习在ImageNet的成功推动医学影像AI爆发
- 2017年：FDA批准首个AI医疗设备IDx-DR（糖尿病视网膜病变筛查）
- 2023年：大语言模型（LLM）在医疗领域应用兴起

[来源: Nature Medicine AI Review 2023]
"""
)
```

### 2.2 继续下一章：市场环境分析

搜索关键词："AI医疗政策环境"、"AI医疗监管"、"AI医疗市场规模预测"

**保存资料：**

```python
file_write(
    file_path="./output/ai_medical_research/materials/processed/policy_summary.md",
    content="""## AI医疗政策环境汇总

### 美国
- FDA已批准超过500个AI医疗设备
- 2021年发布AI/ML医疗器械指导原则
- 采用预认证（Pre-Cert）模式加速审批

### 中国
- NMPA已批准100+ AI医疗器械
- 2019年发布《人工智能医疗器械注册审查指导原则》
- 三类证审批严格，二类证相对宽松

### 欧盟
- CE认证要求符合MDR法规
- 强调临床证据和上市后监管
- GDPR对医疗数据使用有严格限制
"""
)
```

**更新报告：**

```python
file_update(
    file_path="./output/ai_medical_research/report.md",
    search_pattern="### 2.1 宏观环境（PEST）",
    replacement="""### 2.1 宏观环境（PEST）

**政策环境（Political）**
- 美国FDA采用预认证模式，已批准500+ AI医疗设备
- 中国NMPA发布AI医疗器械注册审查指导原则
- 欧盟MDR法规对AI医疗设备的临床证据要求严格
- 各国加速AI医疗审批流程，推动产业发展

**经济环境（Economic）**
- 全球医疗支出持续增长，2025年将达10万亿美元
- 医疗人力成本上升，AI替代需求强烈
- 疫情后医疗数字化投资大幅增加

**社会环境（Social）**
- 人口老龄化加剧医疗需求
- 患者对精准医疗期望提高
- 医生对AI辅助诊断接受度提升

**技术环境（Technological）**
- 大语言模型在医疗NLP领域突破
- 多模态AI融合影像、文本、基因数据
- 边缘计算实现实时诊断
"""
)
```

---

## Step 3: 持续迭代，逐章推进

按照大纲顺序，逐章节重复以下循环：

```
1. 搜索该章节相关信息
2. 发现价值信息 → 立即保存到materials/
3. 该章节信息足够 → 立即file_update报告
4. 进入下一章节
```

**章节完成检查清单：**
- [ ] 该章节已搜索足够信息（3-5个独立来源）
- [ ] materials/文件夹已保存关键资料
- [ ] report.md中该章节已用file_update填充
- [ ] 内容包含数据支撑和来源引用
- [ ] 提供了分析而不仅是事实罗列

---

## Step 4: 最终整理

所有章节完成后，进行最终整理：

```python
# 更新执行摘要（基于各章节内容总结）
file_update(
    file_path="./output/ai_medical_research/report.md",
    search_pattern="{3-5条核心发现 + 关键数据 + 建议}",
    replacement="""全球人工智能医疗市场正处于快速发展期，预计到2025年市场规模将达到450亿美元。医学影像识别、药物研发、智能诊断是当前最成熟的三大应用场景。

### 关键发现

- **市场规模**: 2023年全球AI医疗市场150亿美元，预计2025年达到450亿美元，CAGR超过40%
- **政策环境**: 美国FDA已批准500+ AI医疗设备，中国NMPA加速审批流程
- **技术趋势**: 大模型、多模态AI、边缘计算成为新方向
- **竞争格局**: 科技巨头、医疗AI独角兽、传统医疗企业三足鼎立
- **主要挑战**: 数据隐私、监管合规、临床验证成本高

### 核心建议

1. **关注药物研发AI赛道**: 技术成熟度高，市场需求大，ROI明确
2. **布局医学影像标准化**: 建立数据标准和质控体系是商业化关键
3. **重视监管合规**: FDA/NMPA审批经验成为核心竞争力
4. **投资边缘AI设备**: 满足数据隐私和实时性需求的新增长点"""
)

# 保存结构化数据
file_write(
    file_path="./output/ai_medical_research/research_data.json",
    content='''{
  "topic": "AI医疗应用深度调研",
  "created_at": "2024-01-15",
  "outline": {...},
  "key_findings": [
    {"chapter": "行业概览", "finding": "AI医疗进入深度学习阶段", "sources": [...]},
    {"chapter": "市场环境", "finding": "全球市场规模2025年达450亿美元", "sources": [...]}
  ],
  "sources": [...]
}'''
)
```

---

## 关键原则总结

1. **立即保存**：发现价值信息，第一时间保存到materials/
2. **逐章推进**：不要等所有信息收集完再写报告
3. **及时更新**：章节内容足够丰富，立即file_update
4. **资料分类**：raw/原始、processed/整理、quotes/引用
5. **来源追溯**：每个数据都要标注来源，方便核查
