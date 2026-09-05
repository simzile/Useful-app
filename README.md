# 口袋桥 · PocketBridge

把 Windows 电脑上的一个文件夹放进口袋。Android 手机可以通过 Wi-Fi 或手机流量上传、浏览和下载文件，无需打开微信，也无需电脑每次确认接收。

**个人使用的第一版源码项目。远程连接采用 Tailscale，文件保存在自己的电脑。** 项目包含 Android 原生 App、Windows 托盘程序、自动化测试和 GitHub Actions 构建配置。当前开发环境为 macOS；本地验证情况见 [验证记录](docs/VALIDATION.md)，Windows / Android 安装体验仍需真机验收。

## 使用方式

```text
Android 口袋桥 App
    │ 上传 / 浏览 / 下载（HTTPS，配对凭据 + 固定证书）
    │ Tailscale 私人网络：Wi-Fi、手机流量、异地网络
    ▼
Windows 口袋桥托盘程序 ──→ D:\PocketBridgeFiles
```

电脑文件夹是唯一主副本：电脑放入文件后，手机刷新即可看到；手机上传后，文件直接出现在电脑目录。下载到手机的文件是独立副本。本版不自动同步手机目录，也不把电脑目录挂载成 Android 系统磁盘。

## 第一版功能

- Windows 自选一个共享文件夹，关闭窗口后继续在托盘运行，可选择登录后自动运行。
- Android 扫码配对并记住电脑，也可粘贴配对信息导入。
- 浏览子文件夹、新建文件夹、批量上传、选择位置下载。
- Android 文件管理器或相册中的「分享 → 口袋桥」入口。
- 流式传输、进度显示；同名上传自动另存，保留原文件。
- HTTPS 传输，手机校验配对时固定的电脑证书；配对凭据存入 Android Keystore 加密的本地配置。
- Windows 可撤销所有手机的配对；后续请求立即失效，已经开始的传输可能继续完成。
- 接口限制在指定目录，拒绝路径穿越、Windows 特殊路径、符号链接和目录联接。

## 最快开始：用 GitHub 构建安装包

1. 新建自己的 GitHub 仓库，把本目录的**内容**上传到仓库根目录（包含 `.github` 隐藏目录）。个人使用可以建私有仓库。
2. 打开仓库 **Actions → Test and build PocketBridge**，等待构建通过；也可以点击 **Run workflow** 手动构建。
3. 在成功的运行页面底部下载 Artifacts：
   - `PocketBridge-Windows`：解压后运行 `PocketBridge.exe`。
   - `PocketBridge-Android-debug`：解压后在自己的 Android 手机上安装 `app-debug.apk`。
4. 按下面步骤安装 Tailscale、开启共享、扫码连接。

GitHub Actions 使用量及可用性以你的账户设置为准。仓库只存源码；运行时的文件、二维码、配对密钥、证书及个人路径不应上传。

**长期使用 Android 建议配置固定签名。** 默认 debug APK 用于首次试用；不同 CI 运行可能生成不同调试签名，不能保证直接覆盖安装。配置 [个人签名](docs/ANDROID_SIGNING.md) 后，构建会额外生成可持续更新的 `PocketBridge-Android-release`。请长期保存自己的签名密钥。

## 首次连接

