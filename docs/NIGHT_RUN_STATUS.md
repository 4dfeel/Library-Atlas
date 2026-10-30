# 夜间连续开发账本

用户授权范围：C6–C11（2026-10-31）。C12–C15 未授权，不做。Steam 延期。

| 检查点 | 状态 | 分支 | 报告 |
| --- | --- | --- | --- |
| 用户反馈：压缩包清理、日文文件名、更新按钮 | 已验证（合成）；真实待用户 | `phase-2/checkpoint-5` | [C5](PHASE2_CHECKPOINT5_REPORT.md) |
| C6 官方介绍 | 已实现待验：8 部真实作品读取成功；无视频内嵌 | `phase-2/checkpoint-6` | [C6](PHASE2_CHECKPOINT6_REPORT.md) |
| C7 手动关联与启动 | 已实现待验：真实游戏启动待人工 | `phase-2/checkpoint-7` | [C7](PHASE2_CHECKPOINT7_REPORT.md) |
| C8 跨盘发现导入 | 已实现，真实只读核对通过；批量关联待用户 | `phase-2/checkpoint-8` | [C8](PHASE2_CHECKPOINT8_REPORT.md) |
| C9 存档保护更新 | 已实现，合成验证通过；真实更新待人工 | `phase-2/checkpoint-9` | [C9](PHASE2_CHECKPOINT9_REPORT.md) |
| C10 音声 | 已实现，自制音频验证通过；真实作品待人工 | `phase-2/checkpoint-10` | [C10](PHASE2_CHECKPOINT10_REPORT.md) |
| C11 漫画/CG | 已实现，自制文件验证通过；真实作品待人工 | `phase-2/checkpoint-11` | [C11](PHASE2_CHECKPOINT11_REPORT.md) |

本账本不记录私人路径、作品名或凭据。

## 最终回归（2026-10-31，C11 之后）
| 项目 | 结果 |
| --- | --- |
| 后端全量 pytest | 已通过：754 |
| 前端 Vitest | 已通过：116 |
| Playwright 全量 | 341 通过，1 失败，456 按设计跳过（各用例只跑指定分辨率档）。失败的是 `detail.spec.ts` 列表往返，属测试时序问题：虚拟列表滚动未稳定时选了边缘行。已修复，单独重复 8 次通过、窄窗口通过；**修复后没有再跑一遍全量** |
| 真实游戏启动、更新、音声、漫画、PDF | 未执行，需要人工检查 |
