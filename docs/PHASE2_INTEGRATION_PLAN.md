# Phase 2 接入方案（建议稿，待用户确认）

日期：2026-10-30 · 状态：**建议方案，尚未实现，也未并入正式架构基线**（[ARCHITECTURE.md](ARCHITECTURE.md) 不因本文自动改变）。能力依据见 [能力矩阵](PHASE2_CAPABILITY_MATRIX.md)（下文 E*/M* 编号同该文），结论与待决策见 [检查点 0 报告](PHASE2_CHECKPOINT0_REPORT.md)。

## 1. 当前实际架构与必须保留的约束
- **已落地**：只有前端（Vite 8 + React 19 + TS strict，TanStack Query/Virtual，Tailwind 4），`npm run preview` 在 127.0.0.1:4173 提供 Demo。**仓库内没有任何后端代码、数据库或 Python 依赖清单**；ARCHITECTURE §1–§6 的 FastAPI/SQLite 设计仍是计划。
- **必须保留**：单个绑定回环地址的 FastAPI 服务托管前端静态构建；前端不直读 SQLite、平台文件或密钥；Host/Origin 限制 + 启动会话 + CSRF；服务端统一可见性策略；Steam 文件只读；密钥与会话存 Windows 凭据存储；Demo 独立数据。
- **本方案唯一新增的运行组件**：一个由后端按需拉起的 **WebView2 登录小窗口**，只用于 DLsite 登录（见 §3）。主界面仍是浏览器页面，不改为桌面容器，不换路由或状态方案。此项需用户决定（报告 D1）。

### 现有实现 → 后续扩展点
| 现有实现（文件/符号） | 现状 | Phase 2 扩展点 | 检查点 |
|---|---|---|---|
| `frontend/src/lib/data/types.ts` · `LibrarySource { mode: 'demo' \| 'real' }` | 只有 Demo 实现 | 新增 `real-source.ts`：同一接口，经 `fetch('/api/v1/...')` 实现；页面与 hooks 不变 | CP1 |
| `lib/data/hooks.ts` · `demoRoot = ['library','demo']` | 查询键以 demo 为根 | 真实模式用 `['library','real', profileId, ...]`，切换模式/账号时清空对应前缀 | CP1 |
| `lib/data/demo-source.ts` · 前端可见性过滤 | 仅适用于合成数据 | 真实模式下过滤移到后端；前端不再拿到私人条目 | CP1 |
| `lib/data/types.ts` · `Game.file: { version, sizeBytes } \| null` | 单文件假设 | 真实模式改为 `files: WorkFile[]`（版本/语言/分卷/大小可为 null），作品与文件分离 | CP3–CP4 |
| `lib/data/types.ts` · `WorkCapabilities`、`installed` | 演示能力按作品 | 由后端按 product.json 标志与实测能力填写；`unknown` 不写成 false | CP3 |
| `lib/data/demo-edits.ts` · localStorage 版本化编辑 | 演示编辑 | 真实编辑写入后端 `local_preferences`，与来源元数据分表 | CP1 |
| `lib/data/demo-connections.ts` · `ConnectionState` 5 态 | 演示状态 | 真实状态扩为 `disconnected/authenticating/connected/reauth_required/error`，来自后端 | CP2 |
| `lib/data/demo-tasks.ts` · `TaskPhase`、单计时器 | 前端计时器伪造进度 | 真实任务状态由后端持有，前端轮询/SSE 只读；进度未知为 null | CP4–CP5 |
| `features/demo-services/sources-dialog.tsx`、`tasks-dialog.tsx` · `demoEnabled` | Demo 关闭时显示“尚未接入” | 真实模式接入真实连接/任务，复用现有组件与文案 | CP2/CP4 |

