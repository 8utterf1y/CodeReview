# SpecDiff 重新构思：从“规范扫描”到“变更取证审查”

## 一句话定义

SpecDiff 不再试图回答“整个仓库是否符合整份规范”，而是围绕一个明确的审查任务，将需求转成可验证主张，从变更代码出发沿语义关系网取证，最终回答：

> 这次变更在指定范围内，是否满足指定需求？结论由哪些可复核的证据支持？还有哪些无法确认？

这个定义同时覆盖三种使用方式：

- 查一次 commit / PR 是否符合一份需求文档。
- 只查某些文件、符号、diff hunk 或文档章节。
- 在没有 diff 时，对指定模块做定向一致性审查。

## 为什么要换一个中心

现有思路的中心是“需求条目”：先拆规范，再为每条需求全库搜索。这在 RFC 清单审计里勉强成立，但在日常代码审查中会产生四个根本问题：

1. 它不知道什么是“这次变更造成的”，容易报出大量历史问题。
2. 它把文本命中当成调查起点，模型容易看到孤立片段，却没看到真实入口、调用者、守卫条件和副作用。
3. 它默认文档已经是规范化义务清单，不适合普通的产品需求、设计说明和接口约定。
4. 它把“找到候选代码”和“证明行为成立”混在一起，从而让缺失、误报和工具能力不足难以区分。

新工具的中心应当是“审查案件（Review Case）”。一个案件同时锁定代码版本、变更范围、文档范围、审查模式和证据预算。需求和代码都是案件的证据源，而不是工作流本身。

## 用户如何发起审查

用户只需提供四类信息，其中只有仓库和文档是必需的：

```yaml
repository: /path/to/repo
requirements:
  documents:
    - docs/payment-retry.md
  sections: ["Retry policy", "Failure handling"]   # 可选
scope:
  base: main                                          # 可选
  head: HEAD                                          # 可选
  paths: [src/payment/**]                             # 可选
  symbols: [retryPayment]                             # 可选
mode: auto                                            # fast | deep | auto
```

范围规则要简单且可预期：

- 有 `base/head` 时，diff hunk 是最初的变更种子。
- 指定 `paths/symbols` 时，它们与 diff 取交集；没有 diff 时它们自身就是种子。
- 指定文档章节时，不对未选章节的需求下结论。
- 调用链扩展可以越过文件范围取证，但不会把范围外的历史问题自动归因给本次变更。

## 整体工作流

```text
建立/更新索引
       ↓
锁定 Review Case（版本、diff、文档、范围）
       ↓
文档理解：生成可验证主张
       ↓
将变更种子与主张锚点对齐
       ↓
按预算双向扩展语义关系网
       ↓
生成 Context Pack（不是散乱片段）
       ↓
  L3 快审  或  L4 深审
       ↓
去重、归因、定级、输出人类可读报告
```

系统不以“搜索了多少文件”衡量完成度，而以“每个主张的证据缺口是否已被支持、反证或明确标记为不可判定”衡量。

## 第一层：将代码建成可取证的语义索引

### 索引不只是符号表

Tree-sitter 负责快速、多语言、可增量的语法事实提取。SQLite 中至少保存五类节点：

- `file`：文件、语言、hash、所属模块、生产/测试/生成角色。
- `symbol`：函数、方法、类、字段、常量、路由处理器等，带完整范围和稳定 ID。
- `site`：调用点、读写点、分支守卫、抛错、返回、注册、配置读取等可引用位置。
- `edge`：节点间关系，不只有 `calls`，还应包括 `imports`、`reads`、`writes`、`overrides`、`implements`、`registers`、`routes_to`、`emits`、`handles`、`tested_by`。
- `revision_fact`：某条事实属于哪个 revision，是新增、删除还是变更。

每条关系都必须有：

```text
source, target, edge_type, location, resolver,
confidence, resolution_status, revision
```

