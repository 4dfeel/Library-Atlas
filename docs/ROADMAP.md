# Library Atlas 路线图与阶段门禁

状态：Phase 0、Phase 1 已获用户确认；Phase 2 检查点 0 方案已确认，检查点 1 工程检查完成、待用户确认；2026-10-30。每阶段独立验收，上一阶段未通过不得以完成名义推进。MVP 是 Phase 1–5 的累计成果；Phase 6 为后续选项。

## 通用交付规则
- 每阶段使用 `phase-N/<topic>` 分支，形成可审阅提交；通过检查后保留阶段最终 SHA，可标记 `phase-N-complete`。未验收不得标 complete。推送仅使用用户指定 GitHub 远程，禁止强推。
- 阶段报告包含交付范围、复现命令、检查结果/证据、限制、提交 SHA、下一阶段门禁。不能用“已编写测试”代替“已运行通过”。
- 核心页面按 PRODUCT 清单逐步加入 Playwright 截图；合成数据固定种子，默认无私人可见内容。相关 Vitest/Pytest/Playwright、类型、格式、构建检查通过后才提交完成点。
- 中途发现技术栈更换、大规模重构或删除功能需求先征询用户；一般实现无需反复确认。需要改范围时先更新文档并说明取舍。

| Phase | 可验收交付物 | 测试与检查 | Git 检查点 | 下一阶段条件 |
| --- | --- | --- | --- | --- |
| 0 规划（本轮） | 五份规范文档、Git 初始化与忽略规则、环境检查 | 文件/链接/需求覆盖、git diff --check、无敏感产物；无功能测试 | `docs: define phase 0 product architecture and design` | 用户明确审核 AGENTS、DESIGN、ARCHITECTURE；补充 GitHub 目标 |
| 1 高保真前端与视觉基线 | 分四个检查点完成 AppShell+Library、Game Detail、Dashboard、最终前端验收；精确依赖锁、本地 Demo、Windows 启动构建与 CI；本轮仅检查点 1 | Vitest 组件/数据/配色；Playwright 授权页面的视口/DPR 矩阵、隐私、交互和性能；后端检查延期 | 每检查点独立 `feat` 提交，检查点 1 为 `feat: deliver phase 1 checkpoint 1 library preview` | 每检查点经用户视觉认可才推进；最终前端验收后另行授权后端 |
| 2 后端与数据接入、隐私基础 | 另行授权后先建立 FastAPI/SQLite/迁移/凭据与单服务骨架（平台中立作品模型），再完成 Steam 与 DLsite 能力调查（含 Nest 本地数据、登录会话、使用条款），验证平台认证与会话续期方式、系统凭据存储与断开清除、DLsite 已购列表与可下载文件的获取方式，再实现账号会话、库同步、下载与解压（目录配置、校验、断点续传、安全解压）；只读扫描/导入/API 适配器、观测合并、作业中心与私人隔离 | Pytest 健康/配置/迁移/路径、来源合并/幂等/部分失败/取消/脱敏；普通端点/图片/计数隐私集成测试；生产单服务冒烟；真实网络仅授权手工烟测 | `feat: add safe library ingestion` | 能力矩阵有证据；依赖锁可重建；静态构建由 FastAPI 托管；不可用源明确降级；不写 Steam 文件或覆盖偏好 |
| 3 核心游戏库与整理 | 虚拟网格/列表、筛选详情、批量编辑、普通/私人收藏、隐藏管理、Backlog | Vitest 筛选/选择/撤销；Pytest 持久化/权限/冲突；Playwright 核心流程及新增页截图；1500 项性能与键盘回收检查 | `feat: deliver library and collections` | UI 全状态通过；私人哨兵不泄漏；离线编辑持久；性能达到 DESIGN 预算 |
| 4 智能整理与洞察 | 规则分类预览/锁定、可解释本地推荐/反馈、统计及覆盖说明 | 固定 fixture 验证规则和冷启动；Pytest 统计空值/过滤/时间窗；Vitest 理由呈现；Playwright 推荐/分类/统计截图 | `feat: add classification and insights` | 推荐可解释且可复现；统计不虚构历史；隐私统一过滤；缺元数据可降级 |
| 5 MVP 稳定与交付 | 备份恢复、迁移演练、缓存清理、启动与故障文档、Windows 使用说明、发布构建、完整回归 | 全部测试与截图；断网/权限/端口占用/损坏输入；备份恢复与升级；125%/150% 缩放；1500 项性能报告；源码/发布物秘密扫描 | `chore: qualify local mvp release`，验收后 v0.1.0 | 用户验收完整 MVP，GitHub 已推送至指定仓库；已知风险和恢复路径清晰 |
| 6 可选扩展（需另行授权） | 多账号、趋势/年度回顾、动态收藏、Steam/DLsite 以外的数据源、可选模型、经证实的 Steam 状态集成 | 每项独立 RFC、来源/许可调查、隐私与回归检查 | 按独立功能 PR 与版本标记 | 由用户选择优先级；不自动启动，不预先承诺远端回写 |

