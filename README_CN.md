<p align="center">
  <img src="image/icon.jpg" width="200" alt="Sibyl Research System">
</p>

# Sibyl Research System（西比拉研究系统）

**全自主 AI 科研系统，具备自我进化能力**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 受 [The AI Scientist](https://github.com/SakanaAI/AI-Scientist)、[FARS](https://analemma.ai/blog/introducing-fars/) 和 [AutoResearch](https://github.com/karpathy/autoresearch) 等先驱工作的启发，Sibyl 在此基础上更进一步，原生构建于 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 之上，充分利用其 Agent 生态——Skills、Plugins、MCP Servers 和多 Agent 团队。

[English](README.md)

Sibyl 是一个**全自动科学发现系统**，能自主驱动从文献调研到论文投稿的完整 ML 研究流程。它不是辅助人类研究者的工具，而是一个**自主运转的研究组织**：20+ 个专业化 AI Agent 在辩论中碰撞想法、设计并执行 GPU 实验、撰写论文、严格自我审查——全程无需人工干预。

Sibyl 真正的独特之处在于其**双循环架构**：

- **内循环 — 研究迭代**：每个项目在各个维度上自动迭代——根据实验结果修正假设、重新规划实验、改写论文、在需要时转向备选想法——直到质量达到发表标准。
- **外循环 — 系统自进化**：Sibyl 从研究过程本身中学习。每轮迭代结束后，系统自动从 8 个维度分类问题，追踪哪些改进措施真正有效，并自动更新 Agent Prompt、调度策略和架构模式。**运行你研究的系统，本身也在不断进化。**

### 为什么选择 Sibyl？

- **全维度自主迭代** — 不只是"跑实验、写论文"。研究的每个方面都在迭代中自动优化：想法通过多 Agent 辩论不断打磨，实验通过追加 baseline 和 ablation 不断完善，论文在 6 Agent 交叉评审下不断修订，资源利用通过 GPU 调度反馈持续优化。质量门控决定何时停止或转向——无需人工介入。
- **自进化系统** — 大多数 AI 研究工具是静态的——每次运行方式相同。Sibyl 会进化。它从每次研究迭代中提取经验（问题、成功模式、效率指标），评估其有效性，并将验证有效的改进自动注入 Agent Prompt。无效经验被自动降权。跨项目积累的知识让系统拥有「机构记忆」——每个项目都让所有未来项目受益。
- **Claude Code 原生架构** — 不是 API 调用的封装。直接构建在 Claude Code 架构上（fork skills、agent teams、MCP tools），天然继承其完整生态：SSH 远程执行、多模型协作（Claude + GPT-5.4 交叉审查）、飞书云同步等。

---

## 快速上手

### 推荐：让 Claude 自动配置

最快的上手方式是让 Claude Code 帮你完成全部配置。克隆仓库，在 Claude Code 中打开，然后一句话搞定：

```bash
git clone https://github.com/Sibyl-Research/sibyl-research-system.git
cd sibyl-research-system
claude --plugin-dir ./plugin
```

然后告诉 Claude：

> **"帮我配置 Sibyl Research System，读取 docs/setup-guide.md 然后自动配置所有环境。"**

Claude 会自动检测你的环境、安装依赖、配置 MCP 服务器、创建配置文件，只在检测不到的信息（GPU 服务器 IP、用户名等）时询问你。[配置指南](docs/setup-guide.md)是一份专为 Claude 设计的分步检查清单。

### 手动配置

<details>
<summary>点击展开手动配置步骤</summary>

#### 环境要求

- Python 3.12+、Node.js 18+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)
- 可 SSH 访问的 GPU 服务器
- `ANTHROPIC_API_KEY` 环境变量
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` 环境变量

#### 1. 安装

```bash
git clone https://github.com/Sibyl-Research/sibyl-research-system.git
cd sibyl-research-system
chmod +x setup.sh && ./setup.sh    # 交互式：创建 venv、安装依赖、配置 MCP
```

#### 2. 配置 MCP 服务器

需要两个 MCP 服务器。`setup.sh` 会交互式配置，也可手动添加到 `~/.mcp.json`：

```json
{
  "mcpServers": {
    "ssh-mcp-server": {
      "command": "npx",
      "args": ["-y", "@fangjunjie/ssh-mcp-server",
               "--host", "你的GPU服务器IP", "--port", "22",
               "--username", "你的用户名",
               "--privateKey", "~/.ssh/id_ed25519"]
    },
    "arxiv-mcp-server": {
      "command": "python",
      "args": ["-m", "arxiv_mcp_server"]
    }
  }
}
```

> 服务器名称必须完全一致：`"ssh-mcp-server"` 和 `"arxiv-mcp-server"`。

#### 3. 配置 GPU 服务器

在项目根目录创建 `config.yaml`（不提交到 Git）：

```yaml
ssh_server: "default"
remote_base: "/home/user/sibyl_system"
max_gpus: 4
language: zh                       # 中文模式
```

#### 4. 运行

```bash
claude --plugin-dir ./plugin