## 2. 推荐路线
1. **CP1 本地基础**（不依赖任何平台决定）：FastAPI + SQLite + Alembic，平台中立作品模型、`work_files` 表、个人记录分表、真实/Demo 数据目录隔离、凭据存储边界（§5）、`real-source.ts`。用合成“真实模式”数据测试。
2. **CP2 DLsite 登录**：WebView2 登录窗口 → 后端取 `.dlsite.com` 会话 Cookie → 存凭据存储 → 用 Play 接口 401/200 判断会话有效。人工 M1/M2。
3. **CP3 DLsite 同步**：Play `content/count` → `content/sales`（增量 `last`）→ `content/works` 每批 100 顺序请求；必要时 product.json 补充文件格式/大小/适用性。人工 M3。
4. **CP4 下载**：先由 M4 确认原始文件下载方式；仅针对用户选择的作品；流式写入临时文件，大小核对。
5. **CP5 解压**：首批 ZIP（cp932/UTF-8），RAR/分卷/SFX 视 M4 样本与 D4 决定。
6. **CP6 Steam**：用户自己的 Web API Key + SteamID（OpenID 或手动输入），GetOwnedGames/GetRecentlyPlayedGames，授权的 Steam 目录只读安装检测，`steam://` 用户触发入口。人工 M5。
7. **CP7 全链路验收**。

**替代路线（若 D1/D2 不接受 DLsite 登录）**：DLsite 改为“本地文件夹导入”——用户选择已有下载目录，按文件夹名中的作品编号（RJ/VJ/BJ 等）识别，公开 product.json 补元数据；无需登录，但无法得到已购清单、无法下载。Steam 路线不受影响。

## 3. 认证与会话
### 3.1 DLsite 时序（建议；CP2 前均未实现）
| 步骤 | 前端（浏览器页） | 本地服务 | WebView2 登录窗口 | DLsite | 受保护存储 |
|---|---|---|---|---|---|
| 1 | 用户点“连接 DLsite” → `POST /api/v1/sources/dlsite/auth`（CSRF） | 校验后拉起登录窗口，使用 Atlas 专用 profile 目录；状态 `authenticating` | — | — | — |
| 2 | 轮询状态 | — | 打开 `https://login.dlsite.com/login`，用户亲自输入、通过人机/二步验证 **[待验证 M1]** | 设置 `.dlsite.com` Cookie | — |
| 3 | — | 检测到已登录（导航到登录后页面）后，从 CookieManager 读取 `.dlsite.com` 必要 Cookie **[HttpOnly 读取待验证]** | 读取后立即清除窗口 profile 的 Cookie 并关闭 | — | — |
| 4 | — | 以该 Cookie 请求 `play.dlsite.com/api/authorize` 与 `content/count`；200 → `connected`，401 → `error` | — | 返回 200/401 | 成功后写入（§5），只存 Cookie，不存密码 |
| 5 | 显示“已连接”，不显示账号名/邮箱以外的敏感信息（默认不显示账号） | 重启后从存储读取并探测有效性 | — | — | 读取 |
| 6 | 401 → 显示“需要重新登录” | 状态 `reauth_required`，**不自动重试登录、不自动续期** | — | — | 保留至用户断开 |
| 7 | 用户点“断开” | 删除凭据条目，清空该来源的会话内存与登录窗口 profile；**不删除已导入作品与个人记录**（保留为“未连接来源”的作品，见 §6） | — | — | 删除 |

- 若 WebView2 中无法通过 Cloudflare/验证（M1 失败），**停止并报告**，不尝试绕过；改走替代路线或由用户另行决定。
- 浏览器页面始终拿不到 Cookie；登录窗口不注入脚本读取密码字段。
- 防串号：首次连接记录来源账号的稳定标识（若 Play 接口提供用户 ID，存其哈希）；重新登录得到不同标识时，暂停同步并要求用户确认“新账号/替换账号”。具体标识字段待 CP2 实测。

### 3.2 Steam
- 身份：OpenID 2.0（`return_to=http://127.0.0.1:<port>/api/v1/sources/steam/openid/callback`，按规范校验 `check_authentication`）；若回环回调不被接受则改为手动输入 SteamID/个人资料链接。**[待验证]**
- 库访问：用户自行申请 Web API Key，经 Atlas 设置页输入（只发往本地服务，不回显、不进日志），存凭据存储。不代管或共享 Atlas 自己的 key。
- 不需要 Steam 密码；Atlas 不接触 Steam 登录凭据。