`resolution_status` 至少区分 `exact / probable / ambiguous / unresolved`。Tree-sitter 能证明“这里有一个名为 X 的调用”，却不总能证明它调的就是某个 X。索引必须保留这个不确定性，不能在建图时偷偷选第一个同名符号。

### 精度分层

索引应当允许多个 backend 共存：

1. Tree-sitter 是基础层，保证快速和多语言覆盖。
2. 导入/命名空间/接收者类型规则用于收窄候选符号。
3. 如果仓库提供 LSP、SCIP、clangd 或语言编译器索引，用其覆盖或增强对应边。
4. 任何高精度 backend 不可用时，系统仍可运行，但结论信心必须受索引精度上限约束。

### 增量更新

“更新索引”不应每次重建整库：

1. 比较 path + content hash，得到 added / modified / deleted 文件。
2. 在一个 SQLite transaction 中删除受影响文件的旧事实，并写入新事实。
3. 重新解析指向或来自变更符号的边，不只是变更文件内的边。
4. 提交新的 `index_snapshot`；任何 Review Case 始终绑定一个不可变 snapshot。
5. 更新失败时回滚，不允许模型使用半新半旧的图。

稳定 ID 应来自 `repo + language + qualified_name + normalized_signature + file identity`，不应来自每次扫描顺序。否则无法复用缓存，也无法在 base/head 之间对齐符号。

## 第二层：让普通需求文档变成可验证主张

不再要求文档使用 RFC 式 `MUST/SHOULD`，也不应按单行关键词抽取需求。文档解析单元应是“章节块”，模型同时看标题、正文、列表、表格、示例和例外。

文档先被组织成一个简单的 Requirement Map：

```text
用户目标
  └─ 场景
      └─ 可验证主张
          ├─ 触发条件
          ├─ 预期行为
          ├─ 禁止行为
          ├─ 异常/边界
          └─ 可观察结果
```

每个主张（Claim）保留文档原文和位置，同时生成：

- 一句可判定陈述。
- 适用条件、例外和未明确之处。
- 支持该主张需要看到的证据。
- 否定该主张会出现的反证。
- 用于和代码对齐的概念、领域词、可能的符号和组件锚点。

如果文档只是背景、愿景、非功能性口号，或缺少可观察行为，应标记为 `not_verifiable`，而不是强行生成“代码缺失”。

## 第三层：用有预算的双向扩展取代朴素 BFS

“对目标沿调用链双向 BFS”是正确方向，但不应做成“固定两层、所有边等权、全部代码塞进提示词”。更合适的是多源、加权、按证据缺口扩展。

### 两类起点

- 变更种子：diff hunk 所在符号、新增/删除边、变更的配置和测试。
- 主张锚点：由文档概念对齐到的符号、组件、路由、配置项和测试。

优先寻找两类起点之间的连通路径。它比单纯从某个关键词向外扩展更能回答“这次变更和这条需求到底有没有关系”。

### 扩展优先级

边的优先级由下列因素共同决定：

```text
score = claim_relevance
      + change_proximity
      + edge_semantic_value
      + production_role
      + resolver_confidence
      - fanout_penalty
      - ambiguity_penalty
      - token_cost
```

具体扩展方向取决于主张类型：

- “是否可达”：优先向上找入口、注册者和调用者。
- “是否产生结果”：优先向下找副作用、写操作、事件和错误处理。
- “是否被保护”：同时向上找绕过路径，向下找受保护操作。
- “配置是否生效”：从解析/默认值向下追到真正的运行时读取和分支。

### 停止条件

扩展不以固定深度为唯一限制，而由预算和证据完整性共同控制：

- 已找到从入口、变更点到可观察结果的完整路径。
- 已找到能直接否定主张的反证。
- 新节点的边际信息收益过低。
- 达到节点、源码行或 token 预算。
- 前方只剩模糊/未解析边；此时记录能力缺口，而不假装已证明不可达。

## Context Pack：给模型一个案卷，不是一堆搜索结果

每个 Claim 生成一个有结构的 Context Pack：

