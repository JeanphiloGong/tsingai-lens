# 材料学视角优化建议与功能需求（Materials Research Mentor）

## 适用范围与目标
- 材料体系：复合材料优先，但设计为通用框架。
- 目标性质：力学、热学、耐久性优先，但保留可扩展性。
- 当前痛点：文献阅读效率低（10–100 篇，中英混合，英文为主）。

## 诊断结论（问题链条）
1) **证据链断裂**：论文结论与实验条件、表征证据未系统关联，难以快速判断可信度与可比性。
2) **比较维度缺失**：材料体系、处理工艺、测试条件未结构化，难以横向比较。
3) **实验可复现性信息散落**：样品制备历史、批次、仪器校准信息缺失或不可追溯。
4) **知识图谱未服务实验设计**：图谱偏“概念网络”，缺“工艺—微观结构—性能—条件”因果链。

## 核心优化方向（按材料学主线）
### A. 以“结构—加工—性能—使用”构建图谱骨架
**优化目标**：把文献解析结果组织成可做实验决策的因果链。
**需求**：在实体/关系抽取中明确 4 类核心节点：
- 材料/体系（composition, matrix, reinforcement）
- 工艺/处理（processing, temperature, rate, environment）
- 微观结构（phase, grain size, interface, porosity）
- 性能/指标（mechanical, thermal, durability + units）

### B. 引入“证据强度”与“测量假设”标签
**优化目标**：快速判断结论可信度。
**需求**：
- 每条核心结论必须连接到至少一个证据源（图/表/方法段落）。
- 对关键测量（XRD/SEM/TEM/XPS/Raman 等）标注方法假设与局限。
- 支持“多方法交叉验证”的标记（如 SEM+XRD）。

### C. 强制记录对照与基线
**优化目标**：避免“不可比较”的结果被误用。
**需求**：
- 解析并结构化对照样（baseline/control）。
- 标注实验条件差异：温度/气氛/加载速率/样品尺寸。
- 输出“不可比告警”：缺失单位或条件时标红。

### D. 文献阅读优先级与抽取顺序优化
**优化目标**：先抓住“可用信息”，再细读。
**需求**：
- 自动生成“阅读骨架”：材料体系 → 工艺 → 表征 → 指标 → 结论。
- 生成论文 Q–C–E（Question–Claim–Evidence）卡片。
- 支持按目标性质（力学/热学/耐久性）过滤阅读清单。

## 功能需求清单（MVP+）
### 1) 文献阅读加速（最高优先级）
- 论文自动拆分：摘要、方法、结果、讨论、图表说明。
- 自动抽取材料体系/工艺/测试条件/关键指标。
- 生成 Q–C–E 卡片，链接原文证据。
- 中英文混合处理：统一单位、术语与缩写表。

### 2) 结构化对比视图
- 论文对比表：体系、工艺、微观结构、性能、条件、基线。
- 支持按目标性质过滤（力学/热学/耐久性）。
- 提供“可比性评分”（基于条件一致性与证据完整度）。

### 3) 实验设计辅助（基础版）
- 根据图谱输出“实验候选变量清单”（工艺参数、微观结构因子）。
- 输出推荐的对照与复现策略。
- 强制提示不确定性与假设（标注“待验证”）。

### 4) 知识图谱可用性增强
- 图谱节点增加“材料—工艺—结构—性能”标签。
- 支持按社区导出子图（对应特定主题或体系）。
- GraphML 导出附带社区与类别字段（方便 Gephi 着色）。

## 数据与元数据要求
必须字段（最低可用）：
- 材料体系与组成（composition、matrix、reinforcement）
- 工艺参数（temperature、time、atmosphere、rate）
- 关键微观结构（phase、grain size、interface）
- 性能指标（值、单位、测试条件）
- 对照基线与样品批次

建议字段：
- 仪器型号与校准信息
- 样品制备批次与处理历史
- 不确定性与误差条

## 面向复合材料的专项扩展（可选）
- 复合材料特征字段：纤维体积分数、界面改性、层合结构、取向分布。
- 界面相关表征优先级：SEM/TEM/XPS 证据强度权重提高。
- 性能关联：力学（强度/韧性/疲劳）、热学（导热/热稳定性）、耐久性（老化/腐蚀）。

## 风险与假设
- 假设/待验证：文献可提取到清晰的工艺参数与测试条件。
- 假设/待验证：图/表和方法段能稳定解析与链接。
- 风险：跨语言术语对齐可能导致映射错误。
- 风险：微观结构描述难以结构化，需要专家复核。

