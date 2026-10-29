# Library Atlas 路线图与阶段门禁

状态：Phase 0 规划；2026-10-30。每阶段独立验收，上一阶段未通过不得以完成名义推进。用户审核 Phase 0 的 AGENTS、DESIGN、ARCHITECTURE 前停止开发。MVP 是 Phase 1–5 的累计成果；Phase 6 为后续选项。

## 通用交付规则
- 每阶段使用 `phase-N/<topic>` 分支，形成可审阅提交；通过检查后保留阶段最终 SHA，可标记 `phase-N-complete`。未验收不得标 complete。推送仅使用用户指定 GitHub 远程，禁止强推。
- 阶段报告包含交付范围、复现命令、检查结果/证据、限制、提交 SHA、下一阶段门禁。不能用“已编写测试”代替“已运行通过”。
- 核心页面按 PRODUCT 清单逐步加入 Playwright 截图；合成数据固定种子，默认无私人可见内容。相关 Vitest/Pytest/Playwright、类型、格式、构建检查通过后才提交完成点。
- 中途发现技术栈更换、大规模重构或删除功能需求先征询用户；一般实现无需反复确认。需要改范围时先更新文档并说明取舍。

| Phase | 可验收交付物 | 测试与检查 | Git 检查点 | 下一阶段条件 |
| --- | --- | --- | --- | --- |
| 0 规划（本轮） | 五份规范文档、Git 初始化与忽略规则、环境检查 | 文件/链接/需求覆盖、git diff --check、无敏感产物；无功能测试 | `docs: define phase 0 product architecture and design` | 用户明确审核 AGENTS、DESIGN、ARCHITECTURE；补充 GitHub 目标 |
| 1 工程骨架与视觉基线 | 前后端空骨架、精确依赖锁、token 与共用组件、Demo 空壳/合成卡片样板、SQLite 首迁移、健康接口、Windows 启动构建、CI | Vitest token/组件关键行为；Pytest health/配置/迁移；Playwright 空壳/长标题/缺图/Demo 截图；生产单服务冒烟；中文空格路径 | `feat: establish phase 1 foundation` | 用户认可视觉基线；从锁文件可重建；静态构建由 FastAPI 托管；不依赖 Vite 正式运行 |
| 2 数据接入与隐私基础 | 官方能力调查报告、只读本地扫描/手动导入/API 适配器、观测合并、作业中心、私人隔离与待确认区、凭据存储 | Pytest 来源优先级/幂等/部分失败/取消/路径/密钥脱敏；普通端点/图片/计数隐私集成测试；同步中心与隔离区合成截图；真实网络只做授权手工烟测 | `feat: add safe library ingestion` | 能力矩阵有证据；不可用源已明确降级；无状态假定；同步不改 Steam 文件、不覆盖本地偏好 |
| 3 核心游戏库与整理 | 虚拟网格/列表、筛选详情、批量编辑、普通/私人收藏、隐藏管理、Backlog | Vitest 筛选/选择/撤销；Pytest 持久化/权限/冲突；Playwright 核心流程及新增页截图；1500 项性能与键盘回收检查 | `feat: deliver library and collections` | UI 全状态通过；私人哨兵不泄漏；离线编辑持久；性能达到 DESIGN 预算 |
| 4 智能整理与洞察 | 规则分类预览/锁定、可解释本地推荐/反馈、统计及覆盖说明 | 固定 fixture 验证规则和冷启动；Pytest 统计空值/过滤/时间窗；Vitest 理由呈现；Playwright 推荐/分类/统计截图 | `feat: add classification and insights` | 推荐可解释且可复现；统计不虚构历史；隐私统一过滤；缺元数据可降级 |
| 5 MVP 稳定与交付 | 备份恢复、迁移演练、缓存清理、启动与故障文档、Windows 使用说明、发布构建、完整回归 | 全部测试与截图；断网/权限/端口占用/损坏输入；备份恢复与升级；125%/150% 缩放；1500 项性能报告；源码/发布物秘密扫描 | `chore: qualify local mvp release`，验收后 v0.1.0 | 用户验收完整 MVP，GitHub 已推送至指定仓库；已知风险和恢复路径清晰 |
| 6 可选扩展（需另行授权） | 多账号、趋势/年度回顾、动态收藏、更多数据源、可选模型、经证实的 Steam 状态集成 | 每项独立 RFC、来源/许可调查、隐私与回归检查 | 按独立功能 PR 与版本标记 | 由用户选择优先级；不自动启动，不预先承诺远端回写 |

## Phase 1 的具体边界
1. 创建 frontend/backend/tests/scripts 最小目录；验证并锁定 Node、Python、npm、uv 与库版本，提交 npm/Python 锁文件和可复现安装命令。配置 TypeScript strict、ESLint、格式化、Python lint、Vitest/Pytest/Playwright 与 CI。
2. 前端落地 DESIGN token、导航框架、按钮/输入/弹层/反馈状态、固定比例卡片和本地占位；仅合成数据页面，用于评审设计。1500 条 fixture 可在此建立，但完整虚拟库在 Phase 3 验收。
3. 后端建立配置、数据目录、健康接口、基础错误契约、空 schema 迁移和回环/同源安全壳；不加入真实 Steam 接入、分类或推荐。
4. Vite 构建由 FastAPI 托管，验证页面路由与 API 404；提供带空格/中文路径可运行的 Windows 指令，不要求安装全局 npm 包。
5. 提交工程和视觉证据；只在用户确认后进入 Phase 2。Phase 1 不进行真实数据同步、不导入真实库存、不实现完整核心业务。

## Phase 0 初始化检查记录
- 工作区 `H:\VSC workspacce\Library Atlas` 初始为空，无既有代码和 AGENTS；本轮仅创建文档、`.gitignore` 并初始化本地 Git。
- 已检测 Git 2.56.0.windows.3、Node 22.22.1、npm 10.9.4、Python 3.14.3；仅记录工具存在，不代表技术栈兼容测试通过。尚无依赖清单，因此未安装依赖或生成虚假锁文件。
- 初始未配置 Git 身份与远程；用户随后提供作者信息，已仅在当前仓库配置并用于 Phase 0 提交。GitHub 远程地址仍待用户提供，不擅自创建公开仓库。最终执行结果以本轮交付报告为准。
- Phase 0 不运行 Vitest/Pytest/Playwright，因为没有功能代码；执行文档完整性、内部链接与 Git 空白检查。
