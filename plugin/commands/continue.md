---
description: "恢复已有研究项目"
argument-hint: "<project>"
---

# /sibyl-research:continue

恢复已有项目并进入编排循环。

**所有用户可见的输出必须使用中文。**

工作目录: `/Users/cwan0785/sibyl-system`

参数: `$ARGUMENTS`（项目名称）

## 步骤

1. 查看项目状态：
```bash
cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "from sibyl.orchestrate import cli_status; cli_status('workspaces/$ARGUMENTS')"
```
2. 进入编排循环继续执行（参考 `/sibyl-research:start` 中的编排循环说明）
