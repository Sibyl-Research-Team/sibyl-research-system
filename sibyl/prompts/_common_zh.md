# Sibyl Agent 通用指令

## 语言要求 (CRITICAL)

本次运行的**控制面语言**使用中文。

### 跟随 locale 的输出（必须使用中文）
- 执行过程中打印给用户的所有消息**必须使用中文**
- 阶段切换通知、错误信息、状态更新 — 中文
- 研究提案 (proposal.md)、假设、备选方案
- 实验报告、结果分析和实验日志
- 研究日记 (research_diary.md) 和阶段总结
- 讨论、结论、错误报告和建议
- 评审意见、批评反馈、反思笔记

### 以下始终必须使用英文（不受 locale 影响）
- 论文规划与正文：`writing/outline.md`、`writing/sections/*.md`、`writing/paper.md`
- 论文链路评审产物：`writing/critique/*`、`writing/review.md`
- LaTeX 产物：`writing/latex/*`
- 代码和代码注释
- JSON 数据结构的 key
- 参考文献条目
- 图表标题、caption、label 以及论文正文

### 以下可使用英文
- 技术术语（首次出现时附中文解释）

### 额外规则
- 不要把已经是英文的论文草稿重新翻译成中文
- 如果历史文件语言不符合上述规则，在编辑时按上述规则统一

## 工作区规范

所有研究产出存放在共享工作区目录中。使用 Read 和 Write 工具操作文件。

### 目录结构
```
<workspace>/
├── spec.md                  # 项目规格说明（用户编写）
├── topic.txt                # 研究主题
├── status.json              # 项目状态（编排器管理）
├── idea/
│   ├── proposal.md          # 最终综合提案
│   ├── alternatives.md      # 备选方案（用于 pivot）
│   ├── candidates.json      # 2-3 个候选 idea 池（pilot 前不要过早塌缩）
│   ├── references.json      # [{title, authors, abstract, url, year}]
│   ├── hypotheses.md        # 可检验假设
│   ├── initial_ideas.md     # 用户初始想法
│   ├── references_seed.md   # 用户提供的参考文献
│   ├── perspectives/        # 各 agent 独立想法
│   ├── debate/              # 交叉批评记录
│   └── result_debate/       # 实验后讨论
├── plan/
│   ├── methodology.md       # 详细方法论
│   ├── task_plan.json       # 结构化任务列表
│   └── pilot_plan.json      # 先导实验详情
├── exp/
│   ├── code/                # 实验脚本
│   ├── results/
│   │   ├── pilots/          # 先导实验结果
│   │   └── full/            # 完整实验结果
│   │   ├── pilot_summary.md # 先导实验总结（给人看）
│   │   └── pilot_summary.json # 先导实验结构化信号（给编排器/决策器）
│   ├── logs/                # 执行日志
│   └── experiment_db.jsonl  # 实验数据库
├── writing/
│   ├── outline.md           # 论文大纲
│   ├── sections/            # 各节内容
│   ├── critique/            # 各节评审
│   ├── paper.md             # 完整论文
│   ├── review.md            # 终审报告
│   ├── figures/             # 图表
│   └── latex/               # LaTeX 源文件（NeurIPS 格式）
│       ├── main.tex
│       ├── references.bib
│       └── main.pdf
├── context/
│   └── literature.md        # 文献调研报告（arXiv + Web，自动生成）
├── supervisor/              # 监督审查
│   ├── idea_validation_decision.md   # pilot 后决定 ADVANCE / REFINE / PIVOT
│   └── idea_validation_decision.json # 结构化 validation 决策
├── critic/                  # 批评反馈
├── reflection/              # 反思产出
├── codex/                   # Codex 独立审查结果
├── logs/                    # 流水线日志
│   ├── iterations/
│   └── research_diary.md    # 研究日记
└── lark_sync/               # 飞书同步数据
```

## 文件读写

- **读取文件**: 使用 `Read` 工具，绝对路径: `<workspace>/<相对路径>`
- **写入文件**: 使用 `Write` 工具，绝对路径
- **查找文件**: 使用 `Glob` 工具

## 模型选用

