---
description: "交互式初始化新研究项目，生成 spec.md 规格文件"
argument-hint: "[topic]"
---

# /sibyl-research:init

**交互式初始化项目**。通过提问生成项目规格 markdown，用户修改后再用 `/sibyl-research:start` 启动。

**所有用户可见的输出必须使用中文。**

工作目录: `/Users/cwan0785/sibyl-system`

## 步骤

1. 如果用户给了 topic（`$ARGUMENTS`），用它作为起始；否则询问研究主题
2. 向用户依次询问（可跳过）：
   - 研究主题（一句话）
   - 背景与动机
   - 初始 Ideas
   - 关键参考文献（arXiv URL 等）
   - 可用资源（GPU、服务器）
   - 实验约束（training-free / 轻量 / 不限）
   - 目标产出（论文 / 技术报告 / 实验验证）
   - 特殊需求
3. 生成项目规格文件：
```bash
cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "from sibyl.orchestrate import cli_init_spec; cli_init_spec('PROJECT_NAME')"
```
4. 将收集的信息写入 `workspaces/PROJECT_NAME/spec.md`
5. 告知用户检查并修改 spec.md，确认后用 `/sibyl-research:start` 启动