# 在 Claude Code 中：
/sibyl-research:init              # 创建研究项目
/sibyl-research:start <project>   # 启动全自主研究循环
```

</details>

> **文档**：[完整配置指南](docs/setup-guide.md) · [配置参考 (35+ 选项)](docs/configuration.md) · [MCP 服务器](docs/mcp-servers.md) · [SSH & GPU](docs/ssh-gpu-setup.md) · [全部 12 个命令](docs/plugin-commands.md)

---

## 系统概览

Sibyl 通过 **19 阶段状态机 Pipeline** 编排 20+ 个 AI Agent，自动完成文献调研、创意生成、实验设计与执行、结果分析、论文写作和同行评审。系统支持多轮迭代优化，内置跨项目学习机制持续提升研究质量。

![Sibyl 系统架构](image/sibyl_architecture.png)

### 核心特性

- **19 阶段研究 Pipeline**：从文献检索到 camera-ready 论文的端到端自动化
- **多 Agent 协作**：6 Agent 创意辩论、6 Agent 结果分析、6 Agent 并行写作
- **GPU 并行调度**：拓扑排序 + 动态派发，最大化 GPU 利用率，自动管理任务依赖
- **全维度自主迭代**：质量门控自动判定继续迭代、转向新想法或终止——研究的每个维度都在迭代中自动优化
- **自进化系统**：自动从 8 个维度提取经验、追踪有效性、淘汰无效经验、更新 Agent Prompt——系统随每个项目持续进化
- **多模型协作**：Claude Opus/Sonnet + GPT-5.4 (Codex) 独立交叉审查

## Pipeline 流程

```
+== 研究迭代 ====================+  +== 论文写作 =======================+
|                                 |  |                                   |
|  文献检索 (arXiv + Web)         |  |  大纲                              |
|       |                         |  |       |                           |
|       v                         |  |       v                           |
|  创意辩论 (6 Agent)             |  |  章节写作 (顺序/并行/Codex)        |
|       |                         |  |       |                           |
|       v                         |  |       v                           |
|  实验规划                       |  |  交叉评审 (6 Agent)                |
|       |                         |  |       |                           |
|       v                         |  |       v                           |
|  先导实验                       |  |  整合编辑                          |
|       |                         |  |       |                           |
|       v                         |  |       v                           |
|  完整实验 (GPU 并行)            |  |  终审 (NeurIPS 级别)               |
|       |                         |  |       | 不通过 --> 返回编辑 (x2)   |
|       v                         |  |       v                           |
|  结果辩论 (6 Agent)             |  |  LaTeX --> 编译 PDF                |
|       |                         |  |       |                           |
|       v                         |  +-------|---------+-----------------+
|  决策                           |          |
|       | PIVOT --> 回到创意      |          |
|       | PROCEED                 |          v
+-------|-----------+------------+  +== 审查与反思 =====================+
        |                           |                                     |
        +----------> 大纲           |  审查 (Critic+Supervisor+Codex)     |
                                    |       |                             |
                                    |       v                             |
                                    |  反思 (提取经验教训)                |
                                    |       |                             |
                                    |       v                             |
                                    |  飞书同步 (云文档)                  |
                                    |       |                             |
                                    |       v                             |
                                    |  质量门控                           |
                                    |       | >= 8.0 且 >= 2轮 --> 完成   |
                                    |       | 否则 --> 下一轮迭代         |
                                    |                                     |
                                    +-------------------------------------+
