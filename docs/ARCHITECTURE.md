# Library Atlas 技术架构草案

状态：Phase 0 已审核；2026-10-30。§1–§7 是总体设计；**实际落地情况见 §10**，真实平台接入尚未实现。

## 1. 运行结构与决策
采用本地单体、分层模块架构。React 处理呈现与交互；FastAPI 统一执行可见性、业务规则、同步和文件访问；SQLite 保存结构化资料。1500 条规模不需要微服务、Redis 或远程数据库。

正式运行：浏览器 → `http://127.0.0.1:<port>` → FastAPI `/api/v1/*`、受控图片路由与 Vite `dist/`。仅绑定回环地址，启动时检查端口占用；API 未命中返回 JSON 404，只有非 API 页面路由回退 index.html。正式环境不运行 Vite dev server。开发期 Vite 代理 `/api` 到 FastAPI，开发服务器同样绑定回环；不启用宽泛 CORS。

前端只通过同源 HTTP JSON 访问业务数据。Python Pydantic 模型产生 OpenAPI，Phase 1 固定生成 TypeScript 契约流程；API 枚举和空值含义唯一维护，避免手写双份漂移。同步用后端作业 + 轮询，首版不需要 WebSocket。

## 2. 拟议目录（Phase 1 才创建代码）
```text
AGENTS.md
docs/{PRODUCT,DESIGN,ARCHITECTURE,ROADMAP}.md
frontend/
  src/{app,components/ui,features,lib,styles}/
  tests/
  package.json / package-lock.json
backend/
  app/
    main.py
    api/                 # 请求模型、路由、统一异常
    domain/              # 可见性、分类、推荐、合并策略
    services/            # 用例、作业编排
    repositories/        # SQLite 持久化
    adapters/steam/      # 官方 Web API、本地只读扫描
    core/                # 配置、路径、密钥引用、日志
    migrations/
  tests/
pyproject.toml / uv.lock  # 拟选 uv；Phase 1 验证后锁定工具版本
tests/e2e/               # Playwright、合成 fixture、截图基线
scripts/                 # Windows 启动、构建和检查
```
前端 features 按 library、collections、backlog、recommendations、statistics、sync、privacy 划分；不得将数据库或 Steam 适配器逻辑写进路由/组件。

运行数据放 `%LOCALAPPDATA%\LibraryAtlas\profiles\<profile-id>\`：`library.sqlite3`、`cache/`、`backups/`、`logs/`；Demo 使用独立 `demo/`。不依赖 cwd，不在源码目录写用户资料。运行版本并非当前机器版本自动决定：Phase 1 验证 Node/Python 与依赖兼容性后固定 `.node-version`、`.python-version`、packageManager 和锁文件。

## 3. 数据流与同步
```text
官方 Web API / 本地只读文件 / 手动导入
  → 来源适配器（超时、限流、校验）
  → 标准化观测（来源、时间、完整度、能力）
  → 隐私隔离与合并预览
  → 单批次 SQLite 事务 + 同步摘要
  → 统一可见性查询 → 分类/推荐/统计 → API → UI
