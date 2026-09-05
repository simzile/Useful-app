# 验证记录

日期：2026-09-05。开发环境：macOS / Apple Silicon。

## 已完成

| 检查 | 结果 |
|---|---|
| Python 全部源码语法检查 | 通过 |
| 文件存储与实际 HTTPS 接口测试 | 21 项通过，0 跳过 |
| Android Kotlin 源码编译 | Kotlin 2.0.21、Android SDK 35、JVM target 17，通过 |
| Kotlin 客户端与 Python 服务实际 HTTPS 联通 | 通过 |
| Kotlin 客户端中文目录创建和浏览 | 通过 |
| Kotlin 客户端拒绝错误的证书指纹 | 通过 |
| Kotlin 客户端拒绝错误的配对凭据 | 通过 |
| Android Manifest 和资源 XML 解析 | 通过 |
| GitHub Actions YAML 语法解析 | 通过 |

Python 测试覆盖：2 MiB 二进制文件实际 HTTPS 上传下载、SHA-256 摘要、认证、凭据撤销、证书持久化、拒绝不受信任的证书、中文目录、零字节文件、并发同名上传、保留原文件、失败上传清理、过长或非法路径、符号链接限制，以及阻止把凭据目录共享出去。

本地 Python 版本为 3.14.4，测试依赖为 cryptography 46.0.0 / cffi 2.0.0。依赖下载后按 PyPI 元数据核对 SHA-256，安装到临时虚拟环境，没有向系统 Python 安装包。GitHub CI 使用 Python 3.12 和 `requirements.txt` 中范围允许的依赖版本。

Android 检查采用 Kotlin 编译器直接编译全部 `.kt` 文件，依赖 Android 35 的 `android.jar` 与 ZXing 4.3.0。编译有旧式扫码入口和返回键 API 的弃用警告，无编译错误。协议联通检查则将实际 `Pairing.kt`、`PeerClient.kt` 编译为 JVM 11 测试代码，使用 Java 11、JSON-java 与实际启动在 127.0.0.1 的 Python HTTPS 服务通信；没有替换或模拟文件协议、TLS 验证逻辑。

## 尚未完成

- 完整 Android Gradle 构建、资源打包和 Android Lint：已配置在 GitHub Actions 中，尚未实际运行该 workflow。
- Windows EXE 构建及启动、托盘、开机登录自启：需要 Windows runner 和 Windows 真机。
- Android 真机安装、扫码、系统文件选择器、分享入口、下载保存和前后台切换。
- 两台设备通过不同运营商网络 / 手机流量 / Tailscale 的实测。
- 大于 2 MiB 的端到端传输、超大文件、断网恢复体验与长时间稳定性；100 GiB 是协议上限，不是已验证性能指标。

因此当前产物应作为 **v0.1.0 源码初版** 验收，不能视为已经完成两端安装与跨网实测的正式发行版。

## 建议的首次真机验收

1. GitHub Actions 的两个 desktop jobs 和 android job 通过，下载安装包。
2. 两端 Tailscale 同时连接，Windows 选择独立 NTFS 文件夹，手机成功扫码并记住电脑。
3. 从手机上传中文名图片、PDF、空文件及多个文件；核对电脑落盘内容和大小。
4. 同一个文件上传两次，确认原文件保留，第二份自动另存。
5. 在电脑目录放入子文件夹，手机刷新、进入、下载到系统选择的位置。
6. 手机切换到流量后重复上传下载；传输过程中断开网络，确认电脑没有新出现的半成品文件，手机失败下载得到明确提示。
7. 关闭 Windows 主窗口后继续上传；电脑重启并登录后检查自动运行；撤销配对后旧手机请求失败，重新扫码恢复。

自动化测试命令见主 README。以上未完成项需要在目标设备上记录实际结果后，才能将本项目标记为可长期使用的发行版。