```yaml
case: 仓库、base/head、审查范围
claim: 可判定主张、条件、例外、文档原文
change_summary: 变更符号、边和 hunk
paths:
  - 入口 -> 变更点 -> 行为 -> 可观察结果
source_slices: 完整符号或有守卫语义的最小片段
counterevidence: 绕过路径、相反分支、TODO、未处理路径
tests: 相关测试及其覆盖的主张
provenance: 每个事实的文件、行、revision、解析精度
gaps: 未解析边、未检索方向、被预算截断的路径
```

源码片段应优先以完整符号为边界，并包含影响语义的装饰器、注解、函数签名、前置守卫和关键返回。只在函数过大时才切窗口，并显式说明省略了什么。

Context Pack 是可缓存的。其 cache key 由 `index_snapshot + diff + claim + expansion_policy` 组成。L3 和 L4 可复用同一个初始 Pack，L4 仅在取证阶段通过工具扩展它。

## L3：单次推理快审

L3 的目标是在一次模型调用中给出高召回的初筛结果，适用于 PR 阻塞前的快速反馈。

输入是预先组装好的 Context Pack；模型不自由浏览整库，也不在本阶段追加无界搜索。它对每个 Claim 输出：

- `consistent`：现有证据支持，且没有直接反证。
- `inconsistent`：有直接代码证据显示缺失、相反行为或只实现了部分条件。
- `uncertain`：证据包无法支持可靠结论。
- `not_applicable`：主张与本次审查范围无可解释的关系。

L3 的用户输出是“候选不一致清单”，不应伪装成终局审计结论。对于安全、数据丢失、权限绕过等高风险主张，即使 L3 判定一致，`auto` 模式也应升级到 L4。

## L4：多阶段深审

L4 不是“让更大模型再想一遍”，而是一个有状态、有证据门槛、可按需使用工具的审查协议。所有阶段共享一个结构化 Case File，但每个阶段有不同职责。

### 1. 初判

基于 Claim 和初始 Context Pack，产生候选结论。每个结论必须拆成：

- 需求在什么条件下要求什么。
- 代码实际做了什么。
- 两者之间的差异。
- 当前证据支持度和归因判断。
- 尚未证明的关键前提。

### 2. 质疑

质疑者不重做初判，而是尽量推翻它。对每个候选问题提出具体反问：

- 是否误解了文档的适用条件或例外？
- 这段代码是否真在生产路径上可达？
- 是否存在别名、另一实现、生成代码、外部组件或配置开关？
- 所引证据是导航线索，还是能证明行为的精确源码？
- 问题是本次变更引入的，还是早已存在？
- 所谓“缺失”是已搜索后的负面结论，还是索引/预算不足？

产物不是新结论，而是一组有优先级的 `Evidence Gap`。

### 3. 取证

取证者只根据 Evidence Gap 调用受控工具，例如：

- `expand_graph(symbol, direction, edge_types, budget)`
- `find_paths(from, to, constraints)`
- `read_symbol(symbol_id, revision)`
- `read_diff(symbol_id)`
- `find_callers/callees/references`
- `find_alternate_implementations(concept)`
- `find_tests(symbol_or_claim)`
- `search_text(pattern, scope)`
- `compare_base_head(symbol_or_path)`

工具返回的每条证据都进入 Case File，并有唯一 evidence ID。模型不能引用未进入 Case File 的路径、行号或调用关系。

取证循环应是受限的：一次处理最高优先级的证据缺口，然后重新评估是否足以收敛；而不是一次性发起大量关键词搜索。

### 4. 收敛

收敛者综合初判、质疑和新证据，完成：

1. 将证据不足的问题降为 `uncertain`，不保留虚假确定性。
2. 删除已被反证推翻的误报。
3. 将同一根因造成的多个 Claim 违反合并成一个问题，并列出受影响主张。
4. 判定严重度、可置信度和归因类型。
5. 为每个结论生成最短可复核证据链。

L4 只有在下列门槛满足时才能输出 `inconsistent`：

