# Library Atlas 本地运行与开发

适用环境：Windows，Python 3.14.3（`.python-version`），Node 22.22.1。路径含中文或空格无需处理；脚本按自身位置解析路径。

## 安装
```bat
scripts\setup-backend.cmd          :: 运行依赖，按 requirements.lock 校验哈希
scripts\setup-backend.cmd dev      :: 另装测试与检查工具
cd frontend
npm.cmd ci
npm.cmd run build
```
依赖升级：改 `backend/requirements.in` 或 `requirements-dev.in`，用 `pip-compile --generate-hashes --allow-unsafe --strip-extras --no-header` 重新生成对应 `.lock`，单独提交并说明。

## 启动、检查、关闭
```bat
scripts\serve.cmd
```
打开 http://127.0.0.1:8765/ 。首次运行显示演示空间；点右上角的模式标识可切换到“我的资料库”。

| 操作 | 命令 |
| --- | --- |
| 关闭 | 在服务窗口按 Ctrl+C |
| 存活 | `curl http://127.0.0.1:8765/api/v1/health` |
| 就绪 | `curl http://127.0.0.1:8765/api/v1/ready`（未就绪时 503 并给出原因） |
| 检查配置并执行迁移 | `cd backend && .venv\Scripts\python -m app check` |
| 新建显式目录并初始化空库 | `cd backend && .venv\Scripts\python -m app init --data-dir "D:\Atlas 数据"` |

端口被占用时服务报错退出（退出码 3），**不会结束任何其他程序**。配置错误退出码 2，资料库问题退出码 4。

## 配置
优先级：命令行参数 > 环境变量 > 默认值。参考 `backend/.env.example`（该文件不会被自动读取，里面不放密钥）。

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `ATLAS_PROFILE` | `real` | `real` 或 `test` |
| `ATLAS_DATA_DIR` | `%LOCALAPPDATA%\LibraryAtlas\profiles\default` | 必须是绝对路径；显式指定时目录必须已存在 |
| `ATLAS_PORT` | `8765` | 1024–65535 |
| `ATLAS_STATIC_DIR` | `frontend/dist` | 前端构建位置 |
| `ATLAS_DEV_ORIGINS` | 空 | 额外允许的回环来源，逗号分隔 |

服务只绑定 `127.0.0.1`，没有改成其他地址的配置项。浏览器提交的任何内容都不能改变配置或路径。

## 数据目录
```text
%LOCALAPPDATA%\LibraryAtlas\profiles\default\
  library.sqlite3（及 -wal、-shm）
  backups\            迁移前的自动备份，保留最近 5 份
```
- 不依赖当前工作目录，不写入源码目录，不进 Git。
- **默认目录**不存在时自动创建。**显式目录**不存在时拒绝启动：它可能是没插上的硬盘，新建空库会让人以为资料丢了。
- 数据库打了 `real` / `test` 印记，服务拒绝打开印记不符的库。测试目录另有 `.atlas-test-data` 标记文件，不能作为真实库打开，也不能位于正常数据目录之内。
- 不扫描磁盘，不移动已有文件，不创建下载或解压目录。

## 模式
| | 演示空间 | 我的资料库 | 隔离测试库 |
| --- | --- | --- | --- |
| 数据 | 浏览器内合成数据 | 本地 SQLite，默认为空 | 本地 SQLite，合成样本 |
| 需要服务 | 否 | 是 | 是 |
| 个人修改保存到 | 浏览器 localStorage | 数据库 | 测试数据库 |
| 顶部标识 | DEMO · 演示模式 | 我的资料库 | 测试库 · 合成数据 |

- 模式选择保存在 `localStorage` 的 `library-atlas.workspace-mode.v1`，只存这一个值。默认演示空间。构建时设 `VITE_DEMO_MODE=false` 可完全移除演示空间。
- 查询缓存按模式分开（`['library','demo',…]` 与 `['library','real',…]`）。离开真实模式时取消其请求并清除其缓存。Demo 的修改、连接和任务不会进入真实库，反之亦然；不提供迁移。
- 服务不可用时显示“本地服务未连接”和重试，不显示空库，也不回退 Demo。

## 合成测试库
默认启动不会写入任何样本。测试库必须显式指定目录：
```bat
cd backend
.venv\Scripts\python -m app seed-test --data-dir "%TEMP%\atlas-test" --size 120
.venv\Scripts\python -m app serve --profile test --data-dir "%TEMP%\atlas-test"
```
- `--size` 是普通作品数量，大规模验证用 1500、5000；另加 3 条不可见的私人哨兵。
- 样本覆盖两种来源、各内容类型、跨来源同编号、同名作品、多文件/分卷、未知字段、长标题、缺封面与私人记录。全部虚构。
- 重建：加 `--reset`。只有带标记文件的目录才允许，且只删除该目录下的 `library.sqlite3*`。非空且无标记的目录拒绝写入。
- 清理：直接删除这个测试目录。

## 前后端联调
```bat
:: 窗口 1
set ATLAS_DEV_ORIGINS=http://127.0.0.1:5173,http://127.0.0.1:4173
scripts\serve.cmd
:: 窗口 2
scripts\dev.cmd
```
Vite 把 `/api` 代理到 `127.0.0.1:%ATLAS_PORT%`（默认 8765）。

## 迁移与恢复
- 迁移在服务启动时自动执行，版本由 Alembic 记录，幂等。已有数据库在升级前先做 SQLite 在线备份并校验完整性；迁移在单个事务内，失败整体回滚。
- 资料库版本高于程序时拒绝打开，不做任何改动。本项目**不提供降级**。
- 手动恢复：关闭服务，删除 `library.sqlite3`、`-wal`、`-shm`，把 `backups\` 中的文件复制为 `library.sqlite3`，再启动。
- 备份里有你的作品与备注，但没有平台凭据：数据库本身从不保存密码、Cookie 或 API Key。

## 测试
```bat
powershell -File scripts\check.ps1                :: 后端 ruff、mypy、pytest；前端类型、lint、格式、单测、构建
powershell -File scripts\check.ps1 -WithBrowser   :: 再加完整 Playwright 矩阵
cd frontend && npx.cmd playwright test tests/e2e/real-mode.spec.ts --project=1080p
```
- 后端测试用临时目录里的真实 SQLite 文件和真实应用，不 mock 数据库。
- `real-mode.spec.ts` 启动真实服务进程，使用临时数据目录并把 `LOCALAPPDATA` 指向临时目录，所以不可能碰到正常资料。需要先 `npm.cmd run build`。
- 证据输出到 `artifacts/phase-2-checkpoint-1/`（不入库）。

## 常见问题
| 现象 | 处理 |
| --- | --- |
| 配置错误：目录不存在 | 检查硬盘是否连接；确需新建用 `init` |
| 配置错误：该目录是测试目录 | 去掉 `ATLAS_DATA_DIR`，或加 `--profile test` |
| 端口已被占用 | 关闭占用程序，或设置 `ATLAS_PORT` |
| 页面显示“本地服务未连接” | 启动 `scripts\serve.cmd` 后点重新连接 |
| 页面显示“资料库暂时不可用” | 按提示处理；文件未被改动，可从 `backups\` 恢复 |
| `http://127.0.0.1:8765/` 返回 frontend_not_built | 运行 `npm.cmd run build` |
| Vite 页面报来源被拒绝 | 启动服务前设置 `ATLAS_DEV_ORIGINS` |