```
1. 本地扫描仅在已发现或用户指定的 Steam 根目录/库目录读取白名单文件，支持多个库、中文及空格路径；限制文件大小，拒绝越界路径/符号链接逃逸。不扫描整盘，不读登录凭据，不写 Steam 文件。
2. 按账号与 AppID 幂等合并；安装观测、所有权观测、本地编辑独立存储。安装文件不能证明所有权；某次 API 返回缺少条目不能证明撤销所有权。
3. 来源优先级按字段：用户名称/标签覆盖优先；所有权只由具备该能力的来源陈述；安装状态由成功扫描到的库范围陈述；游玩观测保留来源和采集时间，不跨来源累加。游玩总量下降记录异常，不静默取最大或删除历史。
4. 本地私人/隐藏标记始终独立；远端状态未知不覆盖已知状态，过期的非私密证据不得永久放行。新增/隐私冲突条目进入待确认区；已有用户明确普通标记可保留，但可靠远端私密观测优先隔离。
5. 一个账号同时一个同步写作业；网络阶段不持有数据库长事务。每来源分页/批次校验后短事务提交，取消/崩溃保留已提交批次并标记 partial，摘要列明影响范围。重启将 running 标记 interrupted，不伪装成功。
6. 429/5xx 使用有上限的指数退避和抖动（最多 3 次，尊重 Retry-After），401/403 不循环重试；默认并发 2，可调整。接口配额待调查，不能宣称这是 Valve 允许值。

## 4. 本地模型草案
以下都是 **Atlas 自有字段**，不是 Steam 响应字段。主键采用内部 ID；SteamID 用字符串避免 JavaScript 精度问题，AppID 用正整数。日期存 UTC、展示转换；时长为非负整数分钟或 null；null 不等于 0。

| 表 | 主要字段/约束 |
| --- | --- |
| profiles | id、mode(real/demo)、steam_id(nullable)、display_name；MVP 单活动账号 |
| games（作品） | id、platform(steam/dlsite)、external_id、unique(platform,external_id)、kind(game/image/video/audio/other)、maker、release_date(nullable)、canonical_title、metadata_status；不直接包含账号隐私。原 steam_app_id 由 platform=steam + external_id 表示 |
| library_entries | id、profile_id、game_id、ownership_status(unknown/observed_owned/not_currently_observed)、first_seen_at；unique(profile_id,game_id) |
| local_preferences | entry_id(unique)、visibility(normal/hidden/private/quarantined)、visibility_confirmed_at、title_override、backlog_status、priority、notes、version |
| source_observations | id、entry_id、source、field_name、value_json、observed_at、scope、confidence；校验字段白名单与大小 |
| external_visibility | entry_id、source、hidden_state、private_state(true/false/unknown)、observed_at、evidence_ref；初始全 unknown，不假设可取得 |
| installations | entry_id、library_root_ref、installed_state、observed_at；本地路径不对普通 API 输出 |
| tags / entry_tags | 名称、来源、entry_id、tag_id、locked、rule_id；多对多去重 |
| classification_rules | id、version、condition_json、target_tag_id、enabled；限制为可校验 DSL，不执行用户代码 |
| collections / collection_members | profile_id、name、visibility(normal/private)、entry_id、position；联合唯一成员 |
| playtime_observations | entry_id、source、total_minutes、recent_minutes、window_description、observed_at；不推导单次会话 |
| recommendation_feedback | entry_id、feedback_type、created_at；仅本地使用 |
| sync_jobs / sync_source_results | 状态、来源、计数、起止时间、脱敏错误码、complete/partial/unknown |
| assets | game_id、kind、local_ref、etag、fetched_at、access_scope；私人请求独立校验 |
| settings / schema_migrations | 配置键值（不含密钥）、schema 版本 |

索引优先 profile_id/visibility、steam_app_id、backlog_status、tag 关联、observed_at。使用 SQLite 外键和 CHECK 约束；游戏删除不作为同步动作。迁移选 SQLAlchemy + Alembic，Phase 1 验证版本与 SQLite 能力后锁定；启用 WAL、busy_timeout 和短事务，序列化写入。备份使用 SQLite 在线备份机制，不在 WAL 活跃时只复制主文件。

## 5. 拟议 API 与状态契约
| Atlas API（并非 Steam 接口） | 用途 |
| --- | --- |
| GET /api/v1/library | 搜索、筛选、排序、分页；默认 ordinary scope |
| GET /api/v1/games/{id} | 详情；先应用可见性，不可见返回一致 404 |
| PATCH /api/v1/entries/{id}/preferences | 本地状态；version 冲突返回 409 |
| GET/POST/PATCH /api/v1/collections | 收藏夹与成员管理 |
| POST /api/v1/classification/preview 或 /apply | 预览/提交规则；申请版本匹配 |
| GET /api/v1/recommendations 或 /statistics | 与列表共用可见性策略 |
| POST /api/v1/sync-jobs | 202 + job_id；重复请求幂等键；活动任务冲突 409 |
| GET /api/v1/sync-jobs/{id} | queued/running/succeeded/partial/failed/cancelled/interrupted |
| POST /api/v1/sync-jobs/{id}/cancel | 请求取消，明确已提交批次 |
| POST /api/v1/privacy/session | 用户显式进入私人空间后取得短期会话 |
| GET /api/v1/assets/{id} | 根据当前访问域校验后发送图片 |

分页使用稳定排序（用户排序 + id）及游标，limit 上限 100；响应包含 items、next_cursor、filtered_count、data_as_of、source_coverage、mode。普通计数在过滤后计算，不能泄漏私人总数。错误统一 code/message/request_id/retryable，不携带上游 URL 中的密钥。异步作业错误使用相同脱敏约定。

## 6. 隐私、安全与缓存
- 统一服务端策略：普通域只允许 normal；hidden 管理域显式访问；private/quarantined 必须持有私人会话。集合、推荐、统计、搜索建议、导出、图片均调用同一策略。不能通过 include_private=true 单独绕过。
- 私人空间短期令牌仅驻内存，离开即撤销；刷新关闭。禁止私人内容进入 URL、localStorage、service worker、普通查询缓存或通知。私人响应/图片 Cache-Control:no-store。普通封面缓存也不作为公开静态目录暴露；变更隐私立即失效查询、推荐和图片授权。
- Steam API Key 仅后端使用，通过 Windows Credential Manager 保存引用；每个请求/日志做脱敏，失败时不回退明文。导出不含密钥，备份不含凭据；数据库与封面本身不承诺加密，继承当前 Windows 用户访问控制。防止同用户恶意软件访问不在 MVP 保证内。
- 仅回环不等于身份校验：限制 Host/Origin，写请求使用启动会话 + CSRF 校验；拒绝跨站请求，不允许通配 CORS。启动会话通过一次性 bootstrap 换取 HttpOnly、SameSite=Strict Cookie，随后移除 URL 中 bootstrap；日志不记录它。验证 DNS rebinding 与会话失效。
- 下载器只允许已验证的 Steam/CDN host、HTTPS、限制重定向/大小/超时/内容类型，防 SSRF 和路径穿越；用户导入不能任意下载 URL。私人/待确认游戏默认不自动联网补图或补元数据。
- 缓存初始策略：库存/游玩 15 分钟新鲜期、元数据 7 天、普通图片 30 天（支持 ETag 时使用）；这是 Atlas 本地策略，不是远端配额承诺。过期可展示旧值和时间，只有成功响应更新 last_success；手动同步去重并限流。失败短暂负缓存 5 分钟，私人结果不进共享缓存。
- 前端查询键包含 profile/mode/visibility_scope/filters/version；退出私人空间、切换模式或账号清空相关缓存，取消在途请求，拒绝迟到响应重新填充。
- 自动迁移前备份，保留最近 5 份；备份可能含私人数据，应明确提示和限制访问。恢复需完整性检查、schema 兼容验证、用户确认；运行时停写并原子替换。清缓存不可删除用户偏好；导出默认只含普通条目，私人导出另行确认且不属于 MVP 必需功能。

## 7. 技术能力证据与待调查风险
2026-10-30 查阅官方资料；仅确认文档存在与产品语义，**未执行真实账号验证**。

| 项目 | 已知/待调查 | 调查方法与降级 |
| --- | --- | --- |
| 库存与近期游玩 | 官方 IPlayerService 文档列出 GetOwnedGames / GetRecentlyPlayedGames；实际可见范围与字段完整度待测 | 用户授权测试账号，固定脱敏 fixture，覆盖无权限/空/部分响应；失败保留旧值 |
| Steam 私密与隐藏 | 官方帮助区分二者；未确认有适用于本项目的读取或回写能力 | 使用普通/隐藏/私密组合做受控矩阵，对比官方 API 与只读文件；不能可靠识别则保持 unknown + 手动确认；MVP 不回写 |
| 本地格式/目录发现 | 安装清单和库配置的格式、编码、版本稳定性未验证 | 多库、自定义盘、中文空格路径、损坏/占用文件 fixture；不可读时手动路径/导入，不把安装当拥有 |
| 元数据/封面 | 可用端点、许可、地域/语言差异、失效规则及限流待验证 | 先核对官方文档与使用条款，再小量试验；未通过则手工标签+本地占位，不以未文档化商店端点保障 SLA |
| 游玩统计 | 最近窗口和累计值的可得性/更新时间待验证；历史会话不可假设存在 | 保存观测，标注覆盖；仅以后续快照建立趋势，不回填虚构历史 |
| 运行依赖 | 当前机器 Python 3.14.3 / Node 22.22.1 并非已验证项目基线 | Phase 1 测试依赖 wheel、锁定构建与 Windows 启动；必要时选择兼容 Python 次版本，不变更技术栈 |
| 1500 项与缩放 | 尚无运行实现/性能实测 | 合成数据性能 trace、虚拟化键盘测试、1920 和缩放矩阵；超预算先优化查询与渲染 |

官方依据：[IPlayerService 文档](https://partner.steamgames.com/doc/webapi/IPlayerService?language=english)、[Steam Private Games 帮助](https://help.steampowered.com/en/faqs/view/1150-C06F-4D62-4966)。帮助说明不能证明 API 提供对应状态。后续记录适配器能力为 supported/unsupported/unknown，逐项附实测日期和脱敏证据。

## 8. Phase 1 检查点 1 实施边界
用户明确将本轮收窄为纯前端 AppShell + Library（见 [执行规范](specs/PHASE1.md)），覆盖此前 Phase 1 含后端骨架的安排。正式产品仍采用上述 FastAPI 单服务架构；本轮使用 Vite 本地 dev/preview 供视觉评审，不是正式交付运行架构。未创建 Python、数据库或假业务接口。

前端 `LibrarySource` 是替换边界：组件 → TanStack Query hooks → Demo source → 先按 visibility=normal 过滤的查询结果。Demo 默认启用（`VITE_DEMO_MODE=false` 可关闭），默认生成规模 1500，`?size=5000` 启用压力场景。数据为固定种子、会话内存存储，收藏只保留至刷新。真实 source 尚未实现；这里的前端可见性过滤仅适用于合成数据，不能充当未来真实数据的安全边界。

图片分为三类：24 张本地原创 SVG 叙事插画、可见卡片按需生成的程序化 SVG、明确缺失的统一占位。SVG 不需 srcset，任意 DPR 下保持矢量清晰；未来位图源仍必须提供 sizes/srcset。字体依赖包打入 dist，通过 unicode-range 按需取本地 WOFF2，运行时不联网取字体。原始私人哨兵仅存在 Demo source 内部，普通 hooks 不返回它们；它们不是用户真实隐私资料。

## 9. 多平台扩展：DLsite（2026-10-30 用户决定，待 Phase 2 调查）
- **模型**：上表 games 改为平台中立的作品表；前端 `Game` 类型已包含 `platform`、`kind`、`maker`、`releaseDate`（类型名沿用历史名称，含义为“任意平台的作品条目”）。可见性、本地偏好、收藏、Backlog 与平台无关。
- **适配器**：`adapters/dlsite/` 与 Steam 并列，输出同一标准化观测；按 (platform, external_id) 幂等合并，缺项不删除库存。新条目进入 quarantined，直至用户确认。
- **会话凭据**（2026-10-31 用户决定更新）：用户默认在 Atlas 面板输入账号密码，经本地服务和进程管道交给隐藏的 WebView2 提交；验证码/二步验证由用户本人完成；另有备用网页登录。密码默认只用于本次尝试；用户勾选“记住”后存入 Windows Credential Manager，只用于登录，绝不返回前端。后端仅保存会话 Cookie 至 Windows Credential Manager 并以引用访问；不进数据库、日志、前端、导出或错误上报。会话失效返回明确的 `reauth_required` 状态，不自动重试登录。只读请求，限速，手动或低频触发。
- **打开作品**：后端按作品类型执行：游戏只启动用户确认并登记的可执行文件；其他类型交给系统默认程序或资源管理器。使用参数数组启动，不经 shell 拼接；扫描到的程序不自动运行。
- **下载解压（候选）**：仅限会话可访问的已购作品下载链接与 DLsite 主机白名单；断点续传、大小与完整性校验、限定写入目录；解压逐项校验目标路径（拒绝绝对路径与 `..`）、限制展开大小与文件数。需许可证认证的作品不处理授权。引入 7-Zip/unrar 等组件前另行征询。
- **待调查**：Nest 本地数据位置与格式（是否加密）、网站购买列表与下载链接的获取方式及稳定性、使用条款对自动化读取/下载的限制、作品编号格式、封面与元数据许可。结论写入 §7 能力表后再实现。

### 9.1 检查点 3 前端增量（演示，已实现）
- `Game` 增加 `sourceId`（与 `platform` 组合为身份，演示数据刻意让跨平台编号相同以验证不覆盖）、`capabilities`（download / extract / officialViewerOnly，按作品而非按平台硬编码）、`file`（version、sizeBytes，未知为 null）。`installed` 表示“本机可用”：Steam 为已安装，DLsite 为已下载，二者文案分开，下载完成不等于已安装或可启动。`lastPlayedAt` 为最近使用记录（游戏为游玩，其他为阅读/观看/收听，演示数据）。
- `selectDashboard` 为纯函数：先可见性过滤，再按范围（all / games / steam / dlsite-games / dlsite-media）聚合；每个范围对应一组 Library 筛选（新增 `kind=non-game`），计数一致性有单测。
- `demo-connections`、`demo-tasks` 为页面级单例外部 store（`useSyncExternalStore`）：一个任务服务、一个计时器，任务按作品去重，取消后不再完成，刷新丢弃未完成任务；完成结果写入演示编辑存储的 `downloaded`（v1 增量字段，不清空既有修改）。连接状态只保存粗粒度状态到 localStorage，不含任何凭据。
- 以上均为前端演示边界，不代表后端设计已落地。真实认证、会话存储、库同步、下载器与文件系统操作仍属 Phase 2 及以后，按 §9 的约束在后端实现。
- 检查点 4 补充：`VITE_DEMO_MODE=false` 时来源连接与下载任务弹层不渲染任何演示状态（只说明“尚未接入”），首页聚合查询也不执行；首页范围切换期间的占位数据以 `data-ready=false` / `aria-busy` 标示，测试与性能计时以真实结果到位为准。

## 10. Phase 2 检查点 1 实际落地（2026-10-30）
契约见 [LOCAL_API.md](LOCAL_API.md)，运行见 [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md)，与设计的差异见 [接入方案 §10](PHASE2_INTEGRATION_PLAN.md)。

```text
backend/app/
  main.py            应用工厂：API + 静态托管 + 统一错误 + 不含敏感信息的请求日志
  __main__.py        python -m app serve|check|init|seed-test
  api/models.py      Pydantic 请求/响应契约
  services/library.py  用例：行 → 契约对象；一次请求一个事务
  domain/            首页聚合、文本规范化（纯函数）
  repositories/works.py  全部 SQL；ORDINARY 可见性条件唯一定义处
  db/                schema、engine、bootstrap（校验/备份/迁移/印记）、Alembic 迁移
  core/              config、errors、security（请求边界）、credentials（凭据边界）
  testing/synthetic.py  合成样本，只由 seed-test 命令调用