```

### 各阶段详情

| 阶段 | 描述 | Agent 模式 |
|------|------|-----------|
| `literature_search` | arXiv + Web 双源文献调研 | 单 Agent |
| `idea_debate` | 6 视角创意辩论（创新者/实用主义者/理论家/反对者/跨学科/实验主义者） | 6-Agent 团队 |
| `planning` | 设计实验方案，生成含依赖关系的 task_plan.json | 单 Agent |
| `pilot_experiments` | 小规模可行性验证 | 单 Agent |
| `experiment_cycle` | GPU 并行完整实验，拓扑排序分批调度 | 单 Agent + GPU 调度器 |
| `result_debate` | 6 视角结果分析（乐观者/怀疑者/战略家/方法论者/比较者/修正者） | 6-Agent 团队 |
| `experiment_decision` | 监督决策：PIVOT（换方向）或 PROCEED（继续） | 单 Agent |
| `writing_outline` | 生成论文大纲 | 单 Agent |
| `writing_sections` | 分章节写作（顺序/并行/Codex 模式） | 可配置 |
| `writing_critique` | 6 Agent 交叉评审各章节 | 6-Agent 并行 |
| `writing_integrate` | 编辑整合为完整论文 | 单 Agent |
| `writing_final_review` | NeurIPS/ICML 级别终审（可循环修改） | 单 Agent |
| `writing_latex` | 转换为 NeurIPS LaTeX 格式并编译 PDF | 单 Agent |
| `review` | Critic + Supervisor + Codex 并行审查 | 并行 Skills |
| `reflection` | 分类问题、生成改进计划、记录经验 | 单 Agent |
| `lark_sync` | 同步研究数据到飞书云文档 | 单 Agent |
| `quality_gate` | 评估完成度（≥8.0 分 且 ≥2 轮迭代） | 自动 |

## Agent 角色

### 创意生成团队

| Agent | 视角 | 职责 |
|-------|------|------|
| 创新者 | 跨领域创新 | 大胆的方法论迁移和新颖组合 |
| 实用主义者 | 工程可行性 | 确保想法可落地实现 |
| 理论家 | 数学基础 | 关注理论保证和证明 |
| 反对者 | 挑战假设 | 寻找反面证据和盲点 |
| 跨学科者 | 类比启发 | 从认知科学、物理、生物等领域引入方法 |
| 实验主义者 | 实验优先 | 关注可复现性和数据质量 |

### 结果分析团队

| Agent | 视角 | 职责 |
|-------|------|------|
| 乐观者 | 积极发现 | 发掘正面结果和扩展方向 |
| 怀疑者 | 统计严谨性 | 质疑统计显著性和混淆因素 |
| 战略家 | 下一步行动 | 建议资源分配和研究方向 |
| 方法论者 | 方法审查 | 评估内外部效度 |
| 比较者 | SOTA 对标 | 与现有最佳方法对比定位 |
| 修正者 | 假设修正 | 基于结果反思和调整假设 |

### 模型层级

| 层级 | 模型 | 用途 |
|------|------|------|
| Heavy | Opus 4.6 | 综合决策、监督、编辑、批评、反思 |
| Standard | Opus 4.6 | 文献调研、规划、实验、写作 |
| Light | Sonnet 4.6 | 结果辩论、交叉评审、章节批评 |
| Codex | GPT-5.4 High | 独立第三方审查、可选写作模式 |

## 自我进化系统

Sibyl 不只是运行研究——它在学习如何更好地运行研究。每轮迭代结束后，系统从 8 个维度分析哪些有效、哪些失败、哪些低效，然后自动更新自身：

```
研究迭代完成
       |
       v
  反思 Agent ──> 从 8 个维度分析产出
       |              ├── 实验设计质量
       |              ├── 论文写作水平
       |              ├── 资源效率（GPU 利用率、调度优化）
       |              ├── 创意新颖性与贡献度
       |              └── 系统可靠性、分析深度、规划、流程
       v
  进化引擎 ──> 追踪与评估经验
       |              ├── 时间加权频率分析（30 天半衰期）
       |              ├── 有效性评分（早期 vs 后期迭代对比）
       |              └── 成功模式提取（哪些做法要继续保持）
       v
  自动更新 ──> 将验证有效的改进注入 Agent Prompt
       |              ├── 有效经验：提升优先级
       |              ├── 无效经验：0.3x 降权（自动淘汰）
       |              └── 效率洞察：调度与资源优化
       v
  自检 ──> 检测系统性异常
              ├── 跨迭代质量下降趋势
              ├── 经验未能修复的反复错误
              └── 无效经验堆积

