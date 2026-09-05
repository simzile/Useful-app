# PocketBridge API v1

HTTPS 基础地址：`https://<电脑 Tailscale IPv4>:8765`。所有请求都必须带 `Authorization: Bearer <token>`。请求不自动跳转；Android 同时校验二维码中的 SHA-256 证书指纹，不接受任意自签名证书。

配对二维码是版本化 JSON，包含 `version`（1）、`url`、`token`、`fingerprint`（DER 证书 SHA-256 小写十六进制）。这是长效凭据，直至电脑撤销配对。配置只存本机，接口不提供匿名配对。

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/v1/info` | 返回协议版本与共享目录名称，不暴露绝对路径 |
| GET | `/v1/files?path=` | 返回目录条目，空路径表示共享根目录 |
| GET | `/v1/file?path=docs%2Fpaper.pdf` | 按字节流下载文件，带 Content-Length |
| PUT | `/v1/file?path=docs%2Fpaper.pdf` | 原始文件请求体上传，必须有有效 Content-Length |
| POST | `/v1/folder?path=docs` | 创建单层文件夹，父文件夹必须存在 |

相对路径按 UTF-8 URL 编码。条目字段为 `name`、`path`、`directory`、`size`（字节）和 `modified`（Unix 秒）。目录排在文件之前。

成功上传返回 HTTP 201 和 `path`、`size`、`sha256`。同名文件不会覆盖，返回的 `path` 可能变成 `paper (1).pdf`。可选请求头 `X-Content-SHA256` 让服务端在保存前比较校验值；Android 默认边发送边算摘要，再与服务端响应比较。

上传先写入同目录隐藏临时文件，读满声明长度并刷新到磁盘后，通过不覆盖目标的硬链接操作提交；最后删除临时名称。传输失败会清理临时文件，程序被强制终止或电脑掉电时可能留下隐藏的 `.pocketbridge-*` 残片，可在停服务后清理。

错误响应为 JSON `{ "error": "说明" }`，例如 400 路径或请求无效、401 配对无效、403 链接越界、404 不存在、409 名称冲突、411 缺少长度、413 文件过大、408 超时、500 磁盘读写失败。流式下载已经发出响应头后若出错，连接提前关闭，客户端依据 Content-Length 检测未完成下载。

服务端至多同时处理 16 条连接，读写及 TLS 握手超时 60 秒，单文件上限 100 GiB。不支持 chunked 上传、Range 下载、CORS、删除、匿名访问或公网账户服务。
