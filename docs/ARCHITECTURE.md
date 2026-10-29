# Library Atlas 技术架构草案

状态：Phase 0 待审核；2026-10-30。目录、模型、接口均为拟议契约，不代表已有代码或 Steam 能力。

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
| games | id、steam_app_id(unique nullable)、canonical_title、metadata_status；不直接包含账号隐私 |
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
