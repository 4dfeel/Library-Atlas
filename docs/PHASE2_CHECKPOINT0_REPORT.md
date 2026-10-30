# Phase 2 · 检查点 0 报告：现状审查、平台能力验证与接入方案

日期：2026-10-30 · 分支 `phase-2/checkpoint-0`（基于 `phase-1/foundation` @ `0baa37f`）
交付文件：[能力矩阵](PHASE2_CAPABILITY_MATRIX.md) · [接入方案](PHASE2_INTEGRATION_PLAN.md) · 本报告

## 1. 结论
**调研完成，方案待用户确认；满足用户决策后可有条件进入检查点 1。**
- 检查点 1（本地服务、持久化、真实模式基础）不依赖任何平台决定，可以先做。
- DLsite 登录（检查点 2）有一个关键前提尚未证实：DLsite 登录页对非浏览器请求返回 Cloudflare 人机验证（E3），所以只能由用户在真正的浏览器引擎里登录。推荐用 Atlas 拉起的 WebView2 登录小窗口；能否在其中顺利登录要到检查点 2 由用户实测（M1）。
- DLsite 没有找到面向第三方的公开 API。可行路线依赖 DLsite Play 网页使用的非公开接口（有活跃维护的 MIT 开源实现作参考），存在条款灰色地带与接口变动风险，需要用户知情决定。
- Steam 路线清楚：用户自己的 Web API Key + SteamID，官方文档层已验证；私密资料下的行为待实测。
- 原始文件下载、分割格式、断点续传都还是**待验证**，不能承诺“所有已购作品一键下载解压”。

## 2. Phase 1 前置状态与本次授权
- Phase 1：检查点 4 已提交（`0baa37f`），[验收报告](PHASE1_ACCEPTANCE_REPORT.md)结论为“自动化与本环境视觉检查通过，待用户确认”；无已知阻塞问题。
- 用户于 2026-10-30 指示“检查 Phase 2 大纲并开始检查点 0”，本次即依此执行。**用户尚未明确表示 Phase 1 人工验收通过**，ROADMAP 中 Phase 1 状态保持“用户人工验收：未完成”，列为待决策 D5。
- 本次授权：仓库审查、公开资料核对、隔离的可丢弃实验、编写三份文档并提交。未授权、也未做：后端/数据库搭建、登录、同步、下载、解压、修改应用代码或 Demo 行为。

## 3. 审查与基线
- **已读规范**：AGENTS、PRODUCT、DESIGN、ARCHITECTURE、ROADMAP、`specs/PHASE1.md`、Phase 1 检查点 1–4 报告与验收报告（检查点 4 期间已逐一阅读；本次只复核 ARCHITECTURE §3–§9 与 ROADMAP）、Phase 2 大纲与检查点 0 prompt（位于用户本地 Codex 输出目录，未入库）。
- **代码现状**：只有前端；**无 `backend/` 目录、无 Python 依赖、无数据库**。ARCHITECTURE 的 FastAPI/SQLite 部分仍是计划。数据层替换边界为 `LibrarySource { mode: 'demo' | 'real' }`，详见接入方案 §1 的扩展点表。
- **发现的不一致**：
  1. ROADMAP 把“DLsite 一键下载解压”放在 Phase 6 可选扩展，而 Phase 2 大纲放在 Phase 2 检查点 4–5 → 待用户确认（D5）。
  2. ROADMAP 第 3 行状态描述停留在检查点 2，与第 29 行 Phase 1 状态不一致（历史遗留，本次更新状态行）。
  3. ARCHITECTURE §6 下载白名单只写了 Steam/CDN；DLsite 主机需在方案确认后补入。
  4. 前端 `Game.file` 是单文件，真实 DLsite 作品可能多版本/分卷 → CP3–CP4 改为文件列表。
  5. Phase 2 大纲开头仍写“检查点 4 仍在进行”，已过时（外部文件，未修改）。
- **基线检查（本次实际运行）**：类型检查已通过；Vitest 10 个文件 93/93 已通过。**未执行**完整 Playwright 矩阵：本次没有修改任何应用代码，检查点 4 在同一代码树上的结果仍有效（93 通过 / 117 按设计跳过 / 0 失败）。

## 4. 资料核对
- 核对日期 2026-10-30（JST），全部来源与链接见能力矩阵“证据编号”E1–E18。
- 优先官方资料：DLsite 利用規約（2025-04-21 改定）、Steam IPlayerService/OpenID/Web API 条款、Microsoft WebView2、Python zipfile、7-Zip 许可。
- 第三方实现：只读审阅 `bhrevol/dlsite-async`（MIT，提交 `1af2943`），未运行、未复制代码；仅用于提出接口假设。
- **研究限制**：未找到 DLsite 官方帮助中关于分割下载/二步验证/Nest 的原文（只有二手资料，已标低可靠性）；Valve Developer Wiki 的 Web API 页对抓取返回 403，响应字段名来自社区资料；没有进行任何真实账号验证。

