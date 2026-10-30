# Phase 2 接入方案（建议稿，待用户确认）

日期：2026-10-30 · 状态：用户已确认方向（决定见 §0）；检查点 1 已按本方案落地，差异见 §10，其余部分仍是后续检查点的计划。能力依据见 [能力矩阵](PHASE2_CAPABILITY_MATRIX.md)（下文 E*/M* 编号同该文），结论与待决策见 [检查点 0 报告](PHASE2_CHECKPOINT0_REPORT.md)。

## 0. 用户决定（2026-10-30）
| # | 决定 | 对方案的影响 |
| --- | --- | --- |
| D1 | **（2026-10-31 更新）不能让用户感觉是在网页上登录**：在 Atlas 面板输入账号密码，由 Atlas 交给隐藏浏览器；保留网页登录作为备用。用户接受密码经过 Atlas 和代为填表 | 见 §3.3，是检查点 2 的验收条件 |
| D2 | 接受使用 DLsite Play 非公开接口读取用户自己的已购库 | 保持手动/低频、单线程、不绕过任何验证 |
| D3 | Steam 使用用户自己申请的 Web API Key | 按 §3.2 |
| D4 | 同意以后引入 7-Zip 处理 RAR 与分卷 | 检查点 5 按真实样本决定格式范围，随程序附许可信息 |
| D5 | Phase 1 验收通过；“DLsite 一键下载解压”移入 Phase 2 | ROADMAP 已更新 |

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
### 3.1 DLsite 登录（检查点 2 已实现，真实站点待用户验证）
| 步骤 | 前端（浏览器页） | 本地服务 | 隐藏浏览器进程 | 存储 |
| --- | --- | --- | --- | --- |
| 1 | 面板收集账号密码，`POST /sources/dlsite/login`（CSRF），接受后立即清空 | 校验；账号与已知哈希不同时返回 409 待确认 | — | — |
| 2 | 每 700 ms 询问本地状态 | 拉起进程，账号密码经标准输入传入 | 隐藏打开登录页；确认地址是 `https://login.dlsite.com/login` 才填写并提交 | — |
| 3 | 需要验证时提示“回到验证窗口” | 记录状态 | 仅在平台要求时显示窗口 | — |
| 4 | — | — | 登录后收集 Cookie 并清除，经标准输出交回，退出 | — |
| 5 | 显示已连接 | 过滤 Cookie（只留平台域，去掉分析类），用 Play 接口确认；结果仍属当前尝试才保存 | — | 分片写入 Windows 凭据管理器，数据库只存引用和账号哈希 |
| 6 | 显示状态 | 启动时校验一次；401 → 需重新登录，网络/限流 → 暂时无法验证，存储故障单独说明。不自动重新登录 | — | 读取 |
| 7 | 点断开 | 先提交“已停用”，再删凭据；删除失败可重试，重启也不会恢复 | — | 删除 |

**备用网页登录**（`POST /sources/dlsite/login/window`）：显示同一窗口，用户直接在 DLsite 页面登录，Atlas 不接触密码，但也无法识别账号（换号确认不适用）。用于表单变化或用户不想在 Atlas 输入密码的情况。

### 3.2 Steam
- 身份：OpenID 2.0（`return_to=http://127.0.0.1:<port>/api/v1/sources/steam/openid/callback`，按规范校验 `check_authentication`）；若回环回调不被接受则改为手动输入 SteamID/个人资料链接。**[待验证]**
- 库访问：用户自行申请 Web API Key，经 Atlas 设置页输入（只发往本地服务，不回显、不进日志），存凭据存储。不代管或共享 Atlas 自己的 key。
- 不需要 Steam 密码；Atlas 不接触 Steam 登录凭据。

### 3.3 登录体验要求（D1）
- 正常路径全程在 Atlas 面板内，看不到网页、窗口或地址栏。
- **例外**：人机验证和二步验证只能由用户本人完成，此时才显示窗口，先在面板说明。如果每次登录都出现，必须告诉用户，由用户决定是否接受。
- 不注入样式，不做账号资料读取，脚本操作仅限填写并提交；每次点击只提交一次，不绕过任何验证。

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

