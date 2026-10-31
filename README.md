# Library Atlas

运行在你自己电脑上的多平台作品库，面向 Windows 11。目前支持 DLsite，Steam 尚未开放。

- 同步已购作品，按类型、制作方、状态筛选和搜索，1500 部以上也能流畅浏览
- 下载、解压，自动关联 `DLsiteNest\Library` 里已有的作品
- 启动游戏，记录单次与累计游玩时长、最近游玩和月度统计
- 内置音声播放器和漫画、CG、PDF 阅读器
- 查找存档位置，把确认过的存档备份到你自己的 Google Drive
- 评分、备注、收藏夹，全部只保存在本机

所有资料都留在这台电脑上，默认没有遥测，服务只对本机开放。

## 安装

**完整步骤见 [安装教程](docs/INSTALL.md)。** 已经装好 Python 3.14、Node.js 22.22.1 和 Git 的话：

```powershell
git clone https://github.com/4dfeel/Library-Atlas.git
cd Library-Atlas
.\scripts\setup-backend.cmd
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
.\scripts\serve.cmd
```

然后打开 <http://127.0.0.1:8765/>。解压 RAR、7z 还需要 7-Zip 25.01 或更新版本。

## 开发

- [运行与开发说明](docs/LOCAL_DEVELOPMENT.md)、[本地 API](docs/LOCAL_API.md)
- [产品需求](docs/PRODUCT.md)、[设计规范](docs/DESIGN.md)、[架构](docs/ARCHITECTURE.md)、[路线图](docs/ROADMAP.md)

```powershell
scripts\setup-backend.cmd dev
cd backend
.venv\Scripts\python -m pytest
cd ..\frontend
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run format:check
npm.cmd test
npm.cmd run build
npx.cmd --no-install playwright install chromium
npm.cmd run test:e2e
```

页面测试跑在隔离测试库上：每次运行都新建一个临时数据库，写入合成样本，由真实的本地服务托管生产构建，不会碰到你的真实资料。快速检查可以用 `npm.cmd run test:smoke`。
