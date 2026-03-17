# Sibyl WebUI Frontend

## 一键启动前后端

在仓库根目录执行:

```bash
./scripts/dev-webui.sh
```

默认会同时启动:

- Backend API: `http://127.0.0.1:7654`
- Frontend UI: `http://127.0.0.1:3000`

脚本会在本地开发模式下自动取消 `SIBYL_DASHBOARD_KEY`，避免前端请求被 `401 Unauthorized` 挡住。按 `Ctrl+C` 会同时关闭前后端。

如果你需要保留鉴权环境变量:

```bash
./scripts/dev-webui.sh --with-auth
```

启用鉴权后，前端会先显示解锁页；输入正确的 dashboard key 后才会加载项目列表。

## 手动启动

后端:

```bash
cd /Users/cwan0785/sibyl-system
env -u SIBYL_DASHBOARD_KEY .venv/bin/python3 -m sibyl.cli webui --host 127.0.0.1 --port 7654
```

前端:

```bash
cd /Users/cwan0785/sibyl-system/webui
npm run dev -- --hostname 127.0.0.1 --port 3000
```

如果你是用生产模式启动前端:

```bash
cd /Users/cwan0785/sibyl-system/webui
npm run build
npm run start -- --hostname 127.0.0.1 --port 3000
```

注意: `next start` 使用的是上一次 `build` 产物。前端代码更新后，如果不重新 `npm run build`，页面可能继续表现为旧版本。

## 项目列表为什么可能不显示

- WebUI 只会显示当前 `workspaces_dir` 下包含 `status.json` 的目录。
- 如果后端启用了 `SIBYL_DASHBOARD_KEY`，未登录时现在会显示解锁页，不再表现成“空列表”。
- 首页和解锁页右上角都支持 `EN / 中文` 切换。

## 可选环境变量

```bash
SIBYL_WEBUI_BACKEND_ORIGIN=http://127.0.0.1:7765
```

用于让 Next.js 前端代理到非默认后端地址，适合本地多实例调试或端口冲突场景。

## 依赖准备

后端依赖:

```bash
cd /Users/cwan0785/sibyl-system
.venv/bin/pip install -e .
```

前端依赖:

```bash
cd /Users/cwan0785/sibyl-system/webui
npm install
```

## 常用命令

```bash
npm run lint
npm run build
```
