---
description: "恢复已有研究项目"
argument-hint: "<project>"
---

# /sibyl-research:continue

恢复已有项目并进入编排循环。

**所有用户可见的输出必须使用中文。**

工作目录: 项目根目录（通过 $SIBYL_ROOT 或 cd 到 clone 位置）

参数: `$ARGUMENTS`（项目名称）

## 步骤

1. 查看项目状态：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_status; cli_status('workspaces/$ARGUMENTS')"
```
2. 进入编排循环继续执行（参考 `/sibyl-research:start` 中的编排循环说明）