frontend/src/lib/data/
  workspace.ts       模式选择
  api-client.ts      唯一的 HTTP 出口：错误分类、CSRF
  real-source.ts     真实数据源（实现 LibrarySource）
  hooks.ts           页面唯一入口；按模式分流，缓存键按模式隔离
```

- **已落地**：单一回环 FastAPI 服务托管 `frontend/dist`；SQLite（WAL、外键、CHECK、busy_timeout、显式事务）；SQLAlchemy Core + Alembic；迁移前在线备份；数据库 real/test 印记；服务端可见性；Host/Origin/CSRF 边界；Windows 凭据存储接口。
- **表**：`library_meta`、`sources`、`source_accounts`（空）、`works`、`work_files`、`library_entries`、`personal_records`。来源数据与个人记录分表，同步代码写不到个人记录。
- **未落地**：真实认证、同步、下载、解压、任务系统、私人空间、图片资产路由（封面现在只有合成样本的本地绘制与缺图占位）、Steam 适配器、观测表、收藏夹与分类规则。
- **Demo**：仍是纯前端，不需要服务。其可见性过滤只作用于合成数据，真实模式的可见性只在服务端。

## 11. Phase 2 检查点 2 实际落地（2026-10-31）
```text
backend/app/
  adapters/dlsite/browser.py     隐藏浏览器进程（独立进程，stdin/stdout JSON 行）
  adapters/dlsite/login_page.py  登录页状态判断（纯函数）
  adapters/dlsite/login_host.py  服务侧：启动进程、读事件
  adapters/dlsite/session.py     Cookie 过滤、编解码、有效性检查
  core/session_vault.py          凭据分片（清单最后写、最先删，校验长度和哈希）
  services/dlsite_auth.py        连接状态机：单一尝试、过期结果丢弃
  services/dlsite_factory.py     按 profile 装配真实或测试部件
  repositories/accounts.py       非敏感账号状态
  testing/fake_dlsite.py         假平台，仅 test 配置
