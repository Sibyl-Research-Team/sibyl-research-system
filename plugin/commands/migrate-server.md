---
description: "迁移服务器端旧项目数据到 v5 结构"
argument-hint: "<project>"
---

# /sibyl-research:migrate-server

迁移服务器端旧项目数据到 v5 结构。

**所有用户可见的输出必须使用中文。**

参数: `$ARGUMENTS`（项目名称）

执行以下命令：
```bash
cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "from sibyl.orchestrate import cli_migrate_server; cli_migrate_server('$ARGUMENTS')"
```

返回的 commands 列表通过 `mcp__ssh-mcp-server__execute-command` 依次执行。
