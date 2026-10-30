# Library Atlas 本地 API 契约

状态：Phase 2 检查点 1、2 已实现。这是 Atlas 自有接口，不是 Steam 或 DLsite 的接口。实现见 `backend/app/api/`，端到端验证见 `frontend/tests/e2e/real-mode.spec.ts`。

## 约定
- 基址 `http://127.0.0.1:<port>/api/v1`，默认端口 8765，只绑定回环地址。开发期由 Vite 代理 `/api`，浏览器只看到一个来源。
- JSON 字段统一 camelCase。查询参数同样 camelCase。未知查询参数和未知请求字段一律 422，没有任何参数能扩大可见范围。
- 时间为带时区的 ISO 8601 字符串（UTC）；发售日可为 `YYYY-MM-DD`。时长单位为分钟（非负整数）。
- **`null` 表示来源未提供或尚不知道，不等于 0、false 或“没有”。** 前端也必须按未知显示。

## 错误
所有错误使用同一结构，不含堆栈、SQL、路径、上游 URL 或用户输入：

```json
{ "error": { "code": "work_unavailable", "message": "作品暂不可用。", "requestId": "…", "retryable": false } }
```

| HTTP | code | 含义 | 前端处理 |
| --- | --- | --- | --- |
| 404 | `work_unavailable` | 作品不存在，**或**是私人/隐藏/待确认；两者完全一致 | “找不到这部作品” |
| 404 | `not_found` | 接口不存在 | — |
| 409 | `version_conflict` | `expectedVersion` 已过期，未写入 | 保留输入，提示后可再次保存 |
| 421 | `host_not_allowed` | Host 不在允许列表（防 DNS rebinding） | — |
| 403 | `origin_not_allowed` / `origin_required` / `csrf_invalid` | 本地请求边界拒绝 | `csrf_invalid` 时取新令牌重试一次 |
| 422 | `invalid_request` / `no_changes` | 输入无效 / 没有可写字段 | 显示未保存 |
| 503 | `service_not_ready` / `database_unavailable` | 资料库未就绪或暂时不可访问 | 显示原因与重试，**不显示为空库** |
| 500 | `internal_error` | 未预期错误，日志只记类型与 requestId | 显示重试 |

## 请求边界
- 所有请求：`Host` 必须是允许的回环地址。
- `/api/*`：带 `Origin` 时必须在允许列表；`Sec-Fetch-Site: cross-site` 一律拒绝；不发送任何 CORS 头。
- 写请求（PATCH/POST）：必须带允许的 `Origin` 和 `X-Atlas-CSRF`。令牌由 `GET /session` 取得，只有同源页面读得到，每次服务启动都会变化，不写入 URL、日志或浏览器持久存储。
- 允许的来源：服务自身的 `127.0.0.1` / `localhost`，加 `ATLAS_DEV_ORIGINS` 中的回环地址。

## 接口
### 服务状态
| 接口 | 说明 |
| --- | --- |
| `GET /health` | 存活。进程在即 200，不检查数据库。`{status:"ok",version}` |
| `GET /ready` | 就绪。200 `{status:"ready",profile,schemaRevision}`；否则 503 `{status:"not_ready",profile,reason,message}`。`reason`：`schema_too_new`、`profile_mismatch`、`database_corrupt`、`database_unavailable`、`migration_failed`、`backup_failed`、`migrations_missing`、`starting` |
| `GET /session` | `{csrfToken}` |

`profile` 为 `real` 或 `test`。`test` 时前端持续显示“测试库 · 合成数据”。