- 文档主张本身可判定。
- 代码证据来自精确源码或可信语义关系，不是单纯文本命中。
- 已检查关键替代路径或记录为工具不可达。
- 可以解释它与审查范围的关系。
- 如果结论是“缺失”，必须有搜索范围、查询轨迹和索引覆盖说明。

## L3/L4 的路由策略

`fast` 总是走 L3，`deep` 总是走 L4，`auto` 先进行廉价评估，再对部分 Claim 升级。升级条件包括：

- L3 给出 `inconsistent` 但证据链不完整。
- L3 给出 `uncertain`，且该 Claim 和变更高度相关。
- 高风险主张：安全、权限、金钱、数据丢失、兼容性。
- 修改了公共 API、调用图枢纽、并发/事务逻辑或默认配置。
- 变更删除了边、守卫、错误处理或测试。
- 索引中存在同名候选、动态调用或大扇出。

不必对整个 Review Case 统一使用 L4。正确的粒度是 Claim/Issue：大部分低风险主张留在 L3，只把有争议或高风险的部分升级。

## 变更审查必须处理“归因”

仅在 HEAD 上看到不一致，不等于这次 commit 引入了它。每个最终问题需要标记：

- `introduced`：base 满足或不可达，head 出现明确违反。
- `exposed`：问题在 base 已存在，但新变更让该路径可达、默认开启或影响扩大。
- `pre_existing`：已存在且本次变更没有实质改变它。
- `unattributed`：只能证明 HEAD 不一致，但 base 无法解析或证据不足。

默认的 PR 报告仅将 `introduced` 和 `exposed` 放入阻断性问题。`pre_existing` 可以放入“附带发现”，或由用户选择不显示。

## 输出要像代码审查，不像审计数据库

默认报告先服务人，JSON/SARIF 是附加产物。人类可读报告结构建议为：

1. **审查结果**：通过、有风险或无法完全判定。
2. **需要处理的问题**：按严重度排序。
3. **每个问题**：需求说了什么、代码做了什么、为什么不一致、受影响路径、归因、证据链、建议处理方向。
4. **未确定项**：说清缺什么证据，而不用低信心问题混入正式清单。
5. **审查范围与覆盖**：查了哪些 commit、文件、章节和 Claim，哪些被排除。

一个问题的表达示例：

```text
重试次数可以超过需求允许的上限

需求：支付失败后最多重试 3 次，超过后进入人工处理。
实现：retryPayment 把配置值直接传给循环，没有上限截断；默认配置为 5。
影响：生产入口 processFailedPayment 可到达该路径。
归因：introduced，本次变更删除了 min(configured, 3) 守卫。
证据：文档§Retry policy → diff → retryPayment → processFailedPayment。
级别：high，置信度 0.96。
```

## 建议的核心数据模型

SQLite 可以分为三组表，避免把仓库事实、审查状态和模型结论混在一起。

### 仓库事实

```text
repositories, index_snapshots, files, symbols, sites,
edges, edge_candidates, build_units, revisions, change_facts
```

### 文档与审查范围

```text
documents, document_blocks, claims, claim_sources,
review_cases, review_scopes, case_claims, change_seeds
```

### 证据与推理

```text
context_packs, evidence, evidence_paths, evidence_gaps,
stage_runs, candidate_findings, challenges, final_findings
```

模型输出不能直接改写仓库事实。只有索引器和受控工具能写入事实表；模型只写候选结论、证据缺口和最终判断。

## 模块边界

```text
Indexer
  负责代码事实、版本快照和增量更新

Scope Resolver
  负责 git diff、路径/符号过滤、变更种子和 base/head 对齐

Requirement Interpreter
  负责易读文档的结构化、Claim 和可验证性

Evidence Retriever
  负责概念对齐、加权扩展、源码切片和 Context Pack

Review Orchestrator
  负责 L3/L4 路由、阶段状态、预算和重试

Evidence Tools
  负责在 L4 中按证据缺口安全地补数

Converger
  负责去误报、合并、归因、定级和最终报告
```

