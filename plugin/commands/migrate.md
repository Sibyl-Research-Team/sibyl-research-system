---
description: "迁移本地旧项目到 v5 结构"
argument-hint: "<project>"
---

# /sibyl-research:migrate

迁移本地旧项目到 v5 结构。

**所有用户可见的输出必须使用中文。**

参数: `$ARGUMENTS`（项目名称）

执行以下命令：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_migrate; cli_migrate('workspaces/$ARGUMENTS')"
```
