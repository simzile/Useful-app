package dev.pocketbridge.app

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.net.URI
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class Pairing(val url: String, val token: String, val fingerprint: String) {
    fun json(): String = JSONObject().put("version", 1).put("url", url)
        .put("token", token).put("fingerprint", fingerprint).toString()

    companion object {
        fun parse(value: String): Pairing {
            require(value.length <= 4096) { "配对信息过长" }
            val data = JSONObject(value)
            require(data.getInt("version") == 1) { "不支持此配对版本" }
            val url = data.getString("url").trimEnd('/')
            val uri = URI(url)
            require(uri.scheme == "https" && uri.userInfo == null && uri.query == null && uri.fragment == null
                && uri.path.isNullOrEmpty() && uri.port in 1..65535) { "配对地址无效" }
            val octets = (uri.host ?: "").split('.')
            require(octets.size == 4 && octets.all { it.matches(Regex("[0-9]{1,3}")) && it.toInt() in 0..255 }) {
                "请使用电脑的 IPv4 地址"
            }
            val token = data.getString("token")
            val fingerprint = data.getString("fingerprint").lowercase()
            require(token.matches(Regex("[A-Za-z0-9_-]{32,128}")) && fingerprint.matches(Regex("[0-9a-f]{64}"))) {
                "配对凭据格式无效"
            }
            return Pairing(url, token, fingerprint)
        }
    }
}

/** Pairing secrets are encrypted with a non-exportable Android Keystore key. */
class PairingStore(context: Context) {
    private val prefs = context.getSharedPreferences("paired-computer", Context.MODE_PRIVATE)
    private val alias = "pocketbridge-pairing-v1"

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }

    fun save(pairing: Pairing) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val encrypted = cipher.doFinal(pairing.json().toByteArray(Charsets.UTF_8))
        check(prefs.edit().putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString("data", Base64.encodeToString(encrypted, Base64.NO_WRAP)).commit()) { "配对信息保存失败" }
    }

    fun load(): Pairing? {
        val data = prefs.getString("data", null) ?: return null
        val iv = prefs.getString("iv", null) ?: return null
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
                init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)))
            }
            Pairing.parse(String(cipher.doFinal(Base64.decode(data, Base64.NO_WRAP)), Charsets.UTF_8))
        } catch (_: Exception) {
            clear()
            null
        }
    }

    fun clear() { prefs.edit().clear().commit() }
}

