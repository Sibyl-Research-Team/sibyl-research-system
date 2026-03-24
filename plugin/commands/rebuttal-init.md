---
description: "交互式初始化 Rebuttal 项目"
argument-hint: "[paper_path]"
---

# /sibyl-research:rebuttal-init

交互式初始化 Rebuttal 工作区。通过提问收集论文、评审、代码等信息。

工作目录: `$SIBYL_ROOT`

## Python 环境

所有 python3 调用必须使用 `.venv/bin/python3`，不要使用裸 `python3`。

## 步骤

0. **打印启动横幅**：

```
╔═════════════════════════════════════════════════════════════════╗
║     SIBYL REBUTTAL SYSTEM  ·  Adversarial Rebuttal Engine       ║
╚═════════════════════════════════════════════════════════════════╝

  正在初始化 Rebuttal 项目...
```

1. **收集信息**（如果 `$ARGUMENTS` 提供了论文路径，用它作为起始；否则逐步询问）：

   向用户依次询问（必填项标 *）：
   - * **论文文件路径**：PDF、LaTeX 或 Markdown（如 `paper.pdf`）
   - * **Reviewer 评审目录**：包含每个 reviewer 评审文件的目录（每人一个 .md/.txt/.json/.pdf 文件）
   - **源代码路径**（可选）：如果论文涉及代码实现
   - **字数限制**（可选，默认不限）：每个 reviewer 回复的字数上限
   - **目标会议/期刊**：了解 rebuttal 格式要求
   - **Codex 独立审查**（可选，默认关闭）：是否启用 Codex 作为第三方审查
   - **输出语言**（默认英文）：rebuttal 回复语言
   - **自定义工作区路径**（可选）：默认 `rebuttals/rebuttal-<paper_name>/`

2. **初始化工作区**：

```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "
from sibyl.orchestrate import cli_rebuttal_init
cli_rebuttal_init(
    paper_path='PAPER_PATH',
    reviews_dir='REVIEWS_DIR',
    workspace_dir='WORKSPACE_DIR',   # 可选，None 则自动生成
    word_limit=WORD_LIMIT,           # 0 = 不限
    source_repo='SOURCE_REPO',       # 可选，None 则不传
    codex_enabled=CODEX_ENABLED,     # True/False
    language='LANGUAGE',             # 'en' 或 'zh'
)
"
```

3. **展示初始化结果**：解析 JSON 输出，向用户展示：
   - 工作区路径
   - 检测到的 reviewer 数量和 ID
   - 配置摘要（字数限制、Codex 状态等）
   - 下一步提示：`使用 /sibyl-research:rebuttal-start WORKSPACE_PATH 开始对抗迭代`