```
- **已落地**：登录、备用网页登录、取消、验证窗口、会话保存与恢复、重新验证、断开与清理重试、换号确认。迁移 `0002` 增加 `source_accounts.cleanup_pending`。
- **未验证**：向真实站点提交后的全部行为，见[检查点 2 报告](PHASE2_CHECKPOINT2_REPORT.md)。
- **设置**：`app_settings` 表（迁移 `0003`）保存下载文件夹；`services/folders.py` 校验，`adapters/system/folder_dialog.py` 在独立进程打开系统选择窗口。`source_accounts.account_alias` 保存打码账号。前端路由 `/settings`，顶部 `AccountMenu`。
- **未落地**：作品同步、下载、解压、Steam。

## 12. Phase 2 检查点 3 实际落地（2026-10-31）
```text
backend/app/
  adapters/dlsite/library.py   Play 已购读取（固定地址）
  adapters/dlsite/covers.py    封面获取与缓存（主机白名单、限大小、不跟跳转、不带会话）
  domain/dlsite_works.py       响应 → 元数据，类型映射（纯函数）
  services/dlsite_sync.py      同步任务：单任务、分批短事务、会话代次校验
frontend/src/features/workspace/dlsite-sync.tsx
```
- 迁移 `0004`：`sync_jobs`、`source_accounts.last_synced_at`、`works.source_url`。
- 封面路由 `GET /api/v1/works/{id}/cover` 先走普通可见性，缓存在数据目录 `cache/covers`，文件名是地址的哈希。
- 作品库滚动时收起介绍、工具栏和顶栏（前端状态 + `:has()`）。
- **未落地**：下载、解压、Steam、缓存清理。

## 13. Phase 2 检查点 4 实际落地（2026-10-31）
```text
backend/app/
  adapters/dlsite/downloads.py   下载方案与文件流：逐跳校验主机，地址不出模块
  domain/download_names.py       文件名清理（纯函数）
  services/downloads.py          持久化队列：有限并发、尝试号、提交边界、崩溃恢复
  testing/fake_download_server.py 回环上的真实 HTTP 服务，只用于测试配置