## 5. 实验
| # | 问题 | 方法 | 结果 | 材料 |
|---|---|---|---|---|
| X1 | DLsite 登录页能否由后端直接访问 | 对登录页、首页、Play 接口、product.json 各发 1 次未认证请求 | 登录页 403 + Cloudflare 质询；Play 接口 401 JSON；product.json 200 | 矩阵 E3/E4（仅记录状态码与字段名） |
| X2 | 本机能否使用 Credential Manager 与 DPAPI | ctypes 写/读/删假值；测 2560/2561 字节；DPAPI 20KB 往返 | 2560 成功、2561 失败（1783）；删除后不可读；DPAPI 往返成功；测试项已确认清除 | `work/phase2-cp0/probe_credentials.py`、`.result.json` |
| X3 | 标准库能否正确处理日文 ZIP 与越界路径 | 合成 cp932 无标志 ZIP、UTF-8 ZIP、6 类成员路径、349 字符长路径 | 默认解码错误、指定 cp932 正确、UTF-8 标志优先；5 类越界全部拒绝；长路径成功 | `work/phase2-cp0/probe_archives.py`、`.result.json` |
| X4 | Steam 公开端点 | CDN 3 种图片 HEAD；GetOwnedGames 无 key | 图片 200 + ETag/max-age；API 401 | 矩阵 E13 |
| — | 下载流式/Range | **未执行**：本地测试服务无法证明 DLsite 下载主机是否支持 Range，结论只能来自 M4 | — | — |
| — | WebView2 登录与 Cookie 读取 | **未执行**：需要引入 pywebview/pythonnet 依赖，且有意义的验证必须用真实登录页（CP2/M1） | — | — |

实验均在临时目录进行，未使用真实凭据，未安装依赖，未修改 lockfile 或用户配置。

## 6. 推荐路线与主要未知
推荐顺序：CP1 本地基础 → CP2 DLsite 登录（WebView2 窗口）→ CP3 已购同步 → CP4 下载 → CP5 解压 → CP6 Steam → CP7 验收（详见接入方案 §2、§8）。

| 风险/未知 | 分类 | 影响 | 建议 / 验证 |
|---|---|---|---|
| WebView2 窗口能否通过 DLsite 人机/二步验证 | 真实验证依赖 | 阻塞 CP2 | CP2 由用户实测 M1；失败则停并走替代路线 |
| 会话有效期、续期 | 真实验证依赖 | CP2 体验 | M2；无续期机制则过期提示重新登录 |
| 非公开 Play 接口可能变动 | 可在架构内处理 | 维护成本 | 适配器隔离 + 契约测试 + 失败时保留旧数据并提示 |
| DLsite 条款灰色地带 | **需要用户选择**（D2） | 全部 DLsite 在线能力 | 手动/低频、不绕过验证、不解析官方软件 |
| 原始下载方式、分割格式、续传 | 真实验证依赖 | 阻塞 CP4/CP5 承诺 | M4；Play 接口只给优化版，不能当原始文件 |
| RAR/分卷需外部 7-Zip | **需要用户选择**（D4） | CP5 格式范围 | 7-Zip LGPL + unRAR 限制，需附许可 |
| 凭据超 2560 字节 | 可在架构内处理 | CP2 | 只存必要 Cookie；超限分片 |
| 同步误删、覆盖编辑、串号、隐私遗漏 | 可在架构内处理 | 数据安全 | 接入方案 §4.2、§6；Pytest 覆盖 |
| Steam 私密资料 + 自己 key | 真实验证依赖 | CP6 | M5；不可取时明确提示 |
| Python 3.14 下 pywebview/pythonnet 的 wheel 可用性 | 可在架构内处理 | CP1 依赖锁定 | CP1 先验证；必要时改用兼容的 Python 次版本（ARCHITECTURE §7 已允许） |
| ROADMAP 与大纲范围不一致 | **需要用户选择**（D5） | 文档门禁 | 确认后统一修改 |

当前没有阻塞检查点 1 的问题。

## 7. 需要用户决策
| # | 决策 | 选项 | 推荐 |
|---|---|---|---|
| D1 | DLsite 登录方式 | A. Atlas 拉起 WebView2 登录小窗口，你亲自登录（新增 pywebview 类依赖，主界面不变）；B. 不登录，只导入你已下载的本地文件夹；C. 手动粘贴 Cookie | **A**；A 失败时退到 B。C 不推荐 |
| D2 | 是否接受使用 DLsite Play 非公开接口读取自己的已购库 | 接受（手动/低频、不绕过验证）/ 不接受（只用 B） | 由你决定；风险见能力矩阵 E1 一行 |
| D3 | Steam 接入方式 | 你自己申请 Web API Key + OpenID/手动 SteamID | 推荐此方案（目前唯一的官方路线） |
| D4 | CP5 是否允许引入 7-Zip 处理 RAR/分卷 | 允许 / 只支持 ZIP | 等 M4 看到真实格式后再定也可以 |
| D5 | Phase 1 人工验收是否通过；ROADMAP 是否按大纲把“DLsite 下载解压”从 Phase 6 移入 Phase 2 | 确认 / 修改 | 确认后由 CP1 一并更新 ROADMAP |

## 8. 是否进入检查点 1
建议进入，条件：用户确认本方案与 D5。D1–D4 可在 CP2 开始前再定。

## 9. 变更范围说明
本次只新增/修改文档与 `work/phase2-cp0/` 下两个实验脚本及其结果文件；**没有修改任何应用代码、测试、Demo 行为、依赖或 lockfile**，没有实现真实登录、同步、下载或解压。ROADMAP 仅更新状态行与本报告链接。