```

### 为什么自进化能真正生效

大多数声称能"学习"的 AI 系统都是有状态进程——它们在单次会话中积累上下文，但进程重启后一切归零。Sibyl 采用了根本不同的方法：**无状态架构 + 持久化产物**。

- **每次 prompt 都从磁盘实时加载。** 没有内存缓存，没有常驻守护进程。每个 Agent 在被调用时都从文件系统重新读取其 prompt（`sibyl/prompts/*.md`）。进化引擎修改了 prompt 文件后，下一次 Agent 调用立即读到新版本——无需重启，无需重新部署。
- **每个 Agent 都作为独立子进程运行。** Skill 通过 `python3 -c "..."` 在全新进程中执行，Python 模块每次都重新 import。`sibyl/*.py` 中的代码变更在下一个 stage 立即生效。
- **Config 每次调用都重新解析。** `cli_next()` 每次都实例化新的 `Orchestrator`，重新从磁盘读取 `config.yaml`。进化引擎调整的参数在下一轮调度立即生效。
- **经验 Overlay 是普通文件。** 从历史项目中提炼的经验写入 `~/.claude/sibyl_evolution/lessons/{agent}.md`。`load_prompt()` 每次调用都会追加 overlay 内容——新经验自动注入到下一次 Agent 调用中。

这意味着进化不是需要停机维护的"批量更新"，而是一个**持续、增量的过程**：运行第 N+1 轮迭代的系统已经和运行第 N 轮的不同了，因为第 N 轮结束后的反思已经修改了磁盘上的 prompt、overlay 甚至代码。整个系统的设计使得**每个文件都是真实来源，每个文件都被实时读取**——让自进化成为架构的自然结果，而非后加的功能。

**安全性**：所有系统文件修改都必须通过强制测试（`.venv/bin/python3 -m pytest tests/`）并通过 git commit 追踪，确保每一步进化都可逆、可审计。

**8 大问题类别**：SYSTEM、EXPERIMENT、WRITING、ANALYSIS、PLANNING、PIPELINE、IDEATION、EFFICIENCY —— 每类自动路由到相关 Agent。规划者学会设计更好的实验，实验者学会更高效地使用 GPU，写作者学会避免反复出现的风格问题——全部自动完成。

## 项目结构

```
sibyl-system/
├── sibyl/                      # 核心 Python 模块
│   ├── orchestrate.py          # 状态机编排器（19 阶段 Pipeline）
│   ├── config.py               # 配置管理（模型/GPU/模式）
│   ├── workspace.py            # 工作区文件与 Git 管理
│   ├── gpu_scheduler.py        # GPU 拓扑排序与并行调度
│   ├── evolution.py            # 跨项目进化引擎
│   ├── reflection.py           # 迭代日志
│   └── prompts/                # 32 个 Agent Prompt 模板
├── .claude/
│   ├── agents/                 # Agent 层级定义（heavy/standard/light）
│   └── skills/sibyl-*/         # 30+ Fork Skills（隔离上下文执行）
├── plugin/commands/            # Claude Code 插件命令
├── workspaces/                 # 研究项目工作区
├── tests/                      # 单元测试（~320 个）
└── requirements.txt            # 依赖（PyYAML, rich）
```

### 工作区结构

每个研究项目在 `workspaces/<project>/` 下拥有独立的文件系统：

```
workspaces/<project>/
├── status.json                 # 编排器状态（阶段/迭代/分数）
├── config.yaml                 # 项目级配置覆盖
├── topic.txt / spec.md         # 研究主题与需求规格
├── context/literature.md       # 文献综述
├── idea/                       # 提案、备选方案、辩论记录
├── plan/                       # 实验方案、task_plan.json
├── exp/                        # 代码、结果、日志、GPU 进度
├── writing/                    # 大纲、章节、评审、完整论文、LaTeX
├── logs/                       # 迭代归档、研究日志
└── lark_sync/                  # 飞书同步注册表
```

## 文档

| 文档 | 说明 |
|------|------|
| [配置指南](docs/setup-guide.md) | Claude 可读的配置检查清单（推荐） |
| [快速上手](docs/getting-started.md) | 完整安装与首次运行指南 |
| [配置参考](docs/configuration.md) | 全部 35+ 配置项参考 |
| [MCP 服务](docs/mcp-servers.md) | 第三方 MCP 依赖安装与配置 |
| [SSH 与 GPU 配置](docs/ssh-gpu-setup.md) | GPU 服务器环境配置 |
| [插件命令](docs/plugin-commands.md) | 全部 12 个插件命令参考 |
| [Codex 集成](docs/codex-integration.md) | GPT-5.4 交叉审查配置 |
| [飞书同步](docs/feishu-lark-setup.md) | 飞书云文档同步配置 |
| [系统架构](docs/architecture.md) | 系统内部实现（贡献者参考） |

## 第三方依赖

### MCP 服务

| 服务 | 必需 | 用途 | 来源 |
|------|------|------|------|
| [SSH MCP](https://github.com/classfang/ssh-mcp-server) | 是 | 远程 GPU 执行 | `npx @fangjunjie/ssh-mcp-server` |
| [arXiv MCP](https://github.com/blazickjp/arxiv-mcp-server) | 是 | 论文搜索 | `pip install arxiv-mcp-server` |
| [Google Scholar MCP](https://github.com/JackKuo666/Google-Scholar-MCP-Server) | 推荐 | 学术引用搜索 | GitHub clone |
| [Codex MCP](https://github.com/openai/codex) | 可选 | GPT-5.4 审查 | `npm install -g @openai/codex` |
| [Lark MCP](https://github.com/larksuite/lark-openapi-mcp) | 可选 | 飞书 Bitable/IM | `npm install -g @larksuiteoapi/lark-mcp` |
| [Feishu MCP](https://github.com/cso1z/Feishu-MCP) | 可选 | 飞书文档操作 | `npm install -g feishu-mcp` |
| [bioRxiv MCP](https://github.com/JackKuo666/bioRxiv-MCP-Server) | 可选 | 生物预印本 | `pip install biorxiv-mcp-server` |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | 可选 | 网页浏览 | `npm install -g @playwright/mcp` |

完整安装与 `~/.mcp.json` 配置见 **[MCP 服务指南](docs/mcp-servers.md)**。

### Python 依赖

- **PyYAML** >= 6.0 — 配置文件解析
- **rich** >= 13.0 — 终端格式化输出

### 可选工具

- [OpenAI Codex CLI](https://github.com/openai/codex) — 独立交叉审查（`codex_enabled: true`）
- [Ralph Loop](https://github.com/anthropics/claude-code) — 自主迭代循环（Claude Code 插件）

## 核心机制

### GPU 并行调度

实验阶段读取 `task_plan.json`，按依赖关系拓扑排序，然后根据可用 GPU 贪心分配并行执行：

```json
{
  "tasks": [
    {"id": "train_baseline", "depends_on": [], "gpu_count": 2, "estimated_minutes": 60},
    {"id": "train_model_a", "depends_on": ["train_baseline"], "gpu_count": 1, "estimated_minutes": 90},
    {"id": "train_model_b", "depends_on": ["train_baseline"], "gpu_count": 1, "estimated_minutes": 90},
    {"id": "ablation", "depends_on": ["train_model_a", "train_model_b"], "gpu_count": 1, "estimated_minutes": 30}
  ]
}
```

### 跨项目自我进化

一个项目中积累的经验自动改进所有未来项目：

1. **记录**：每次反思后，从 8 个维度分类问题和成功模式
2. **分析**：时间衰减加权聚合（30 天半衰期）——近期经验权重更高
3. **评估**：对比早期和后期分数，验证经验是否真正有效（需 >= 4 次出现）
4. **应用**：为每个 Agent 生成专属 Prompt 叠加层——每个 Agent 只接收与其角色相关的经验
5. **淘汰**：无效经验自动降权（x0.3），防止错误建议持续影响系统
6. **自检**：检测质量下降、未被经验修复的反复错误和无效经验堆积

### PIVOT 机制

当实验结果不理想时，监督决策 Agent 可触发 PIVOT：

- 分析结果是否支持原始假设
- 评估是否值得继续投入
- 若 PIVOT：回退到创意辩论阶段，携带备选方案
- 最多 6 次 PIVOT 循环（可配置）

## 横向对比

| 特性 | Sibyl Research System | [AI Scientist](https://github.com/SakanaAI/AI-Scientist) | [AutoResearch](https://github.com/karpathy/autoresearch) |
|------|-------------|-------------|--------------|
| 架构 | Claude Code 原生（skills, teams, MCP） | API 封装 | 单文件脚本 |
| Agent 数量 | 20+ 专业化 Agent | 单个 LLM | 单 Agent |
| 创意生成 | 6 Agent 多视角辩论 | LLM 头脑风暴 | 无 |
| 实验执行 | GPU 并行 + 拓扑排序调度 | 模板化执行 | 单 GPU 循环 |
| 论文写作 | 多 Agent 写作 + 评审 + 修改 | LLM 生成 | 无 |
| 自我进化 | 跨项目经验学习 | 无 | 无 |
| 质量控制 | 多轮审查 + 质量门控 | 自动审查 | 基于指标 |
| 人工干预 | 全自主 | 极少 | 极少 |

## 许可证

MIT License