Orchestrator 应保持“薄”：它只执行状态机，不自己解释需求或搜代码。但状态机不应围绕“每条需求调度一个 agent”，而应围绕 Claim 的证据状态与升级条件。

## 对当前实现的具体调整

当前代码中可以保留的部分：

- SQLite 代码事实库和 Tree-sitter 语言包。
- 精确 source evidence ID 和查询轨迹。
- 薄 Orchestrator 与 runtime 控制产物的思路。
- `uncertain` 而非在工具不足时猜测的证据原则。
- 以精确源码作为行为结论依据的要求。

需要替换或重写的部分：

- 将每次删库重建改为 snapshot + incremental update。
- 将顺序编号的符号 ID 改为稳定 ID。
- 将“同名且同 component 的第一个符号”解析改为保留候选集和歧义。
- 将只有 callers/callees 的候选图扩展为多关系语义图。
- 将全库 requirement batch 改为 Review Case 和 Claim-centered Case File。
- 将按单行关键词识别规范改为章节级需求理解。
- 新增 diff-aware scope、base/head 对比和问题归因。
- 将一次 Investigator 判断拆成 L3 快审和 L4 的初判/质疑/取证/收敛。
- 将 JSON/SARIF 为主的产物改为人类可读审查报告为主。

## 实施路线

### 阶段 A：先做好“变更快审”

目标是尽快证明新的产品形态，不急于支持所有语义边。

- 新增 Review Case、base/head、路径/符号/文档章节范围。
- 从 diff 定位变更符号。
- 使用现有符号/调用候选图做受限的双向扩展。
- 实现章节级 Claim 抽取和 Context Pack。
- 实现 L3 单次推理和 Markdown 报告。

成功标准：对一个小型 PR，用户可在数分钟内看到与 diff 有明确关系的候选不一致，且每条都能点回需求和源码。

### 阶段 B：加入 L4 取证闭环

- 实现 Case File、Evidence Gap 和受控取证工具。
- 实现初判、质疑、取证、收敛的状态机。
- 加入 Claim 级自动升级和预算控制。
- 加入误报剔除、根因合并和证据门槛。

### 阶段 C：提高图精度和归因能力

- 索引增量化与稳定 ID。
- 引入多 backend 符号解析，扩展读写、注册、路由、实现关系等边。
- 保存 base/head 事实差异，实现 introduced/exposed/pre-existing 归因。
- 根据仓库和语言特性校准扩展权重。

## 评估方法

不应只测“最终找到了多少问题”。至少要分层评估：

- **索引层**：符号召回率、边解析精度、歧义保留率、增量更新耗时。
- **检索层**：金标证据链的命中率、无关 token 占比、在同等预算下相对关键词搜索的收益。
- **判断层**：问题 precision/recall、`uncertain` 校准度、归因准确率、严重度一致性。
- **L4 价值**：相对 L3 剔除的误报数、补回的真问题数、每个收敛问题的工具调用和 token 成本。
- **用户价值**：从发起到首条有用反馈的时间、开发者接受/驳回率、证据复核耗时。

基准集应围绕“diff + 需求章节 + 已知结论”构建，而不是围绕整仓 RFC 覆盖率构建。

## 最重要的产品取舍

1. **审查目标优先于全库完备性。** 先回答用户指定的 diff 和需求，不要默认做一次无边界审计。
2. **证据可复核性优先于模型叙事完整性。** 宁可输出不确定，也不用一段流畅推理填补未解析的调用链。
3. **图用于导航和组织证据，不自动等于证明。** 候选边必须带精度，最终行为结论尽可能回到精确源码。
4. **L3 和 L4 是两种审查合约，不只是两个模型名称。** L3 追求快速初筛，L4 追求经质疑和补证后的可信收敛。
5. **不一致和本次变更引入的不一致是两件事。** 如果不做 base/head 归因，工具就不适合用于真实 PR 审查。

这样重构后，SpecDiff 的核心不再是“一个能搜代码的审计 Agent”，而是“一个能够为变更构建证据、组织质疑并收敛结论的审查系统”。
