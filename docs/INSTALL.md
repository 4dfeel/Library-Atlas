# Library Atlas 安装教程

Library Atlas 是一个运行在你自己电脑上的作品库：浏览 DLsite 已购作品，下载、解压、启动，记录游玩时长，并可把存档备份到你自己的 Google Drive。所有资料都保存在本机，服务只对本机开放，局域网和外网都访问不到。

下面的步骤不需要编程经验，照着做即可，全程大约 10 分钟。

## 1. 准备环境

系统要求 Windows 11。需要先安装下面这些软件：

| 软件 | 版本 | 用途 | 下载 |
| --- | --- | --- | --- |
| Python | 3.14 | 运行本地服务 | [python.org](https://www.python.org/downloads/windows/) |
| Node.js | 22.22.1 | 构建页面，只在安装和更新时用到 | [nodejs.org](https://nodejs.org/dist/v22.22.1/) |
| Git | 任意 | 下载和更新代码 | [git-scm.com](https://git-scm.com/download/win) |
| 7-Zip（可选） | 25.01 或更新 | 解压 RAR 和 7z 作品，不装时只能解压 ZIP | [7-zip.org](https://www.7-zip.org/) |

安装 Python 时保持默认选项即可，确认勾选了 **py launcher**。全部装好后，打开一个新的 PowerShell 窗口检查：

```powershell
py -3.14 --version
node --version
git --version
```

三条命令都显示出版本号，就可以继续。如果提示“找不到命令”，请关掉窗口重新打开一次，还不行就重新安装对应的软件。

## 2. 下载代码

先进入你想存放程序的文件夹，再下载。路径里有中文或空格都没关系。

```powershell
git clone https://github.com/4dfeel/Library-Atlas.git
cd Library-Atlas
```

这个仓库目前是私有的，下载时需要用有访问权限的 GitHub 账号登录。

## 3. 安装并构建

以下命令都在 `Library-Atlas` 文件夹里执行，依次运行：

```powershell
.\scripts\setup-backend.cmd
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
```

第一次运行要下载依赖，需要几分钟。中间出现的 `npm warn` 可以忽略，只要最后没有红色的 `error` 就算成功。

## 4. 启动

```powershell
.\scripts\serve.cmd
```

窗口里显示 `Library Atlas · real · http://127.0.0.1:8765` 后，用浏览器打开 <http://127.0.0.1:8765/>。

**使用期间不要关闭这个窗口。** 要退出时，在窗口里按 `Ctrl+C`。下次使用只需要在 `Library-Atlas` 文件夹里再运行这一条命令，也可以直接双击 `scripts\serve.cmd`。

## 5. 第一次使用

打开后作品库是空的，这是正常的。按下面的顺序设置：

1. **登录 DLsite**：进入“设置 → 账号”登录。登录后的会话保存在 Windows 凭据管理器。只有勾选“记住账号和密码”，才会同时保存密码。
2. **同步作品**：登录后点“同步”，已购作品会进入作品库。
3. **设置文件夹**：在“设置 → 文件夹”选择作品的下载和解压位置。
4. **关联已有作品**：如果你已经用 DLsiteNest 下载过作品，Atlas 会自动查找各盘的 `DLsiteNest\Library` 并关联，只写关联记录，不会改动文件。其他位置可以在“设置 → 本机作品库”手动添加。

### 可选：云存档

想把存档备份到自己的 Google Drive，需要先创建你自己的 Google 客户端，步骤写在“设置 → 云存档”里。授权只在 Google 官方页面进行，只上传你确认过的存档，不上传游戏本体。

## 更新到新版本

先在服务窗口按 `Ctrl+C` 关闭服务，然后执行：

```powershell
git pull
.\scripts\setup-backend.cmd
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
.\scripts\serve.cmd
```

你的资料不会丢失。资料库结构有变化时，程序会在启动时先自动备份，再升级。

## 资料保存在哪里

| 内容 | 位置 |
| --- | --- |
| 资料库、封面缓存、自动备份 | `%LOCALAPPDATA%\LibraryAtlas\profiles\default` |
| 登录会话、记住的密码、Google 授权 | Windows 凭据管理器，名称以 `LibraryAtlas/` 开头 |
| 作品文件 | 你在“设置 → 文件夹”里选择的位置 |

## 卸载

1. 关闭服务。
2. 想保留作品文件就不要动作品文件夹，它们不在程序目录里。
3. 删除 `Library-Atlas` 文件夹。
4. 如果不再需要资料，删除 `%LOCALAPPDATA%\LibraryAtlas`。这一步会清除评分、备注和游玩记录，无法恢复。
5. 打开“控制面板 → 凭据管理器 → Windows 凭据”，删除以 `LibraryAtlas/` 开头的条目。

## 常见问题

**提示端口 8765 已被占用**
通常是 Atlas 已经在运行了，直接打开 <http://127.0.0.1:8765/> 试试。如果是别的程序占用，可以换一个端口：`.\scripts\serve.cmd --port 8766`，然后打开对应的地址。

**运行 `setup-backend.cmd` 时提示找不到 `py`**
重新运行 Python 安装程序，勾选 **py launcher**。

**页面显示“前端尚未构建”**
第 3 步的 `npm.cmd run build` 没有成功，重新执行第 3 步。

**页面显示“本地服务未连接”**
运行 `serve.cmd` 的窗口被关掉了，重新运行即可。你的资料不受影响。

**RAR 或 7z 作品无法解压**
安装或升级 7-Zip 到 25.01 以上。Atlas 不会使用旧版本，因为旧版本存在解压时写到目标文件夹外面的安全漏洞。

## 安全提示

- 服务只监听 `127.0.0.1`，不要用端口转发或内网穿透把它暴露出去，它没有登录这一步。
- 游戏是以你的身份运行的程序。来源不明的作品不要直接运行，恶意程序能读到你的 Windows 凭据。
- 不要把账号、密码、Cookie 或 Google 客户端密钥发给任何人，也不要提交到 Git。
