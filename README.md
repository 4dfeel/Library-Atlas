# Library Atlas

面向 Windows 11 的本地多平台作品库（Steam + DLsite，以游戏为核心）。当前交付为 **Phase 1 前端独立 Demo**：检查点 1（AppShell + 作品库）、检查点 2（作品详情，含多平台作品库重构）、检查点 3（首页 Dashboard、演示来源连接与下载解压）与检查点 4（全页面验收）。工程检查已完成，Phase 1 等待用户人工验收，见 [Phase 1 验收报告](docs/PHASE1_ACCEPTANCE_REPORT.md)。所有作品、封面和游玩记录均为合成资料（Steam 游戏与 DLsite 风格的游戏/图像/视频/音声/其他作品，全部原创、全年龄），不连接 Steam 或 DLsite。

## 在 Windows 启动

使用 **Node 22.22.1 + npm 10.9.4**（见 `.node-version` 和 `frontend/package.json`），打开 PowerShell：

重新执行 `npm.cmd ci` 前先用 `Ctrl+C` 停止已有开发/预览服务，避免 Windows 锁住已加载的原生模块文件。

```powershell
Set-Location -LiteralPath 'H:\VSC workspacce\Library Atlas\frontend'
npm.cmd ci
npm.cmd run dev
```

访问 [http://127.0.0.1:5173/library](http://127.0.0.1:5173/library)。也可双击 `scripts/dev.cmd`，或从任意目录运行它；`scripts/dev.cmd preview` 启动构建预览。脚本按自身位置解析路径，路径中的中文、空格无需移动或改名。

另提供 `scripts/dev.ps1` 与 `scripts/check.ps1`，供允许执行本地 PowerShell 脚本的环境使用。当前机器的策略会阻止 `.ps1`；直接用 `.cmd` 或上述 `npm.cmd` 命令即可，无需修改执行策略。

构建与本地静态预览：

```powershell
npm.cmd run build
npm.cmd run preview
```

预览地址 [http://127.0.0.1:4173/library](http://127.0.0.1:4173/library)。本检查点使用 Vite 供前端评审；正式产品仍按 ARCHITECTURE 使用 FastAPI 托管构建，但后端尚未授权开发。端口已占用时命令直接报错，请先关闭原来占用该端口的服务。

## Demo 使用

- 默认生成 1500 条；[5000 条压力场景](http://127.0.0.1:4173/library?size=5000) 或“关于演示”设置可切换规模。普通可见数量为 1463/4872，其余合成条目属于隐藏、私人或待确认，不进入普通查询。
- 首页 [http://127.0.0.1:4173/](http://127.0.0.1:4173/) 可切换范围（`?scope=steam|dlsite-games|dlsite-media|games`）；“管理来源连接”演示连接/过期/失败/断开，顶栏下载图标查看演示任务。DLsite 作品详情（如 `demo-00033`）提供“演示下载并解压”，`demo-00144` 首次校验失败可重试，`demo-00048` 仅限官方阅读器。全部为模拟，不登录、不下载、不写文件；`?state=source-expired` 预置 DLsite 会话过期。
- 顶部按作品类型（全部/游戏/非游戏/漫画·图像/视频/音声/其他）切换，工具栏可按平台筛选、仅看收藏。
- 网格/列表均虚拟化；支持名称/制作方防抖搜索、类型/游玩/安装筛选、名称/游玩时长排序及收藏。`Ctrl+K` 聚焦搜索（详情页中跳回游戏库搜索；正在输入备注时不跳转）。搜索、筛选、排序与视图写入 URL，返回时恢复。
- 点击游戏名称或卡片进入详情 `/library/<ID>`，例如 [星穹观测站](http://127.0.0.1:4173/library/demo-00001)。状态、1–5 星评分、备注与收藏是**演示修改**，保存在本浏览器 localStorage（键 `library-atlas.demo-edits.v1.atlas-demo-41544c41`），刷新后保留；“演示设置 → 重置演示修改…”确认后清除。不写入任何真实资料。
- 详情边界样本：`demo-00010` 无背景、`demo-00036` 无封面、`demo-00025` 双缺图、`demo-00008` 未开始、`demo-00002` 无成就、`demo-00003` 无评分与备注、`demo-00029` 超长中日英标题；`demo-00098`（私人）与 `demo-99999`（不存在）显示同一不可用页面。`?state=loading|error|save-error` 复现加载、读取失败与保存失败。
- `?state=empty` / `?state=error` / `?state=loading` 用于检查反馈；`?q=跨越星海` 检查超长标题，`?q=晨雾回廊` 检查缺封面。
- `frontend/.env.example` 给出构建配置；`VITE_DEMO_MODE=false` 关闭 Demo。需重启 dev 或重新构建；此时显示未接入说明，不会转为真实数据。
- 收藏夹管理、游玩计划、发现、私人空间、启动/打开作品、真实登录、库同步与真实下载解压尚未开放；未实现操作明确标注，不会假装已经成功。

## 验证与截图

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run format:check
npm.cmd test
npm.cmd run build
npx.cmd --no-install playwright install chromium
npm.cmd run test:e2e
```

快速检查可用 `npm.cmd run test:smoke`。完整检查使用七档 CSS 视口/DPR：1080P、2K、4K、4K@1.5、1080P@2、1280×720、1440×900。DPR 模拟不能替代 Windows 系统缩放人工检查。

生成证据位于 `artifacts/phase-1-acceptance/`：`screenshots/<档位>/<页面-状态>__<视口>@<DPR>.png`、`layout-checks.jsonl`（已通过的布局断言）、`performance/*.json`（性能与离线样本）。运行后在仓库根目录执行 `node scripts/index-evidence.mjs` 生成 `INDEX.md` 覆盖表。HTML 报告在 `frontend/playwright-report/`。这些运行产物被 Git 忽略；GitHub CI 保留短期 artifact，不把 trace 或用户资料写入仓库。查看报告：`npx.cmd --no-install playwright show-report`。

单元测试验证可见性过滤、搜索排序、收藏隔离、SVG 安全、组件反馈、弹窗焦点与语义配色对比。Playwright 验证布局、实际筛选、快捷键、收藏、焦点返回、滚动锚点、图片请求范围和浏览器性能。新截图是评审证据；用户确认前不作为已批准的回归基线。

## 结构与本地素材

- `frontend/src/app/`：AppShell（侧栏、顶栏、路由切换、演示设置）。`src/lib/router.ts` 为最小 History API 路由。
- `frontend/src/features/game-detail/`：详情页顶部展示区、正文与“我的记录”编辑。
- `frontend/src/components/`：共用卡片及按 shadcn/ui 模式组合的 Radix 基础组件。
- `frontend/src/lib/data/`：类型、Demo source、隐私选择器、TanStack Query hooks；页面不直接导入 fixture。未来仅替换 source，真实服务端仍须执行隐私过滤。
- `frontend/src/features/library/`：Library 页面、URL 状态、容器测量与 TanStack Virtual 网格/列表。
- `frontend/src/styles/globals.css`：设计 token、组件状态、响应式与减少动画规则。
- `frontend/public/demo/covers/`：24 张原创叙事矢量插画；`node scripts/generate-demo-covers.mjs` 从仓库根目录可确定性重建，同时生成 `public/demo/backdrops/` 24 幅 2:1 详情背景。其余程序化 SVG 只在可见卡片生成，缺图使用独立占位。
- 字体通过锁定的 `@fontsource-variable/noto-sans-sc` 包打入构建，使用 unicode-range 按需加载本地 WOFF2，无 Google Fonts/CDN 请求。系统 Segoe UI 优先；中文可回退 Noto Sans SC。字体许可证随发布物提供于 `licenses/noto-sans-sc-OFL.txt`。

需求和范围以 [当前执行规范](docs/specs/PHASE1.md)、[设计规范](docs/DESIGN.md) 和 [路线图](docs/ROADMAP.md) 为准。Phase 1 完成后等待用户人工验收；未经另行授权不进入 Phase 2（后端、真实登录、同步与下载）。
