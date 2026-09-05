# Android 个人签名

调试 APK 适合首次试用。长期使用请固定一份个人签名，后续版本才能覆盖升级并保留已保存的配对信息。

在安装了 JDK 的电脑上生成个人密钥（将密钥保存到仓库外的安全位置，命令会交互式询问密码）：

```bash
keytool -genkeypair -v -keystore pocketbridge-personal.jks -alias pocketbridge -keyalg RSA -keysize 3072 -validity 10000
```

把 `.jks` 文件做 Base64 编码，在仓库 **Settings → Secrets and variables → Actions → New repository secret** 设置：

| Secret | 内容 |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | `.jks` 文件的 Base64 字符串，单行 |
| `ANDROID_KEYSTORE_PASSWORD` | 密钥库密码 |
| `ANDROID_KEY_ALIAS` | 例如 `pocketbridge` |
| `ANDROID_KEY_PASSWORD` | 此别名的私钥密码，通常与密钥库密码相同 |

在 PowerShell 中可将 Base64 直接复制到剪贴板，避免输出到终端记录：

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\YourPrivateKeys\pocketbridge-personal.jks')) | Set-Clipboard
```

重新运行 workflow 后，从 `PocketBridge-Android-release` 下载安装包。签名数据仅在 runner 临时目录解码，不作为产物上传。

从调试版切换到个人签名版，通常需要先卸载调试版并重新扫码配对。请备份签名密钥和密码；以后增加 `android/app/build.gradle.kts` 的 `versionCode`，再用同一份密钥构建升级版本。

本地发布构建使用环境变量 `ANDROID_KEYSTORE_PATH`（绝对路径）、`ANDROID_KEYSTORE_PASSWORD`、`ANDROID_KEY_ALIAS`、`ANDROID_KEY_PASSWORD`，执行 `gradle :app:assembleRelease`。没有配置密钥时 release 输出为未签名文件，不能直接安装；默认的 debug 构建仍可用。