## Phase 1 当前授权与检查点
用户于 2026-10-30 授权并指定 [Phase 1 提示文档](specs/PHASE1.md) 为本轮执行依据。技术栈和未来正式运行架构不变；原计划中的后端骨架、SQLite、迁移、OpenAPI 与 FastAPI 静态托管均延期至 Phase 2 另行授权后，不在本轮创建。

1. **检查点 1（已交付）**：AppShell + Library，统一 Demo 数据层，24 张本地原创插画封面，1500/5000 数据，网格/列表虚拟化，实际搜索/多条件筛选/排序/收藏；完整七档视口与 DPR 截图、性能实测、必要测试、文档、提交和推送。完成后等待用户视觉审核。
2. **检查点 2（已实现，待视觉确认；含 2026-10-30 作品库重构）**：Game Detail：稳定 ID 路由与 Library 往返状态恢复、2:1 原创背景、缺图/缺数据语义、按 ID 读写的隐私过滤、版本化本机演示修改（状态/评分/备注/收藏）与重置；七档矩阵截图、测试与性能实测。见 [检查点 2 报告](PHASE1_CHECKPOINT2_REPORT.md)。
3. **检查点 3（已实现，待视觉确认）**：Dashboard 与 Steam/DLsite 多来源适配：首页 12 项内容与范围切换、来源/类型/能力模型增量、演示来源连接与演示下载解压流程、七档矩阵截图、测试与性能实测。见 [检查点 3 报告](PHASE1_CHECKPOINT3_REPORT.md)。真实登录、会话保持、库同步、下载与解压均未实现。
4. **检查点 4（工程检查完成，待用户人工验收）**：全页面验收、视觉修复与阶段交付：七档矩阵覆盖全部核心页面与边界状态、离线资源、隐私、计时器与性能复测，修复见 [检查点 4 报告](PHASE1_CHECKPOINT4_REPORT.md)，结论与证据索引见 [Phase 1 验收报告](PHASE1_ACCEPTANCE_REPORT.md)。

**Phase 1 状态**：工程检查已完成，用户于 2026-10-30 确认通过。真实 Windows 125%/150%/200% 系统缩放与读屏软件未单独验证，仍记录为未执行项。

检查点 1 不实现真实数据接入、Steam 操作、后端/数据库、私人空间或其完整安全边界，不承诺 Phase 1 已整体完成。Recharts 仅在图表页面需要时加入，当前不安装未使用依赖。Demo 模式关闭时展示未接入说明，不尝试真实请求。字体、封面均本地可用，不依赖 CDN。

## Phase 2 当前授权与检查点
按 Phase 2 大纲逐点授权；一次只执行一个检查点。“DLsite 一键下载解压”按用户决定（2026-10-30）从 Phase 6 移入 Phase 2 检查点 4–5。上表 Phase 2 行是早期概述，以本节和大纲为准。

| 检查点 | 主题 | 状态 |
| --- | --- | --- |
| 0 | 现状审查与平台能力验证 | 已交付，方案已获用户确认。见 [能力矩阵](PHASE2_CAPABILITY_MATRIX.md)、[接入方案](PHASE2_INTEGRATION_PLAN.md)、[报告](PHASE2_CHECKPOINT0_REPORT.md) |
| 1 | 本地服务、持久化与真实模式基础 | 工程检查完成，CI 通过，待用户确认。见 [报告](PHASE2_CHECKPOINT1_REPORT.md)、[API](LOCAL_API.md)、[运行说明](LOCAL_DEVELOPMENT.md) |
| 2 | DLsite 认证与会话保持 | 实现完成，真实登录与跨重启恢复已验证，用户已确认。见 [报告](PHASE2_CHECKPOINT2_REPORT.md) |
| 3 | DLsite 已购作品同步与分类 | 实现完成，首次真实同步通过，待用户确认分类。见 [报告](PHASE2_CHECKPOINT3_REPORT.md) |
| 4 | 真实下载队列 | 实现完成，待人工真实下载验证。见 [报告](PHASE2_CHECKPOINT4_REPORT.md) |
| 5 | 解压与一键下载并解压 | 实现完成，待人工真实解压验证。见 [报告](PHASE2_CHECKPOINT5_REPORT.md) |
| 6 | DLsite 官方商店介绍与富媒体详情（Steam 延期） | 实现完成，待真实覆盖核对。见 [报告](PHASE2_CHECKPOINT6_REPORT.md) |
| 7 | 全链路验收 | 未开始 |

Steam 接入未实现；真实下载和解压待用户验证。

## Phase 0 初始化检查记录
- 工作区 `H:\VSC workspacce\Library Atlas` 初始为空，无既有代码和 AGENTS；本轮仅创建文档、`.gitignore` 并初始化本地 Git。
- 已检测 Git 2.56.0.windows.3、Node 22.22.1、npm 10.9.4、Python 3.14.3；仅记录工具存在，不代表技术栈兼容测试通过。尚无依赖清单，因此未安装依赖或生成虚假锁文件。
- 初始未配置 Git 身份与远程；用户随后提供作者信息，已仅在当前仓库配置并用于 Phase 0 提交。随后经用户授权创建私有仓库 https://github.com/4dfeel/Library-Atlas 并完成推送。
- Phase 0 不运行 Vitest/Pytest/Playwright，因为没有功能代码；执行文档完整性、内部链接与 Git 空白检查。