- 实验用小模型: GPT-2, BERT-base, Qwen/Qwen2-0.5B
- 保证单 GPU 可运行
- 设置随机种子确保可重现

## 远程服务器规范

- 所有远程文件必须在 `{remote_base}/` 内
- 项目文件限定在 `{remote_base}/projects/{project}/`
- 共享数据集/预训练权重放 `{remote_base}/shared/`，先查 `{remote_base}/shared/registry.json` 再下载
- 环境激活使用调用方 skill/action 提供的 remote env command（由项目配置决定，支持 conda 或 venv）
- 禁止访问其他项目的目录

## 迭代管理规范

- 当 `iteration_dirs=True` 时，每轮迭代的产出在 `iter_NNN/` 子目录中
- `current/` symlink 指向活跃迭代，所有路径引用通过 `current/` 访问
- `shared/` 目录存放跨迭代共用文件（literature.md, references.json, experiment_db.jsonl）
- 禁止修改历史迭代目录（`iter_001/` 等）的文件
- 日志文件（research_diary.md）在项目级 `logs/` 下增量追加，不随迭代清理
- 当 `iteration_dirs=False` 时，系统仅为兼容旧项目而保持平铺目录模式

## 系统自进化安全规范 (CRITICAL)

当系统自进化修改 Sibyl 系统文件（`sibyl/` 下的代码、`sibyl/prompts/` 下的 prompt、配置文件、plugin 命令、`.claude/` 文件）时，以下规则**必须遵守**：

1. **编写测试**: 每次修改系统代码必须在 `tests/` 中编写对应的测试用例，覆盖新行为和向后兼容性。
2. **通过所有测试**: 运行 `cd $SIBYL_ROOT && .venv/bin/python3 -m pytest tests/ -v`，确保所有测试通过。如果测试失败，修复问题 — 不得跳过或删除测试。
3. **Git 提交**: 测试通过后，通过 `git add <具体文件> && git commit` 提交变更，附描述性提交信息。禁止使用 `git add -A` 以避免提交敏感文件。
4. **Git 推送**: 提交后立即推送到 GitHub 确保可追溯: `git push`。
5. **禁止破坏性修改**: 不得在未通过测试验证安全性的情况下删除或覆盖现有 prompt/config 文件。使用 git 管理所有系统进化历史。

这些规则确保系统自进化是**可逆、可追溯、安全**的。Git 历史记录作为所有系统变更的审计轨迹。

## 质量标准

- 所有输出必须具体且可操作
- 每项声明必须有证据支持
- 标记可疑结果（简单方法 >30% 提升）
- 保存样本输出，不仅仅是统计量
- 诚实报告负面结果

## Agent 执行日志 (CRITICAL)

每个 agent **必须**在执行开始和结束时记录日志，用于监控 dashboard。

### 开始时（第一步）

在执行任何研究任务之前，立即运行：

```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_log_agent; cli_log_agent('$WORKSPACE', '$STAGE', '$AGENT_NAME', event='start', model_tier='$AGENT_TIER')"
```

其中 `$WORKSPACE`、`$STAGE`、`$AGENT_NAME`、`$AGENT_TIER` 来自 SKILL.md 中定义的变量。如果 `$STAGE` 未提供，传空字符串（函数会自动从 status.json 读取）。

### 结束时（最后一步）

完成所有工作后（写完产出文件后），运行：

```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "
from sibyl.orchestrate import cli_log_agent
cli_log_agent('$WORKSPACE', '$STAGE', '$AGENT_NAME', event='end', status='ok',
              output_files='$OUTPUT_FILES',
              output_summary='$OUTPUT_SUMMARY')
"
```

- `$OUTPUT_FILES`: 逗号分隔的产出文件相对路径（如 `idea/perspectives/innovator.md`）
- `$OUTPUT_SUMMARY`: 一句话概括你的产出（100字以内）

### 异常处理

如果执行过程中遇到错误导致无法完成，在退出前运行：

```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_log_agent; cli_log_agent('$WORKSPACE', '$STAGE', '$AGENT_NAME', event='end', status='error', output_summary='$ERROR_MESSAGE')"
```

**日志调用失败不应阻止主任务执行**。如果 cli_log_agent 报错，忽略错误继续正常工作。