## 4. 同步、分类与数据模型
### 4.1 最小模型增量（在 ARCHITECTURE §4 基础上）
| 表 | 新增/调整 |
|---|---|
| source_accounts | id、platform、account_ref（凭据存储目标名，非秘密）、account_fingerprint（哈希，可空）、state、last_verified_at |
| games（作品） | 保持 `unique(platform, external_id)`；增加 `raw_work_type`、`age_category`；`kind` 由映射得到 |
| work_files | id、game_id、label、version、language、part_index/part_count、size_bytes(nullable)、format(nullable)、availability(`downloadable`/`viewer_only`/`unknown`)、observed_at |
| library_entries | 增加 `source_account_id`；`ownership_status` 沿用 unknown/observed_owned/not_currently_observed |
| download_tasks / extract_tasks | §7 状态；关联 game_id + work_file_id + target_root_ref |
| local_paths | id、purpose(`download_root`/`extract_root`/`steam_root`)、path（仅后端）、created_by_user_at |

### 4.2 同步语义
- 一次同步 = 一个 `sync_job`；每批 100 件短事务提交；中断标记 `partial/interrupted`。
- 返回结果中缺失的作品 → `not_currently_observed`，**不删除作品、个人记录与本地文件**。
- 同步只写来源元数据与观测表，**不覆盖** `local_preferences`（评分、备注、收藏、隐私、自定义标题）。
- 新作品默认 `quarantined`（AGENTS：DLsite 新条目默认进待确认区）；待确认条目不联网补元数据与封面。
- 节流：手动触发；顺序请求；429/5xx 有限退避（最多 3 次）；401 立即 `reauth_required`。

### 4.3 DLsite `work_type` → Atlas 类型（建议，保留原始值）
| Atlas | DLsite 代码 |
|---|---|
| 游戏 | ACN、ADV、RPG、SLN、STG、PZL、QIZ、TBL、TYP、DNV、ETC |
| 图像（漫画/CG） | MNG、SCM、ICG、WBT、VCM |
| 音声 | SOU、MUS |
| 视频 | MOV |
| 其他 | NRE、PBC、TOL、IMT、AMT、ET3 及任何未知代码 |

DNV（数字小说）归游戏、VCM（有声漫画）归图像、MUS（音乐）归音声属于判断，CP3 由用户在真实库上确认；用户可逐件改类型且同步不覆盖。

## 5. 凭据存储与本地服务边界
- **存储**：Windows Credential Manager（generic，`LibraryAtlas/<platform>/<account_ref>`）。单条 ≤ 2560 字节（E14 实测）。Steam key 单条即可；DLsite 只保存会话必需的 Cookie（过滤掉分析/广告 Cookie），超过 2560 字节则按 `#0..#n` 分片写入并带版本与长度校验。DPAPI 文件仅作为分片不可行时的备选，需另行说明。
- 任何失败都返回明确错误（`credential_store_unavailable`），**不降级为明文文件、数据库或 localStorage**。
- 凭据只在后端内存中短暂存在；请求日志对 Cookie/Authorization/查询参数中的 key、签名下载 URL 全部脱敏；错误上报只带错误码与 request_id。
- **本地服务**：沿用 ARCHITECTURE §6（回环绑定、Host/Origin 白名单、bootstrap 会话 + CSRF、无通配 CORS、DNS rebinding 检查）。触发登录窗口、写凭据、下载、解压、打开目录均属敏感写操作，必须带会话 + CSRF。
- **出站白名单**：DLsite 仅 `login.dlsite.com`、`play.dlsite.com`、`play.dl.dlsite.com`、`www.dlsite.com` 及 CP4 实测确认的下载主机；Steam 仅 `api.steampowered.com`、`steamcommunity.com`（OpenID）、`cdn.akamai.steamstatic.com`。不提供“任意 URL 下载”接口；重定向逐跳校验主机。
- **文件路径**：下载根与解压根由用户在设置中选择并分别登记；所有写入都在登记根目录下，resolve 后校验包含关系；不扫描整盘；Steam 根目录只读。

