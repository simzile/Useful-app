package dev.pocketbridge.app

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

data class RemoteEntry(val name: String, val path: String, val directory: Boolean, val size: Long)

class PeerClient(private val pairing: Pairing) {
    @Volatile private var active: HttpsURLConnection? = null
    private fun matches(cert: X509Certificate): Boolean =
        MessageDigest.getInstance("SHA-256").digest(cert.encoded).hex() == pairing.fingerprint

    private val tls = SSLContext.getInstance("TLS").apply {
        init(null, arrayOf<TrustManager>(object : X509TrustManager {
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {
                throw CertificateException("Not a client certificate verifier")
            }
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                if (chain.isEmpty() || !matches(chain[0])) throw CertificateException("电脑证书与配对信息不匹配")
                chain[0].checkValidity()
            }
        }), null)
    }

    private fun connection(endpoint: String, method: String = "GET"): HttpsURLConnection =
        (URL(pairing.url + endpoint).openConnection() as HttpsURLConnection).apply {
            sslSocketFactory = tls.socketFactory
            // The QR-pinned leaf certificate replaces DNS-based identity checks.
            hostnameVerifier = javax.net.ssl.HostnameVerifier { _, session ->
                try { matches(session.peerCertificates[0] as X509Certificate) } catch (_: Exception) { false }
            }
            requestMethod = method
            instanceFollowRedirects = false
            connectTimeout = 15000
            readTimeout = 60000
            useCaches = false
            setRequestProperty("Authorization", "Bearer ${pairing.token}")
            active = this
        }

    private fun check(connection: HttpsURLConnection) {
        if (connection.responseCode !in 200..299) {
            val raw = connection.errorStream?.use { input ->
                val buffer = ByteArray(8192)
                var count = 0
                while (count < buffer.size) {
                    val read = input.read(buffer, count, buffer.size - count)
                    if (read < 0) break
                    count += read
                }
                String(buffer, 0, count, Charsets.UTF_8)
            }
            val error = try { JSONObject(raw ?: "{}").optString("error", "连接失败") } catch (_: Exception) { "连接失败" }
            throw IOException("$error（${connection.responseCode}）")
        }
    }

    private fun json(endpoint: String, method: String = "GET"): JSONObject {
        val request = connection(endpoint, method)
        try {
            check(request)
            return request.inputStream.bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }
        } finally { request.disconnect(); active = null }
    }

    fun info(): JSONObject = json("/v1/info")
    fun list(path: String): List<RemoteEntry> {
        val entries = json("/v1/files?path=${encode(path)}").getJSONArray("entries")
        return (0 until entries.length()).map { index -> entries.getJSONObject(index).let {
            RemoteEntry(it.getString("name"), it.getString("path"), it.getBoolean("directory"), it.getLong("size"))
        } }
    }
    fun mkdir(path: String) { json("/v1/folder?path=${encode(path)}", "POST") }
    fun cancel() { active?.disconnect() }

    fun upload(resolver: ContentResolver, uri: Uri, folder: String, cacheDir: File,
               progress: (Long, Long) -> Unit): String {
        var name = "手机文件"
        var size = -1L
        resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val nameColumn = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeColumn = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (nameColumn >= 0 && !cursor.isNull(nameColumn)) name = cursor.getString(nameColumn)
                if (sizeColumn >= 0 && !cursor.isNull(sizeColumn)) size = cursor.getLong(sizeColumn)
            }
        }
        require(name.isNotBlank() && !name.contains('/') && !name.contains('\\')) { "文件名称无效" }
        var temporary: File? = null
        try {
            // Some document/cloud providers have no known size. Stage only those
            // streams to app cache so the protocol can enforce exact lengths.
            if (size < 0) {
                val staged = File.createTempFile("upload-", ".part", cacheDir)
                temporary = staged
                resolver.openInputStream(uri)?.use { input -> staged.outputStream().use { output ->
                    val buffer = ByteArray(256 * 1024)
                    var count = 0L
                    while (true) {
                        if (Thread.currentThread().isInterrupted) throw IOException("已取消")
                        val read = input.read(buffer)
                        if (read < 0) break
                        output.write(buffer, 0, read)
                        count += read
                        if (count > 100L * 1024 * 1024 * 1024) throw IOException("单文件最大 100 GiB")
                        progress(count, -1)
                    }
                } } ?: throw IOException("无法读取所选文件")
                size = staged.length()
            }
            require(size <= 100L * 1024 * 1024 * 1024) { "单文件最大 100 GiB" }
            val path = if (folder.isEmpty()) name else "$folder/$name"
            val request = connection("/v1/file?path=${encode(path)}", "PUT")
            val digest = MessageDigest.getInstance("SHA-256")
            try {
                request.doOutput = true
                request.setRequestProperty("Content-Type", "application/octet-stream")
                request.setFixedLengthStreamingMode(size)
                val source = temporary?.inputStream() ?: resolver.openInputStream(uri) ?: throw IOException("无法读取文件")
                source.use { input -> request.outputStream.use { output ->
                    val buffer = ByteArray(256 * 1024)
                    var sent = 0L
                    while (true) {
                        if (Thread.currentThread().isInterrupted) throw IOException("已取消")
                        val read = input.read(buffer)
                        if (read < 0) break
                        output.write(buffer, 0, read)
                        digest.update(buffer, 0, read)
                        sent += read
                        progress(sent, size)
                    }
                    if (sent != size) throw IOException("文件在读取时发生变化，请重试")
                } }
                check(request)
                val result = request.inputStream.bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }
                if (result.getString("sha256") != digest.digest().hex()) throw IOException("上传后校验失败，请核对电脑文件")
                return result.getString("path")
            } finally { request.disconnect(); active = null }
        } finally { temporary?.delete() }
    }

    fun download(resolver: ContentResolver, entry: RemoteEntry, destination: Uri, progress: (Long, Long) -> Unit) {
        val request = connection("/v1/file?path=${encode(entry.path)}")
        try {
            check(request)
            val size = request.contentLengthLong
            if (size < 0) throw IOException("电脑未返回有效文件长度")
            request.inputStream.use { input ->
                (resolver.openOutputStream(destination, "wt") ?: throw IOException("无法打开保存位置")).use { output ->
                    val buffer = ByteArray(256 * 1024)
                    var received = 0L
                    while (true) {
                        if (Thread.currentThread().isInterrupted) throw IOException("已取消")
                        val read = input.read(buffer)
                        if (read < 0) break
                        output.write(buffer, 0, read)
                        received += read
                        progress(received, size)
                    }
                    if (received != size) throw IOException("下载不完整，请重试")
                }
            }
        } finally { request.disconnect(); active = null }
    }

    companion object {
        private fun encode(value: String): String = URLEncoder.encode(value, "UTF-8")
        private fun ByteArray.hex() = joinToString("") { "%02x".format(it.toInt() and 255) }
    }
}
