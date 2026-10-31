# Phase 2 平台能力矩阵

核对日期：2026-10-30（JST）· 分支 `phase-2/checkpoint-0` · 配套文档：[接入方案](PHASE2_INTEGRATION_PLAN.md)、[检查点 0 报告](PHASE2_CHECKPOINT0_REPORT.md)

> 2026-10-30 更正：第 17 条第 11 号的概括原先写成“超出必要的反复查询”，复核原文后改正（该措辞针对向运营方的提问）。结论不变。

> 2026-10-31 检查点 2 更新：见文末“检查点 2 运行层结果”。上表的“待验证”项以该节为准。

## 状态与验证层级
| 状态 | 定义 |
|---|---|
| 已验证 | 当前结论有直接证据；“验证层级”注明是文档层还是运行层 |
| 部分验证 | 部分机制明确，但关键条件、环境或真实账号行为尚未确认 |
| 待验证 | 证据不足，尚不能承诺实现 |
| 当前不支持 | 在当前约束下无法提供，说明证据、影响与可选方案 |

验证层级：**文档层**＝官方文档/条款；**代码层**＝阅读第三方源码（只读，未运行）；**公开响应**＝本机对公开端点发出的单次未认证请求；**运行层**＝本机实验（见 `work/phase2-cp0/`）。本检查点**没有进行任何真实账号验证**，表中凡涉及“登录后”的行为都不是运行层结论。