## 10. 检查点 1 实际落地与本方案的差异
后续检查点以 [LOCAL_API.md](LOCAL_API.md) 和代码为准。

| 方案 | 实际 | 原因 |
| --- | --- | --- |
| ARCHITECTURE §5 游标分页 | 偏移窗口分页（`offset` + `limit`，排序以 ID 收尾） | 虚拟滚动要能跳到任意位置、返回时恢复位置；游标只能顺序读 |
| ARCHITECTURE §6 启动 bootstrap + HttpOnly Cookie | Host + Origin + Sec-Fetch-Site + 进程级 CSRF 令牌 | 本检查点无敏感操作，且无桌面启动器发放 bootstrap。**检查点 2 处理凭据前需重新评估是否补上** |
| §4.1 `source_accounts`、`work_files`、`library_entries` | 按方案建表；`source_accounts` 暂无写入方 | 明确账号归属边界；未连接时为空 |
| ARCHITECTURE §4 `source_observations`、`playtime_observations` 等观测表 | 未建。来源字段直接存在 `works` | 没有消费者；检查点 3/6 需要时用迁移增加 |
| ARCHITECTURE §4 `profiles` 表 | 未建。一个数据库就是一个资料库，账号隔离靠每个 profile 一个目录 | 比表内隔离更不容易串库 |
| 任务表（§4.1、§7） | 未建，只保留 §7 契约 | 检查点 4 才有执行方 |
| 凭据存储（§5） | `backend/app/core/credentials.py` 提供读/写/删接口，超限直接报错。分片、会话保存未实现，无 API 调用它 | 只建边界 |
| `Game.file` 改为 `files` | `file` 保留（第一个文件），详情另加 `files[]` | 不改动 Demo 与卡片 |
| 名称排序 | 规范化后按码位，不是拼音/五十音 | 不为此新增依赖；已写入 API 说明 |
| ARCHITECTURE §1 OpenAPI 生成 TS 类型 | 未做，前端类型手写，靠端到端测试保证一致 | 检查点 2 接口增多前建议补上 |

后续检查点必须遵守：同步只写 `works`、`work_files`、`library_entries`，只通过 `repositories.works.upsert_source_metadata`；新作品默认 `quarantined`；普通读取一律走 `ORDINARY` 条件；凭据只经 `core/credentials.py`。

## 11. 检查点 2 与本方案的差异
| 方案 | 实际 | 原因 |
| --- | --- | --- |
| 用户在可见的 WebView2 窗口登录 | 默认在 Atlas 面板输入，隐藏浏览器提交；窗口改为例外与备用 | D1 更新 |
| 账号指纹来自平台 | 账号密码登录时取用户输入账号的哈希（按资料库加盐）；网页登录无法识别 | 不为此读取账号资料 |
| 启动 bootstrap + HttpOnly 会话 | **本点不补，理由见检查点 2 报告 §5** | 接口从不返回会话或密码；防范对象已由现有边界覆盖 |

## 12. 检查点 3 实际落地
见[检查点 3 报告](PHASE2_CHECKPOINT3_REPORT.md)。与 §4 的差异：
- 新作品直接进入普通作品库（用户决定，构建阶段），不进待确认区。
- 不写 `work_files`：真实文件列表留给检查点 4，避免为此多发请求。
- 观测表仍未建立，来源字段直接写在 `works`。

后续检查点须遵守：同步只经 `upsert_source_metadata(keep_missing=True)`；不解析来源编号；类型映射集中在 `domain/dlsite_works.py`。

## 13. 检查点 4 实际落地
见[检查点 4 报告](PHASE2_CHECKPOINT4_REPORT.md)。与 §7 的差异：
- 状态比草案多了 `reauth_required` 和 `interrupted`。`paused` 已实现，真实平台的续传待验证。
- 没有写 `work_files`：分卷信息在请求时读取，不提前为全库取下载地址。任务记录在 `download_tasks`。
- 没有 `local_paths` 表：沿用检查点 2 的文件夹设置，任务创建时把路径固定下来。
- API 路径是 `/api/v1/downloads`，不是通用的 `/tasks`：解压的形态等检查点 5 再定。

后续检查点须遵守：下载地址不持久化；完成不等于已安装；解压不能改动 `download_tasks` 的完成语义。