1. 在 [Tailscale 官网](https://tailscale.com/docs/install) 给 Windows 和 Android 安装 Tailscale，加入同一个私人网络。通常使用同一个账户登录即可，平时保持连接。
2. Windows 打开口袋桥，选择专用共享文件夹，例如 `D:\PocketBridgeFiles`，点击「检测 Tailscale」，然后「开启共享」。目录需位于 **NTFS** 文件系统（本版用硬链接实现原子保存；exFAT/FAT32 不支持）。
3. 若手机连接超时，在 Windows **管理员 PowerShell** 中运行仓库的 `scripts/Enable-TailscaleFirewall.ps1`。规则仅放行电脑 Tailscale 地址上的 TCP 8765 端口，来源限制为 Tailscale IPv4 网段。
4. 电脑点击「手机扫码配对」，Android 口袋桥点击「扫码连接电脑」。确认地址来自自己的电脑后完成连接。
5. 以后手机打开 App，即可上传或取回文件。电脑可勾选「Windows 登录后自动运行」，然后关闭窗口留在托盘。

Tailscale 的作用是让两台设备在不同网络下仍能互相访问，**并不是把文件上传到网盘**。能直连时走点对点连接；部分网络会经过加密中继，速度可能低于局域网。详见官方 [远程访问文件服务说明](https://tailscale.com/docs/use-cases/personal-or-at-home-use/access-nas-media-file-servers) 和 [连接类型](https://tailscale.com/docs/reference/connection-types)。

## 开发与本地运行

### Windows 端

要求 Python 3.12 或更高版本（安装时包含 Tk）、Windows 10/11。在仓库根目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r desktop\requirements.txt
.\.venv\Scripts\python desktop\run.py
```

在 Windows 本机打包 EXE：

```powershell
.\.venv\Scripts\python -m pip install "pyinstaller>=6.11,<7"
.\.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name PocketBridge --paths desktop --collect-submodules pystray --hidden-import PIL._tkinter_finder desktop\run.py
```

产物位于 `dist/PocketBridge.exe`。[PyInstaller 需要在目标操作系统构建](https://pyinstaller.org/en/stable/)，因此 Windows EXE 在 Windows 本机或 GitHub 的 Windows runner 中生成。

文件服务也可以在其他操作系统以无界面模式运行，便于开发：

```bash
python3 -m venv .venv
.venv/bin/pip install -r desktop/requirements.txt
.venv/bin/python desktop/run.py --headless --host 127.0.0.1 --folder /tmp/pocketbridge-files --state-dir /tmp/pocketbridge-state
```

`127.0.0.1` 仅供本机测试，手机连接时换成**电脑实际拥有的 Tailscale IPv4 地址**。端口默认 8765，可通过 `--port` 修改。本版不面向直接暴露公网的部署。

### Android 端

要求 Android 8.0+。构建使用 JDK 17、Gradle 8.9、Android SDK 35 / Build Tools 35.0.0、Kotlin 2.0.21 和 AGP 8.7.3。

本项目不提交第三方 Gradle Wrapper 二进制；安装 Gradle 8.9 后，在 `android` 目录执行：

```bash
gradle wrapper --gradle-version 8.9
./gradlew :app:assembleDebug :app:lintDebug
```

Windows 下使用 `gradlew.bat`。Android Studio 可打开 `android` 目录；本机 SDK 路径写入不提交到 Git 的 `android/local.properties`，或设置 `ANDROID_HOME`。GitHub 构建已配置 SDK / JDK / Gradle。

### 文件服务测试

```bash
cd desktop
python -m unittest discover -s tests -v
```

覆盖 HTTPS 实际请求、上传下载完整性、中文文件名、零字节文件、同名并发上传、访问认证、配对撤销、上传中断清理、路径与链接限制等。

## 使用边界

- **电脑必须开机、联网并已登录 Windows；口袋桥和 Tailscale 必须运行。** 本版是登录后启动的托盘程序，不是登录前运行的 Windows 系统服务。电脑睡眠或关机时不能访问。
- Android 传输期间保持 App 在前台；本版暂不提供后台传输保障、断点续传、离线队列或自动同步。断网后重试；已完成的同名上传会另存。
- 单个文件上限 100 GiB，仍受磁盘可用空间、文件选择器和网络条件限制；这是协议限制，并非已经完成 100 GiB 实测。未知长度的云端文档会先缓存到手机，需要足够手机空间。
- 不显示以 `.` 开头的文件，不接受 Windows 保留名称；不提供远程删除、重命名或文件预览。
- 已下载到手机的文件不会随电脑内容更新。传输过程中请勿在电脑上同时编辑同一个文件。
- 默认只支持一台电脑、一套可整体撤销的配对凭据。二维码相当于访问钥匙，请仅用于自己的设备。
- Tailscale 是额外安装的软件，有自己的账户、网络可用性和 Android VPN 使用限制。本版未将其集成到 App 内，也未自建公网穿透/中继服务。

## 项目结构

```text
desktop/pocketbridge/   Windows UI、配置、HTTPS 服务与文件存储
desktop/tests/          文件存储及真实 HTTPS 接口测试
android/               原生 Kotlin Android App
scripts/               Windows Tailscale 防火墙配置
.github/workflows/     自动测试、Windows EXE / Android APK 构建
docs/                  协议、签名和真机验收说明
```

更详细的部署排查见 [远程连接说明](docs/REMOTE_SETUP.md)，接口见 [API 说明](docs/API.md)。

