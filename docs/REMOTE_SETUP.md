# 跨网络连接与排查

本版采用外置 Tailscale：Windows 上的 HTTPS 文件服务绑定电脑 Tailscale IPv4，Android 通过相同地址访问。手机可使用流量，电脑可位于路由器或运营商 NAT 后；连接表现取决于两端网络和 Tailscale 连通性。

首次需在两端安装并登录 Tailscale。口袋桥不代替 Tailscale 的登录流程，也不自动配置账户或路由器。不要为这个第一版给路由器配置公网端口转发。

## 连不上时按这个顺序检查

1. 电脑已开机、没有睡眠，Tailscale 显示已连接，口袋桥显示「正在共享」。
2. 手机 Tailscale 显示已连接，设备列表中可以看到电脑。若手机正在使用另一个 VPN，先处理 VPN 冲突。
3. 核对二维码里的 `100.x.x.x` 是否是电脑当前的 Tailscale 地址。重新加入网络或更换设备后可能需要重新检测地址、开启共享并扫码。
4. 检查私人网络的访问规则是否允许手机访问电脑 TCP 8765。
5. 在 Windows 管理员 PowerShell 中运行 `scripts/Enable-TailscaleFirewall.ps1`；若改过端口，传入 `-Port 新端口`。此脚本不改变 Tailscale 网络访问规则。
6. 提示「配对凭据无效」时重新扫码；提示证书不匹配时核对是否连到原来的电脑，确认后重新配对。

需要停止时，在托盘打开主窗口并停止共享；彻底退出请选择托盘菜单「退出」。停服务与撤销配对不会保证终止已经开始的传输。

## 配置保存位置

- Windows：`%LOCALAPPDATA%\PocketBridge\config.json`、`certificate.pem`、`private-key.pem`、`app.log`。
- Android：App 私有配置，配对内容用 Android Keystore 中的 AES-GCM 密钥加密；禁用应用备份。
- 共享文件：Windows 窗口中选择的独立目录，默认在用户目录下 `PocketBridgeFiles`。

共享目录不能包含上述程序配置目录。不要公开配对二维码或把运行时配置加入 Git。删除电脑的证书/配置会使原配对失效；需重新扫码。

## 同一 Wi-Fi 使用

也可以停止共享，填写电脑的局域网 IPv4（例如实际分配到的 `192.168.x.x`）后重新开启并扫码。此时需要相应的局域网防火墙规则；提供的脚本只适用于 Tailscale。离开局域网后，此地址通常不能继续访问，因此异地使用建议一直用 Tailscale 地址。

## 后续可扩展方向

可在文件协议不变的前提下，添加多台电脑、断点续传、前台传输服务、分设备授权或自动同步。若希望只安装自己的 App，需要另外设计和运维设备发现、认证、公网穿透与中继，不能只把当前地址换成公网 IP。

官方资料：[安装 Tailscale](https://tailscale.com/docs/install)、[远程文件服务](https://tailscale.com/docs/use-cases/personal-or-at-home-use/access-nas-media-file-servers)、[连接类型](https://tailscale.com/docs/reference/connection-types)。

