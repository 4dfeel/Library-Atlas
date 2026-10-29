# Library Atlas

面向 Windows 11 的本地 Steam 游戏收藏平台。当前交付为 **Phase 1 / 检查点 1：AppShell + Library 的独立 Demo**，整阶段尚未完成。所有游戏、封面和游玩记录均为合成资料，不连接 Steam。

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
- 网格/列表均虚拟化；支持名称防抖搜索、类型/游玩/安装筛选、名称/游玩时长排序及收藏。`Ctrl+K` 聚焦搜索；收藏仅在当前页面会话内保留，刷新重置。
- `?state=empty` / `?state=error` / `?state=loading` 用于检查反馈；`?q=跨越星海` 检查超长标题，`?q=晨雾回廊` 检查缺封面。
- `frontend/.env.example` 给出构建配置；`VITE_DEMO_MODE=false` 关闭 Demo。需重启 dev 或重新构建；此时显示未接入说明，不会转为真实数据。
- 首页、详情、收藏夹管理、私人空间和 Steam 同步尚未开放。现有收藏按钮有效；未实现页面不会假装已经成功。

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

生成证据位于 `artifacts/checkpoint-1/screenshots/<档位>/`、`artifacts/checkpoint-1/performance.json` 和 `frontend/playwright-report/`。这些运行产物被 Git 忽略；GitHub CI 保留短期 artifact，不把 trace 或用户资料写入仓库。查看报告：`npx.cmd --no-install playwright show-report`。

单元测试验证可见性过滤、搜索排序、收藏隔离、SVG 安全、组件反馈、弹窗焦点与语义配色对比。Playwright 验证布局、实际筛选、快捷键、收藏、焦点返回、滚动锚点、图片请求范围和浏览器性能。新截图是评审证据；用户确认前不作为已批准的回归基线。

## 结构与本地素材

- `frontend/src/app/`：AppShell、Library 状态和筛选交互。
- `frontend/src/components/`：共用卡片及按 shadcn/ui 模式组合的 Radix 基础组件。
- `frontend/src/lib/data/`：类型、Demo source、隐私选择器、TanStack Query hooks；页面不直接导入 fixture。未来仅替换 source，真实服务端仍须执行隐私过滤。
- `frontend/src/features/library/`：容器测量与 TanStack Virtual 网格/列表。
- `frontend/src/styles/globals.css`：设计 token、组件状态、响应式与减少动画规则。
- `frontend/public/demo/covers/`：24 张原创叙事矢量插画；`node scripts/generate-demo-covers.mjs` 从仓库根目录可确定性重建。其余程序化 SVG 只在可见卡片生成，缺图使用独立占位。
- 字体通过锁定的 `@fontsource-variable/noto-sans-sc` 包打入构建，使用 unicode-range 按需加载本地 WOFF2，无 Google Fonts/CDN 请求。系统 Segoe UI 优先；中文可回退 Noto Sans SC。字体许可证随发布物提供于 `licenses/noto-sans-sc-OFL.txt`。

需求和范围以 [当前执行规范](docs/specs/PHASE1.md)、[设计规范](docs/DESIGN.md) 和 [路线图](docs/ROADMAP.md) 为准。检查点 1 完成后等待用户确认视觉方向，不自动进入详情、Dashboard 或后端阶段。