### 作品列表 `GET /works`
| 参数 | 取值 | 默认 | 语义 |
| --- | --- | --- | --- |
| `search` | ≤200 字符 | 空 | 标题、副标题、制作方的**包含匹配**；NFKC 规范化且不分大小写；`%`、`_` 按普通字符处理 |
| `kind` | `all` `non-game` `game` `image` `video` `audio` `other` | `all` | `non-game` 为除游戏外的全部 |
| `platform` | `all` `steam` `dlsite` | `all` | |
| `genre` | ≤200 字符 | `all` | 精确匹配；未分类作品不可按此筛选 |
| `status` | `all` `unplayed` `playing` `completed` `paused` | `all` | 个人状态 |
| `installed` | `all` `installed` `not-installed` | `all` | **本机状态未知的作品两边都不算** |
| `favoritesOnly` | 布尔 | `false` | |
| `sort` | `curated` `name-asc` `name-desc` `playtime-desc` `playtime-asc` | `curated` | 见下 |
| `offset` / `limit` | ≥0 / 1–100 | 0 / 100 | 窗口分页 |

所有条件取交集。排序始终以作品 ID 收尾，翻页不跳不重：
- `curated`：加入时间从新到旧。
- `name-*`：NFKC 规范化、不分大小写、数字按数值比较（第 2 卷在第 10 卷之前）。**按 Unicode 码位，不是拼音或五十音顺序**。
- `playtime-*`：未知时长在两个方向都排最后；0 和未知分开。

响应：

| 字段 | 范围 |
| --- | --- |
| `items` | 当前窗口的作品 |
| `filteredCount` | 符合全部筛选的数量 |
| `totalVisible`、`kindCounts`、`installedCount`、`favoriteCount` | 全部普通作品，不受筛选影响 |
| `genres` | 随 `kind` 变化的可选类型 |

### 作品对象
`id`、`platform`、`sourceId`（身份为 `platform + sourceId`，同编号跨平台是两部作品）、`kind`、`maker?`、`releaseDate?`、`title`、`subtitle?`、`genre?`、`status`、`installed?`（Steam 为已安装，DLsite 为已下载）、`playtimeMinutes?`、`favorite`、`visibility`（普通接口恒为 `normal`）、`cover {kind:"procedural"|"missing",index}`、`background`（本检查点恒为 null）、`addedAt`、`lastPlayedAt?`、`capabilities {download?,extract?,officialViewerOnly?}`、`file {version?,sizeBytes?}?`（第一个文件）。带 `?` 的字段可为 `null`。

### 详情 `GET /works/{id}`
作品对象加：`description?`、`tags[]`、`categories[]`（本检查点恒为空）、`achievements {unlocked,total}?`、`rating?`、`note`、`version`、`files[]`。

`files[]` 每项：`id`、`label?`、`version?`、`language?`、`partIndex?`、`partCount?`、`sizeBytes?`、`format?`、`availability`（`unknown` `downloadable` `viewer_only`）、`downloadState`（`unknown` `not_downloaded` `downloaded`）、`extractState`（`unknown` `not_applicable` `not_extracted` `extracted`）。一个作品可有多个文件，分卷不是独立作品；下载、解压、安装、可启动是分开的事实。

### 个人记录
| 接口 | 说明 |
| --- | --- |
| `PATCH /works/{id}/personal` | 请求体可含 `status`、`rating`（1–5 整数，`null` 清除）、`note`（去首尾空白后 ≤1000 字，纯文本）、`favorite`、`expectedVersion`。只写给出的字段。成功返回完整详情 |
| `POST /works/{id}/favorite/toggle` | 原子翻转收藏，返回完整详情 |

**并发策略**：单机应用，只防真实会发生的两种情况。
1. 同一页面连续保存：前端按作品串行发送，响应带 `version`，版本较旧的响应不会覆盖缓存。
2. 另一标签页已改：备注保存时带 `expectedVersion`，过期返回 409，草稿保留，刷新后可再次保存。状态、评分、收藏是单字段写入，互不覆盖。

**缓存规则**：修改成功后用响应更新详情缓存，并使当前模式下的列表、详情、首页缓存全部失效。修改失败也会失效，让页面回到服务器的真实值。