## 建议落地节奏（与当前系统结合）
1) **立即可做**：在现有索引流程中补充结构化抽取字段与 Q–C–E 卡片。
2) **短期**：增加对比表与“可比性评分”逻辑。
3) **中期**：实验设计辅助与证据强度标注体系。
4) **长期**：自动实验方案生成 + 实验闭环验证。

## 可执行需求列表（含优先级与验收标准）
说明：验收指标为目标值，需结合实际样本校准（假设/待验证）。

| ID | 需求 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| R1 | 论文自动拆分为摘要/方法/结果/讨论/图表说明 | P0 | ≥90% 论文识别出主要段落并可定位原文位置（待验证） |
| R2 | Q–C–E 自动抽取（Question/Claim/Evidence） | P0 | 每篇论文至少输出 1 条 Q–C–E，且 Claim 有 Evidence 关联（待验证） |
| R3 | 条件与单位结构化（温度/气氛/速率/尺寸/单位） | P0 | ≥80% 性能数据附带单位与测试条件（待验证） |
| R4 | 对照与基线识别 | P0 | ≥70% 论文能标出对照样或基线条件（待验证） |
| R5 | 中英文术语与单位对齐 | P1 | 术语映射命中率 ≥85%，单位可转换到统一标准（待验证） |
| R6 | 结构化对比表视图 | P1 | 支持按材料体系/工艺/性能筛选并导出对比表 |
| R7 | 图谱导出增强（社区/类别字段） | P1 | GraphML 包含 community/type 字段，可直接在 Gephi 上色 |
| R8 | 证据强度标注 | P1 | Evidence 标注方法类型与交叉验证标记（单/多方法） |
| R9 | 文献列表状态与处理追踪 | P2 | 每篇文献有处理状态、失败原因与重试入口 |
| R10 | 增量更新索引 | P2 | 新增文献不影响旧索引，生成增量日志 |
| R11 | 数据 schema 校验 | P2 | 输出数据通过必填字段校验并生成缺失统计 |

## Q–C–E 抽取字段
### Paper 元信息
- paper_id、title、authors、year、venue、doi、language
- material_system（体系/类别）

### Question
- research_question（问题陈述）
- hypothesis（假设，可为空）
- target_properties（目标性能：力学/热学/耐久性/其他）

### Claim
- claim_text（结论语句）
- claim_type（性能提升/机理解释/工艺优化/结构特征）
- effect_size（提升幅度或趋势，可为空）
- comparison_baseline（对照条件/基线）

### Evidence
- evidence_type（figure/table/method/paragraph）
- evidence_id（图表编号或段落定位）
- measurement_method（XRD/SEM/TEM/XPS/Raman/热分析/力学测试等）
- test_conditions（温度/气氛/速率/尺寸/载荷等）
- sample_info（样品制备与批次）
- uncertainty（误差/置信区间/重复次数）

### Validity
- evidence_strength（单方法/多方法）
- limitations（方法假设与局限）
- reproducibility_flag（是否跨批次复现）

## 论文阅读模板（单篇）
```
【Paper】
Title:
DOI:
Year/Venue:
Language:

【System】
Material system:
Composition:
Processing summary:
Microstructure summary:

【Question】
Research question:
Hypothesis:
Target properties:

【Claims】
1) Claim:
   Baseline:
   Effect size:
   Evidence (figure/table/method):
   Measurement:
   Conditions:
   Uncertainty:
   Limitations:

【Notes】
Key comparisons:
Missing data:
Potential follow-up:
```

## 材料数据 schema 草案（字段/单位/缺失处理）
### 数据结构（建议）
- paper（论文元数据）
- sample（材料体系与制备信息）
- process（工艺参数）
- microstructure（微观结构）
- measurement（测试与性能）
- claim（Q–C–E 结构化结论）

### 字段示例（简化版）
```
paper_id, title, year, doi, language
sample_id, material_system, composition, matrix, reinforcement
process_id, temperature_K, time_s, atmosphere, rate
micro_id, phase, grain_size_nm, porosity_pct, interface_desc
measure_id, property_name, value, unit, test_temperature_K, test_rate
claim_id, claim_text, evidence_id, evidence_type, confidence_level
```

### 单位规范（建议）
- 温度：K（如原文为 °C，转换并保留原始值）
- 时间：s（原文保留，转换为 s）
- 强度：MPa，弹性模量：GPa
- 热导率：W/(m·K)，热膨胀：1/K
- 寿命/耐久性：循环次数、小时（统一单位并记录条件）

### 缺失处理规则
- unknown：未知或无法判断
- not_reported：论文未报告
- not_applicable：不适用
- estimated：推断值（需标注来源）
- range：区间值（记录上下界）
