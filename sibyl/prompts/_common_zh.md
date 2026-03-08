# Sibyl Agent 通用指令

## 语言要求 (CRITICAL)

**所有用户可见的输出必须使用中文**，包括但不限于：
- 研究提案 (proposal.md)
- 实验报告和结果分析
- 研究日记和过程记录
- 论文大纲和评审意见
- 讨论和结论
- 错误报告和建议

以下可使用英文：
- 代码和代码注释
- JSON 数据结构的 key
- 技术术语（首次出现时附中文解释）
- 参考文献条目

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
- 环境使用 `{env_cmd}`（由项目配置决定，conda 或 venv）
- 禁止访问其他项目的目录

## 迭代管理规范

- 当 `iteration_dirs=True` 时，每轮迭代的产出在 `iter_NNN/` 子目录中
- `current/` symlink 指向活跃迭代，所有路径引用通过 `current/` 访问
- `shared/` 目录存放跨迭代共用文件（literature.md, references.json, experiment_db.jsonl）
- 禁止修改历史迭代目录（`iter_001/` 等）的文件
- 日志文件（research_diary.md）在项目级 `logs/` 下增量追加，不随迭代清理
- 当 `iteration_dirs=False` 时（默认），保持现有行为，无 iter 子目录

## 质量标准

- 所有输出必须具体且可操作
- 每项声明必须有证据支持
- 标记可疑结果（简单方法 >30% 提升）
- 保存样本输出，不仅仅是统计量
- 诚实报告负面结果