### 首页 `GET /dashboard`
参数 `scope`（`all` `games` `steam` `dlsite-games` `dlsite-media`）与 `batch`（≥0）。统计口径与 Demo 的 `selectDashboard` 相同，每个范围的作品数等于作品库相应筛选的数量（有测试）。无时长记录的游戏不计入时长；非游戏作品没有游玩统计。推荐在同一天同一 `batch` 内固定。

### 来源 `GET /sources`
`{sources:[{id,displayName,connection,workCount,lastSyncAt,capabilities:{connect,sync,download}}]}`。`connection` 见下方“DLsite 连接”；有来源记录不代表已认证。`capabilities.connect` 仅 DLsite 为 `true`，其余为 `false`。

### DLsite 连接
都不返回账号名、会话或平台响应。写接口受请求边界保护。

| 接口 | 说明 |
| --- | --- |
| `GET /sources/dlsite/connection` | `{state,code?,message?,lastVerifiedAt?,canReveal?}`。只读本地状态，不访问平台 |
| `POST /sources/dlsite/login` | `{loginId,password,confirmSwitch?}`，启动一次登录。不接受其他字段，请求体不进日志和错误响应 |
| `POST /sources/dlsite/login/window` | 备用网页登录，无请求体 |
| `POST /sources/dlsite/login/cancel` | 取消当前尝试，其迟到结果被丢弃 |
| `POST /sources/dlsite/login/reveal` | 把验证窗口调回前台 |
| `POST /sources/dlsite/verify` | 用保存的会话向平台确认一次 |
| `POST /sources/dlsite/disconnect` | 清除 Atlas 保存的会话，不影响作品和个人记录，也不代表退出平台其他设备 |

| `state` | 含义 |
| --- | --- |
| `not_connected` | 没有可用会话 |
| `authenticating` / `needs_verification` | 登录进行中 / 平台要求用户本人验证 |
| `verifying` | 正在确认会话 |
| `connected` | 已确认可用 |
| `unverified` | 暂时无法确认（网络、限流、凭据存储读取故障），不代表失效 |
| `reauth_required` | 平台明确拒绝，或保存的会话损坏，需重新登录 |
| `disconnect_failed` | 已停用但清理未完成，可重试；重启也不会恢复 |

| `code` | 含义 |
| --- | --- |
| `bad_credentials` | 账号或密码不正确 |
| `form_changed` | 登录页结构不认识，可改用网页登录 |
| `browser_unavailable` | 登录组件无法启动 |
| `timeout` | 等待超时 |
| `not_confirmed` | 没能确认登录成功 |
| `store_failed` | 登录成功但无法安全保存，未保持连接 |
| `store_unavailable` | 读不到系统凭据存储 |
| `session_missing` / `session_expired` | 保存的会话不可用 / 已失效 |
| `platform_unavailable` | 暂时连不上平台 |

错误响应：409 `login_in_progress`（已有登录在进行）、409 `account_mismatch`（账号与之前不同，带 `confirmSwitch: true` 重试）、503 `credential_store_unavailable`。

### 文件夹设置
| 接口 | 说明 |
| --- | --- |
| `GET /settings/folders` | `{folders:[{kind,path,isDefault,status}]}`。`kind`：`library`、`download_cache`。`status`：`ok`、`not_set`、`missing` |
| `PUT /settings/folders/{kind}` | `{path}`。必须是已存在、可写的绝对路径，不能是 Atlas 数据目录或系统文件夹，两个文件夹不能相同。无效返回 422 `folder_invalid` |
| `POST /settings/folders/{kind}/pick` | 打开系统文件夹选择窗口，用户关闭后返回。取消不改动 |
| `POST /settings/folders/{kind}/open` | 在资源管理器打开已登记的文件夹。请求不能指定路径 |

只记录和校验，不扫描磁盘，不移动文件。选定的文件夹不见了时报告 `missing`，不会重建。下载功能开放前不会写入。

## 后续检查点的任务状态（仅契约，未实现）
本检查点没有任务表和任务接口。契约见 [接入方案 §7](PHASE2_INTEGRATION_PLAN.md)。