## 6. 模式、账号与个人记录隔离
- Demo 与真实使用不同数据目录（如 `%LOCALAPPDATA%\LibraryAtlas\demo` 与 `...\real`）、不同 SQLite 文件、不同查询键前缀、不同任务队列；真实模式失败时显示真实错误或空库引导，**不回退 Demo**。
- 断开来源：删除会话凭据；作品与个人记录保留并标“来源未连接”；用户可另行选择“移除该来源的作品”（需确认范围，CP2 设计 UI）。
- 换账号：检测到不同账号指纹时不合并，要求用户选择；不同账号的 library_entries 分开。
- 迁移前自动备份（ARCHITECTURE §6）；不可逆清理需事前说明与确认。

## 7. 任务状态契约草案
| 任务 | 状态 | 说明 |
|---|---|---|
| sync | queued → running → succeeded / partial / failed / cancelled / interrupted；附 `reauth_required` 错误码 | 进度 = 已处理批次 / 总批次（总数来自 count，未知则 null） |
| download | queued → resolving_link → downloading → verifying → done；failed / cancelled；`paused` 仅在 M4 证实可续传后提供 | 临时文件 `*.part`，完成后原子改名；大小核对；链接过期回到 resolving_link |
| extract | queued → checking（格式/空间/冲突）→ extracting（暂存目录）→ committing → done；failed / cancelled；`needs_password`、`missing_parts` | 失败只清理本任务暂存目录；可单独重试解压不重下载 |

- API 形态沿用 ARCHITECTURE §5：`POST` 返回 202 + task_id；`GET /api/v1/tasks?active=1`；`POST /api/v1/tasks/{id}/cancel|retry`。
- 前端只消费后端状态；未知进度显示不定进度条；“已下载”≠“已安装”，“已解压”≠“可启动”；打开目录与执行文件是不同的用户动作，CP5 不提供执行文件。

## 8. 检查点门禁调整建议
| 检查点 | 前置条件 | 交付物 | 门禁调整 |
|---|---|---|---|
| CP1 | 用户确认本方案；D5（Phase 1 验收）确认 | 后端骨架、模型/迁移、凭据存储模块（假值测试）、real-source、隔离 | 不依赖 D1–D4，可先行 |
| CP2 | D1、D2 | 登录窗口、会话存取/探测/断开 | M1 失败即停，报告替代路线 |
| CP3 | CP2 通过 | 同步、分类、真实页面 | M3；分类映射用户确认 |
| CP4 | CP3 + M4 | 下载队列 | 续传/暂停仅在 M4 证实后提供 |
| CP5 | CP4 + D4 | 解压 | 支持矩阵按真实样本定，不预先承诺 RAR/7z |
| CP6 | D3 | Steam 接入 | 可与 CP2–CP5 并行规划，但按用户授权顺序执行 |
| CP7 | 以上全部 | 全链路验收 | 同 Phase 2 大纲 |

ROADMAP 现有 Phase 2 行（含后端骨架与“能力调查”）与 Phase 6 中的“DLsite 一键下载解压（可选）”与本大纲不一致：大纲把下载解压放进 Phase 2 CP4–CP5。建议用户确认后再统一修改 ROADMAP（D5）。

## 9. 不支持与未验证能力（摘要）
- **不支持**：后端代填密码登录、读取系统浏览器 Cookie、解析 DLsite Nest 数据、Atlas 下载 Steam 游戏、自动破解/猜测归档密码、自动运行 `.exe`。
- **未验证**：WebView2 内能否完成 DLsite 登录、会话有效期、原始文件下载方式与续传、DLsite 分割文件格式、Steam 私密资料 + 自己 key 的行为、OpenID 回环回调、`steam://` 各命令当前可用性。