## 证据编号
| 编号 | 来源 | 类型 |
|---|---|---|
| E1 | [DLsite 利用規約](https://www.dlsite.com/home/user/regulations)（最终改定 2025-04-21） | 官方条款 |
| E2 | [dlsite-async 源码](https://github.com/bhrevol/dlsite-async)，提交 `1af2943`（2026-10-30），MIT；[文档](https://dlsite-async.readthedocs.io)；PyPI 最新 1.0.0b4 / 稳定 0.11.2 | 第三方代码（只读） |
| E3 | 本机 curl：`login.dlsite.com/login` → 403 + `Cf-Mitigated: challenge`（Cloudflare）；`www.dlsite.com/maniax/` 200 | 公开响应 |
| E4 | 本机 curl：`play.dlsite.com/api/v3/content/count` 与 `play.dl.dlsite.com/api/v3/download/sign/cookie` 未登录 → 401 JSON；`www.dlsite.com/home/api/=/product.json?workno=…` 未登录 → 200，含 `work_type`、`file_type`、`file_size`、`is_split_content`、`dl_format`、`language_editions`、`is_dlsiteplay_only_work` 等字段 | 公开响应 |
| E5 | [WebView2 ICoreWebView2CookieManager](https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/icorewebview2cookiemanager)：`GetCookies` 返回指定 URI（或整个 profile）的 Cookie；`DeleteAllCookies` 清除 profile | 官方文档 |
| E6 | 本机注册表：WebView2 Runtime 156.0.4314.50 已安装；`LongPathsEnabled=1` | 运行层 |
| E7 | [pywebview API](https://pywebview.flowrl.com/api/)：`window.get_cookies()`、`clear_cookies()`、`private_mode`、`storage_path`；未说明是否包含 HttpOnly | 第三方文档 |
| E8 | [IPlayerService](https://partner.steamgames.com/doc/webapi/IPlayerService)：GetOwnedGames 需 key + steamid，“if their owned games/game details are visible to you”；GetRecentlyPlayedGames | 官方文档 |
| E9 | [Steam Web API Terms of Use](https://steamcommunity.com/dev/apiterms)（Last updated July 2010）：每日 100,000 次；密钥保密；需告知用户存储的 Steam 数据 | 官方条款 |
| E10 | [Steamworks 用户认证](https://partner.steamgames.com/doc/features/auth)：Steam 为 OpenID 2.0 Provider，端点 `https://steamcommunity.com/openid/`，Claimed ID 含 64 位 SteamID | 官方文档 |
| E11 | [Steam browser protocol](https://developer.valvesoftware.com/wiki/Steam_browser_protocol)：`steam://run/<id>`、`steam://install/<id>`；页面自述部分命令已失效 | 社区 wiki |
| E12 | [steamlocate](https://docs.rs/crate/steamlocate/2.0.0-beta.3/source/src/app.rs)、[game-detector](https://docs.rs/crate/game-detector/latest/source/src/steam.rs)：`config/libraryfolders.vdf`、`steamapps/appmanifest_<appid>.acf`（AppState: appid、name、StateFlags、installdir、SizeOnDisk） | 第三方代码 |
| E13 | 本机 curl：`cdn.akamai.steamstatic.com/steam/apps/440/{header.jpg,library_600x900.jpg,library_hero.jpg}` 均 200 image/jpeg，带 ETag 与 `max-age`；`api.steampowered.com/.../GetOwnedGames` 无 key → 401 | 公开响应 |
| E14 | `work/phase2-cp0/probe_credentials.py` + `.result.json`：CredWriteW 2560 字节成功、2561 字节失败（错误 1783）；读回一致、删除后不可读；DPAPI 20,000 字节往返成功且密文不含明文 | 运行层 |
| E15 | `work/phase2-cp0/probe_archives.py` + `.result.json`：无 UTF-8 标志的 cp932 ZIP 默认解码错误、`metadata_encoding="cp932"` 正确、UTF-8 标志优先；`..`/盘符/UNC/根路径 5 类越界均被拒绝；349 字符日文长路径写入成功 | 运行层（合成数据） |
| E16 | [zipfile 文档](https://docs.python.org/3/library/zipfile.html)：3.11 起 `metadata_encoding`，整个归档统一，UTF-8 标志优先 | 官方文档 |
| E17 | [7-Zip License](https://www.7-zip.org/license.txt)：LGPL 2.1+，RAR 解码含 unRAR 限制，分发须附许可信息；[rarfile 4.5](https://pypi.org/project/rarfile/)（ISC，需外部 unrar/7z）；[py7zr 1.1.4](https://pypi.org/project/py7zr/)（LGPL-2.1+，不支持 BCJ2）；[keyring 25.7.0](https://pypi.org/project/keyring/)（MIT） | 官方/包元数据 |
| E18 | 社区问答（[知恵袋 1](https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/q14120144784)、[知恵袋 2](https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/q1049414345)）：DLsite 大容量作品为分割下载，需全部下载后执行结合/解压 | 二手资料，可靠性低 |

## DLsite
| 平台/模块 | 具体能力 | 状态 | 机制与前提 | 证据 | 验证层级 | 未知与限制 | 后续检查点 |
|---|---|---|---|---|---|---|---|
| DLsite 条款 | 第三方工具代用户读取已购库 | 部分验证 | 条款未明文允许或禁止“用户本人以工具读取自己的库”；第17条第9号（过度负载）、第11号（BOT 等技术手段不正操作；同号的“反复”指向运营方反复提问，不是访问或检索）、第10号（解析提供的软件）、第6号（回避技术保护）、第12条第2項（超出预定方式复制）构成边界 | E1 | 文档层 | 属灰色地带，**需用户知情决定**；只做手动/低频、单线程、不绕过任何验证 | CP2 前 |
| 认证 | 官方第三方授权（OAuth 等） | 待验证 | 未找到面向第三方的公开开发者文档或授权流程 | E1、E2 | 文档层 | 未找到≠不存在；不得把网页登录包装成官方授权 | — |
| 认证 | 后端代填账号密码登录 | 当前不支持 | E2 的做法：GET 登录页取 `_token`，POST `login_id/password`；本机对登录页的非浏览器请求被 Cloudflare 质询拦截 | E2、E3 | 公开响应 | 绕过质询违反第17条且需持有密码；不采用 | — |
| 认证 | 内嵌真实浏览器窗口（WebView2）由用户亲自登录，结束后由后端读取会话 Cookie | 部分验证 | WebView2 Runtime 已安装；CookieManager 可读取/清除 profile 的 Cookie；pywebview 提供 `get_cookies()`（HttpOnly 未说明） | E5、E6、E7 | 文档层 + 运行时存在性 | 未实测 DLsite 登录页在 WebView2 中能否通过质询、是否有二步验证；pywebview 是否返回 HttpOnly 需在 CP2 验证，否则直接经 pythonnet 调用 CookieManager | CP2（人工 M1） |
| 认证 | 用户系统浏览器登录 | 当前不支持 | Atlas 页面与 dlsite.com 跨站，无法读取其 Cookie | 浏览器同源策略 | 文档层 | 若要用，只能手工复制 Cookie（本方案不推荐，未经用户同意不实施） | — |
| 会话 | 跨重启复用会话 | 待验证 | 会话 Cookie 存入受保护存储后，后端以 httpx 携带请求 | E2、E14 | 代码层 + 存储运行层 | Cookie 有效期、是否绑定 UA/IP、是否需要 `play.dlsite.com/api/authorize` 预热未知 | CP2（人工 M2） |
| 会话 | 失效检测 | 部分验证 | 未登录访问 Play API 返回 401 JSON，可作为 `reauth_required` 信号 | E4 | 公开响应 | 登录后过期的返回形态未实测 | CP2 |
| 会话 | 刷新/续期 | 待验证 | 未见刷新机制 | — | — | 无证据前不做自动续期，过期即提示重新登录 | CP2 |
| 已购读取 | 已购总数与作品编号列表 | 部分验证 | `GET play.dlsite.com/api/v3/content/count?last=` 与 `/content/sales?last=`（workno + sales_date） | E2、E4 | 代码层 + 未认证 401 | 非公开接口，可能随时变化；`last` 时间戳支持增量 | CP3（人工 M3） |
| 已购读取 | 作品详情批量获取 | 部分验证 | `POST play.dlsite.com/api/v3/content/works`，每批 100 个编号，源码注释称服务器不喜高并发→顺序请求 | E2 | 代码层 | 字段：workno、name（多语言）、maker{id,name}、work_type、age_category、author_name、tags、regist_date、sales_date、upgrade_date、work_files（封面/样图）；**已永久删除的作品不会返回** | CP3 |
| 分类 | DLsite 类型 → Atlas 五类 | 部分验证 | `work_type` 代码（如 RPG/ACN/ADV/SLN/STG/PZL/QIZ/TBL/TYP/DNV/ETC/MNG/ICG/SCM/WBT/VCM/SOU/MUS/MOV/NRE/PBC/TOL/IMT/AMT/ET3） | E2、E4 | 代码层 + 公开响应 | 映射见接入方案 §4.3；保留原始代码；未知代码进“其他/待分类” | CP3 |
| 元数据 | 公开作品元数据 | 部分验证 | `www.dlsite.com/<site>/api/=/product.json?workno=` 未登录可读，含文件格式、大小、是否分割、平台、语言版本等 | E4 | 公开响应 | 非公开文档接口；仅对用户库内作品低频调用；**私人/待确认条目不联网补全** | CP3 |
| 封面 | 封面/样图 URL | 部分验证 | Play 接口 `work_files`、product.json `image_main` 等 | E2、E4 | 代码层 + 公开响应 | 缓存许可未见明文；仅作个人本地缓存，失效回退占位 | CP3 |
| 文件列表 | Play 优化版文件树 | 部分验证 | `download/sign/cookie?workno=` 取令牌（含 `expires`、`url`）→ `ziptree.json` | E2、E4 | 代码层 + 未认证 401 | **仅为网页优化版**（图片缩小压缩、音频转 MP3、视频为 HLS），不是原始发行文件 | CP4 |
| 下载 | 原始发行文件（含分割） | 待验证 | 站点“购入済み作品”下载页需会话；大作品为分割下载 | E18 | 二手资料 | 原始下载链接获取方式、分卷命名、是否 SFX `.exe`+`.rar`、链接有效期均未核实 | CP4（人工 M4） |
| 下载 | 链接生命周期 | 部分验证 | Play 下载令牌带 `expires` 字段 | E2 | 代码层 | 原始下载链接有效期未知；过期需重新取令牌，不复用 | CP4 |
| 下载 | 断点续传（Range） | 待验证 | — | — | — | 不能因 HTTP 库支持 Range 就承诺平台支持 | CP4（人工 M4） |
| 下载 | 完整性校验 | 待验证 | product.json 有 `file_size`/`contents_file_size` | E4 | 公开响应 | 未见官方哈希；只能做大小核对 + 归档自校验，不得宣称官方校验 | CP4 |
| 下载 | 不适用作品识别 | 部分验证 | product.json 的 `is_dlsiteplay_only_work`、`is_android_only_work`、`is_ios_only_work`、`work_rentals`、`is_oauth_work` 等标志 | E4 | 公开响应 | 各标志确切语义未见文档；以“需官方应用/不支持”显示，不尝试下载 | CP3–CP4 |
| DLsite Nest | 读取 Nest 本地数据 | 当前不支持（不建议） | — | E1 第17条第10号 | 文档层 | 解析其本地数据可能属于“解析提供的软件”；且非本检查点授权范围 | — |

## Steam
| 平台/模块 | 具体能力 | 状态 | 机制与前提 | 证据 | 验证层级 | 未知与限制 | 后续检查点 |
|---|---|---|---|---|---|---|---|
| 身份 | 确认 SteamID | 已验证 | OpenID 2.0，Claimed ID 含 64 位 SteamID；或用户手动输入 SteamID/个人资料链接 | E10 | 文档层 | `return_to` 指向 `127.0.0.1` 回调是否被接受待实测；OpenID 只证明身份，不授予库访问 | CP6 |
| 库 | 已拥有游戏 | 已验证（文档层） | `IPlayerService/GetOwnedGames`，需 Web API Key + steamid；`include_appinfo` 取名称/图标 | E8、E13 | 文档层 + 无 key 401 | 资料仅说明“对你可见时返回”；**用户用自己的 key 查询自己的私密资料时能否返回未验证**；免费游戏需 `include_played_free_games` | CP6（人工 M5） |
| 游玩记录 | 累计时长、最近两周、最后游玩 | 部分验证 | GetOwnedGames（playtime_forever、rtime_last_played 等）、GetRecentlyPlayedGames（playtime_2weeks） | E8 | 文档层（方法）/ 字段名来自社区 | 官方页面未列响应字段；以实测 fixture 为准 | CP6 |
| 凭据 | Web API Key | 已验证（条款） | 用户自行在 Steam 申请，本机保存；每日 10 万次；不得分享 | E9、E14 | 文档层 + 存储运行层 | 不在聊天中提供；仅后端使用 | CP6 |
| 访问状态 | 区分私密/无权限/空库/限速/网络 | 部分验证 | 401/403/429/网络错误及“响应无 games 字段”需分别处理 | E8、E13 | 文档层 | 私密资料返回的具体形态待实测；不把任何失败当 0 件 | CP6 |
| 封面 | 公开 CDN 图片 | 部分验证 | `cdn.akamai.steamstatic.com/steam/apps/<appid>/{header.jpg,library_600x900.jpg,library_hero.jpg}` | E13 | 公开响应 | 非文档化地址，部分游戏缺竖版图；需缺图回退 | CP6 |
| 安装检测 | 已安装游戏与库目录 | 部分验证 | `<Steam>/config/libraryfolders.vdf` 列出库；各库 `steamapps/appmanifest_<appid>.acf` | E12 | 第三方代码 | 只读用户授权的 Steam 根目录；StateFlags 位含义未核实；格式可能随客户端变化 | CP6 |
| 客户端 | 启动/安装入口 | 部分验证 | `steam://run/<appid>`、`steam://install/<appid>`，用户点击后经系统协议处理器打开 | E11 | 社区 wiki | wiki 自述部分命令失效；仅整数 appid，固定前缀，不拼接用户输入 | CP6 |
| 下载解压 | Atlas 直接下载/解压 Steam 游戏 | 当前不支持（设计如此） | 由 Steam 客户端负责 | — | — | 不复用 DLsite 下载解压器 | — |
| 私密/隐藏 | 读取 Steam 端隐藏/私密游戏状态 | 待验证 | 见 ARCHITECTURE §7 | — | — | 不能可靠读取则保持 unknown | CP6 |

## 系统能力：凭据存储与解压
| 平台/模块 | 具体能力 | 状态 | 机制与前提 | 证据 | 验证层级 | 未知与限制 | 后续检查点 |
|---|---|---|---|---|---|---|---|
| 凭据 | Windows Credential Manager 读写删 | 已验证 | CredWriteW/CredReadW/CredDeleteW（generic），单条 blob ≤ 2560 字节 | E14 | 运行层（假值，已删除） | 超限需分片或改用 DPAPI；同用户恶意软件可读，不在保证内 | CP1–CP2 |
| 凭据 | DPAPI（CurrentUser）加密任意长度数据 | 已验证 | CryptProtectData/CryptUnprotectData | E14 | 运行层 | 仅当分片不适用时作为备选，需在方案中说明 | CP2 |
| 凭据 | Python 依赖 | 部分验证 | 标准库 ctypes 即可；keyring 25.7.0（MIT）可选 | E14、E17 | 运行层（ctypes） | 是否引入 keyring 在 CP1 依赖锁定时决定 | CP1 |
| 解压 | ZIP（含日文 cp932 文件名） | 已验证 | 标准库 zipfile + `metadata_encoding="cp932"`；无标志时需判定编码 | E15、E16 | 运行层（合成） | 一个归档内混合编码无法逐项指定；需编码探测与人工回退 | CP5 |
| 解压 | 越界路径防护 | 已验证 | 拒绝盘符、根路径、UNC、`..`，resolve 后必须在目标目录内 | E15 | 运行层（合成） | 还需处理符号链接条目、文件数/展开体积上限 | CP5 |
| 解压 | Windows 长路径 | 已验证（本机） | `LongPathsEnabled=1`，349 字符日文路径写入成功 | E6、E15 | 运行层 | 其他机器可能未开启；需检测并提示 | CP5 |
| 解压 | RAR / 分卷 / SFX `.exe` | 待验证 | 需外部 7-Zip 或 unrar（rarfile 仅封装）；7-Zip 可读 SFX 与分卷 | E17、E18 | 包元数据 / 二手 | 需真实样本确认 DLsite 分割格式；引入 7-Zip 需用户同意（AGENTS/ARCHITECTURE §9）；绝不运行 `.exe` | CP5 |
| 解压 | 7z | 部分验证 | py7zr（LGPL-2.1+，不支持 BCJ2）或 7-Zip | E17 | 包元数据 | 是否需要 7z 取决于真实样本 | CP5 |
| 解压 | 加密归档 | 当前不支持（自动） | 只允许用户手动输入作品方公布的密码 | — | — | 不猜测、不破解 | CP5 |

## 人工验证清单（留到对应检查点，由用户本人操作）
| 编号 | 检查点 | 用户操作 | 观察并匿名记录 | 通过标准 |
|---|---|---|---|---|
| M1 | CP2 | 在 Atlas 连接面板中输入账号密码登录 | 是否出现人机验证/二步验证；能否完成 | 登录完成，Atlas 只显示“已连接” |
| M2 | CP2 | 关闭并重启 Atlas；隔 1 天、7 天再看 | 会话是否仍有效（只记“有效/失效 + 天数”） | 失效时提示重新登录，不静默失败 |
| M3 | CP3 | 同步后对比 DLsite 网站显示的已购数量 | 只记两个数字是否一致 | 一致，或差异能解释（如已删除作品） |
| M4 | CP4 | 选 1 件自己愿意测试的作品 | 原始文件是否可下载、是否分割、格式、大小、断点续传是否生效 | 能核对大小与完成位置 |
| M5 | CP6 | 在 Steam 中切换资料隐私设置后同步 | 私密时用自己的 key 是否仍能取到库 | 结果如实记录，不可取时提示清楚 |

## 检查点 2 运行层结果（2026-10-31，本机，未使用任何账号）
| 问题 | 结果 | 依据 |
| --- | --- | --- |
| 隐藏的 WebView2 能否打开登录页 | **运行层已验证**：`visibilityState` 为 hidden 时正常加载，未出现 Cloudflare 质询或验证码，`navigator.webdriver` 为 false | 一次性探针，未提交任何内容 |
| 登录表单结构 | **运行层已验证**：`form` 含隐藏 `_token`、`login_id`（id `form_id`）、`password`（id `form_password`）、提交按钮 | 同上 |
| 能否读取 HttpOnly Cookie | **运行层已验证**：登录页的 HttpOnly Cookie 可读 | 同上；登录后的 Cookie 未验证 |
| pywebview 6.2.1 + pythonnet 3.2.1 | **运行层已验证**：Python 3.14.3 下可安装、可运行 | 已写入锁文件 |
| 后台进程的管道与取消 | **运行层已验证**：打开网页登录窗口后取消，进程退出，无残留 | 未提交任何内容 |
| 无登录时 httpx 访问 Play 接口 | **公开响应**：默认请求头返回 401，未被质询 | 单次请求 |
| 提交后的行为（成功跳转、错误提示、是否要求验证） | **待验证（M1）** | 向真实站点提交需用户本人操作 |
| 登录后的会话 Cookie、大小、后端能否复用 | **待验证（M1）** | 同上 |
| 跨重启、过期 | **待验证（M2）** | 同上 |

## 检查点 3 运行层结果（2026-10-31，用户本人账号）
| 问题 | 结果 |
| --- | --- |
| 已购列表与作品资料 | **运行层已验证**：`content/count`、`content/sales`、`content/works`（每批 100）可用，后端 httpx 复用保存的会话即可 |
| 响应字段 | **运行层已验证**：age_category, app_type, author_name, content_count, content_length, content_size, dl_format, download_start_date, downloadable, encodable, file_type, genre_ids, inservice, is_playwork, maker, name, name_phonetic, os, purchase_type, regist_date, rental_activate_date, rental_expired_date, rental_id, rental_time, sales_date, series, site_id, tags, touch_content_count, touch_inservice, touch_site_id, translator, upgrade_date, viewer_type, work_files, work_type, workno。值的含义大多未核实 |
| 覆盖差异 | **部分验证**：列表 526，资料 518，差 8 部，原因未确认 |
| 简介 | **当前不支持**（此入口）：响应没有简介字段 |
| 封面 | **运行层已验证**：`work_files.main` 匿名可取，无需会话 |
| 原版文件下载 | **待验证**：只确认存在 downloadable、file_type、content_size、dl_format 字段，未请求任何文件 |

## 检查点 4 证据（2026-10-31）
| 问题 | 结果 |
| --- | --- |
| 原版文件的入口 | **代码层**：[dlsite-manager](https://github.com/vuhe/dlsite-manager)（MIT，`36bed5b`）：`GET play.dlsite.com/api/v3/download?workno=` 返回跳转，目标路径区分单文件、分卷、需序列号。**用户账号上未实测** |
| 分卷 | **代码层**：分卷页面列出带 `/number/N/` 的链接。**未实测** |
| 会话能否访问 www 下载地址 | **待验证（M4）** |
| 最终文件主机 | **待验证（M4）**：只允许 `dlsite.com` 及其子域，其他主机会被拦截并报告 |
| Range、ETag | **待验证（M4）**：第三方代码使用 Range 续传；Atlas 只在有强校验器时续传，否则从头下载 |
| 官方哈希 | **当前不支持**：未见平台提供；只做长度核对和本地 SHA-256 |
| `content_size` 单位 | **代码层**：第三方用它预估下载大小，按字节处理。**未与平台数值比对** |
| 需要序列号的作品 | **当前不支持**：Atlas 明确提示，不尝试 |

## 检查点 5 证据（2026-10-31）
| 问题 | 结果 |
| --- | --- |
| ZIP、cp932 文件名 | **运行层已验证（合成）** |
| RAR 4、RAR 分卷、7z、7z SFX | **运行层已验证（合成，7-Zip 25.01）** |
| RAR 5、RAR SFX | **待验证**：没有样本 |
| 带密码的压缩包 | **当前不支持**：7-Zip 只接受命令行密码，会暴露 |
| 真实 DLsite 文件的格式 | **待验证（M4）** |
| 公开 `product.json` 的 `image_main`、`image_samples`、`intro_s` | **公开响应**：用一个与用户账号无关的作品核实，地址形如 `//img.dlsite.jp/...` |
| `upgrade_date` 的含义 | **待验证**：字段存在，Atlas 只比较是否变化 |

## 真实下载结果（2026-10-31，用户账号，匿名摘要）
| 问题 | 结果 |
| --- | --- |
| `play.dlsite.com/api/v3/download` 入口与保存的会话 | **运行层已验证**：单文件作品，后端直接下载成功 |
| 最终文件主机在放行范围内 | **运行层已验证** |
| 响应头 | **运行层已验证**：有 `Content-Length`、强 ETag、Last-Modified；文件名为 `<作品编号>.zip` |
| ZIP 解压 | **运行层已验证**：76 个文件，无异常 |
| 续传、分卷、序列号 | **待验证** |

## 检查点 6 证据（2026-10-31）
| 问题 | 结果 |
| --- | --- |
| 公开作品页的介绍结构 | **公开响应 + 运行层**：`work_parts_container`；用户库内 8 部读取成功 |
| 分区跳转 | **运行层已验证**：作品可能从一个分区跳到另一个分区 |
| 视频预览 | **待验证**：未见真实样本 |

## 本地音声（检查点 10）
| 能力 | 状态 |
| --- | --- |
| WAV 播放、跳转、接续 | 已验证（自制音频） |
| MP3、FLAC、OGG、Opus、M4A、AAC | 接口可提供，真实文件未验证，取决于浏览器 |
| WMA、APE、TAK、TTA、WV、MIDI | 只列出，标为不可播放 |

## 本地阅读（检查点 11）
| 能力 | 状态 |
| --- | --- |
| PNG 文件夹、ZIP/CBZ、简单 PDF | 已验证（自制文件） |
| JPEG、WebP、GIF、BMP、AVIF，真实日文或扫描版 PDF | 未用真实文件验证 |
| RAR、CBR、7z、CB7、EPUB、MOBI、AZW3 | 不支持，列出并说明 |
| 平台专用格式（如 `.dlst`） | 不解密，请用官方阅读器 |

## 云存档（检查点 9b）
| 能力 | 状态 |
| --- | --- |
| 授权、上传、恢复、冲突、换号隔离 | 假 Drive 上已验证，真实 Google 未验证 |
| 两台真实电脑 | 未验证 |
| 自动恢复 | 不提供 |
| 云端自动清理 | 不提供 |
| 加密 | 不提供 |
| 关闭后自动备份 | 仅限直接运行主程序的游戏 |