frontend/src/features/downloads/real-downloads.tsx
```
- 迁移 `0006`：`download_tasks`。`active_key` 唯一，保证一个文件只有一个进行中任务。
- 文件先写 `<缓存>/<任务号>.part`，校验后移动到 `<作品文件夹>/<作品编号>/`，不覆盖。
- 前端只轮询任务列表；进度变化不触碰作品库查询，只有完成时才刷新。
- **未落地**：解压、安装、运行、Steam。

## 14. Phase 2 检查点 5 实际落地（2026-10-31）
```text
backend/app/
  adapters/system/archives.py  ZIP 与 7-Zip：列表、解压、路径语义、最终检查
  adapters/dlsite/product.py   公开作品记录（不带会话）
  services/extractions.py      解压任务：输入核对、暂存、提交、崩溃恢复
  services/update_checks.py    每天一次的更新检查（复用同步）
  services/gallery.py          介绍图：按需读取，保存一周，按序号取图
  db/engine.py                 writing()：写事务一开始就取得写锁
frontend/src/features/downloads/downloads-page.tsx  下载页与底部栏
frontend/src/features/game-detail/work-gallery.tsx  介绍图
```
- 迁移 `0007`：`extract_tasks`、`download_tasks.flow_id`。`0008`：`works.upgraded_at`、`gallery_json`、`gallery_checked_at`、`download_tasks.source_upgraded_at`。
- 7-Zip 是可选的外部程序，由用户安装，不随项目分发。
- **未落地**：安装、运行、Steam。

## 15. Phase 2 检查点 6 实际落地（2026-10-31）
- `adapters/dlsite/store_page.py`：读公开作品页，白名单解析为块，不存 HTML。
- `services/introductions.py`：按需读取、保存一周、失败保留旧内容。
- 迁移 `0010`：`works.intro_json`、`intro_fetched_at`。
- 前端 `features/game-detail/official-intro.tsx` 只渲染校验过的块。
- **未落地**：视频内嵌播放。

## 16. Phase 2 检查点 7 实际落地（2026-10-31）
- `services/local_copies.py`、`domain/local_files.py`（候选程序，只看文件名）、`adapters/system/launcher.py`（参数列表，不经过 shell）。
- 迁移 `0011`：`local_copies`。C8–C11 都基于它。
