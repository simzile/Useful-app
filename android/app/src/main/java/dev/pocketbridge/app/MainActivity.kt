package dev.pocketbridge.app

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.SystemClock
import android.provider.DocumentsContract
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import com.google.zxing.integration.android.IntentIntegrator
import java.util.concurrent.Executors

@Suppress("DEPRECATION")
class MainActivity : Activity() {
    private lateinit var store: PairingStore
    private var client: PeerClient? = null
    private val worker = Executors.newSingleThreadExecutor()
    private lateinit var content: LinearLayout
    private lateinit var folderLabel: TextView
    private lateinit var status: TextView
    private lateinit var progress: ProgressBar
    private lateinit var files: LinearLayout
    private val controls = mutableListOf<View>()
    private var folder = ""
    private var busy = false
    private var pendingDownload: RemoteEntry? = null
    private var pendingShares = emptyList<Uri>()
    private var lastProgress = 0L
    private val blue = Color.rgb(36, 92, 230)
    private val ink = Color.rgb(21, 40, 70)

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        store = PairingStore(this)
        client = store.load()?.let { PeerClient(it) }
        folder = state?.getString("folder") ?: ""
        state?.getString("download")?.let { raw ->
            val data = org.json.JSONObject(raw)
            pendingDownload = RemoteEntry(data.getString("name"), data.getString("path"), false, data.getLong("size"))
        }
        // This app keeps transfers in the foreground; failed uploads never replace
        // desktop files. Orientation is handled without destroying the Activity.
        drawScreen()
        captureShares(intent)
        if (client != null) refresh() else status.text = "先连接 Tailscale，再扫描电脑上的配对二维码。"
    }

    override fun onSaveInstanceState(state: Bundle) {
        state.putString("folder", folder)
        pendingDownload?.let { entry -> state.putString("download", org.json.JSONObject()
            .put("name", entry.name).put("path", entry.path).put("size", entry.size).toString()) }
        super.onSaveInstanceState(state)
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun label(value: String, size: Float = 15f, bold: Boolean = false): TextView = TextView(this).apply {
        text = value; textSize = size; setTextColor(ink)
        if (bold) setTypeface(typeface, Typeface.BOLD)
        setPadding(0, dp(8), 0, dp(8))
    }
    private fun rounded(color: Int) = GradientDrawable().apply {
        setColor(color); cornerRadius = dp(16).toFloat()
    }
    private fun action(text: String, parent: LinearLayout = content, click: () -> Unit): Button = Button(this).apply {
        this.text = text; isAllCaps = false; setTextColor(blue)
        setOnClickListener { if (!busy) click() }
        parent.addView(this, LinearLayout.LayoutParams(-1, dp(52)).apply { bottomMargin = dp(6) })
        controls.add(this)
    }

    private fun drawScreen() {
        val scroll = ScrollView(this).apply { setBackgroundColor(Color.rgb(243, 246, 251)); isFillViewport = true }
        content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(22), dp(24), dp(22), dp(32)) }
        scroll.addView(content)
        // Respect Android 15 edge-to-edge system bars.
        scroll.setOnApplyWindowInsetsListener { view, insets ->
            view.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            insets
        }
        setContentView(scroll)
        content.addView(label("口袋桥", 32f, true))
        content.addView(label("POCKETBRIDGE  /  我的电脑文件夹", 12f).apply { setTextColor(Color.rgb(86, 112, 143)) })
        folderLabel = label("共享文件夹", 20f, true)
        content.addView(folderLabel)
        val pairingRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        content.addView(pairingRow)
        action("扫码连接电脑", pairingRow) {
            IntentIntegrator(this).setDesiredBarcodeFormats(IntentIntegrator.QR_CODE)
                .setPrompt("扫描口袋桥 Windows 端的配对二维码")
                .setBeepEnabled(false).setOrientationLocked(false).initiateScan()
        }.layoutParams = LinearLayout.LayoutParams(0, dp(52), 1f)
        action("手动导入", pairingRow) { importPairing() }.layoutParams = LinearLayout.LayoutParams(0, dp(52), 1f)
        action("＋  选择文件上传") { chooseUpload() }.apply {
            backgroundTintList = android.content.res.ColorStateList.valueOf(blue)
            setTextColor(Color.WHITE)
        }
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        content.addView(row)
        action("上一级", row) {
            folder = folder.substringBeforeLast('/', "")
            refresh()
        }.layoutParams = LinearLayout.LayoutParams(0, dp(52), 1f)
        action("刷新", row) { refresh() }.layoutParams = LinearLayout.LayoutParams(0, dp(52), 1f)
        action("新建文件夹", row) { createFolder() }.layoutParams = LinearLayout.LayoutParams(0, dp(52), 1f)
        progress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply { visibility = View.GONE; max = 100 }
        content.addView(progress, LinearLayout.LayoutParams(-1, dp(10)))
        status = label("连接中…", 13f).apply { setTextColor(Color.rgb(86, 112, 143)) }
        content.addView(status)
        files = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        content.addView(files)
        action("断开并清除配对") {
            AlertDialog.Builder(this).setTitle("清除这台电脑的配对？")
                .setMessage("文件仍保存在电脑上。再次连接时需要扫码。")
                .setNegativeButton("取消", null).setPositiveButton("清除") { _, _ ->
                    client?.cancel(); client = null; store.clear(); folder = ""
                    files.removeAllViews(); folderLabel.text = "共享文件夹"; status.text = "配对已清除"
                }.show()
        }
        content.addView(label("文件保存在你的电脑。传输期间请保持此页面在前台；电脑需开机并开启共享。", 12f))
    }

    private fun connection(): PeerClient? {
        if (client == null) status.text = "请先扫码连接电脑"
        return client
    }

    private fun task(message: String, work: () -> Unit) {
        if (busy) return
        busy = true; lastProgress = 0
        controls.forEach { it.isEnabled = false }
        progress.visibility = View.VISIBLE; progress.isIndeterminate = true
        status.text = message
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        worker.execute {
            try { work() } catch (error: Exception) {
                ui { status.text = "${error.message ?: "连接失败"}\n请检查 Tailscale、电脑共享状态和防火墙。" }
            } finally {
                ui {
                    busy = false; controls.forEach { it.isEnabled = true }
                    progress.visibility = View.GONE
                    window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    if (pendingShares.isNotEmpty() && client != null) offerShares()
                }
            }
        }
    }

    private fun ui(work: () -> Unit) = runOnUiThread { if (!isFinishing && !isDestroyed) work() }

    private fun refresh() {
        val peer = connection() ?: return
        task("正在读取电脑文件夹…") {
            val info = peer.info()
            val entries = peer.list(folder)
            ui { render(entries); status.text = "已连接 · ${info.getString("folder")} · ${entries.size} 项" }
        }
    }

    private fun render(entries: List<RemoteEntry>) {
        folderLabel.text = if (folder.isEmpty()) "我的共享文件夹" else "/$folder"
        files.removeAllViews()
        if (entries.isEmpty()) {
            files.addView(label("这里还没有文件\n从手机上传，或在电脑共享文件夹中放入文件。", 15f).apply {
                gravity = Gravity.CENTER; setPadding(dp(20), dp(30), dp(20), dp(30))
            })
        }
        entries.forEach { entry ->
            val card = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                background = rounded(Color.WHITE)
                setPadding(dp(16), dp(6), dp(16), dp(6))
                addView(label((if (entry.directory) "▣  " else "↓  ") + entry.name, 16f, true))
                addView(label(if (entry.directory) "文件夹 · 点击打开" else "${formatSize(entry.size)} · 点击下载", 12f))
                isClickable = true; isFocusable = true
                setOnClickListener {
                    if (!busy) {
                        if (entry.directory) { folder = entry.path; refresh() }
                        else chooseDownload(entry)
                    }
                }
            }
            files.addView(card, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(10) })
        }
    }

    private fun importPairing() {
        val field = EditText(this).apply { hint = "粘贴电脑端复制的配对信息"; minLines = 3; maxLines = 6 }
        AlertDialog.Builder(this).setTitle("导入配对信息").setView(field)
            .setNegativeButton("取消", null).setPositiveButton("连接") { _, _ -> acceptPairing(field.text.toString()) }.show()
    }

    private fun acceptPairing(value: String) {
        val pairing = try { Pairing.parse(value) } catch (error: Exception) {
            status.text = error.message ?: "配对信息无效"; return
        }
        // Confirm the scanned destination before sending credentials or sharing files.
        AlertDialog.Builder(this).setTitle("连接这台电脑？")
            .setMessage("${pairing.url}\n请确认二维码来自你自己的电脑。")
            .setNegativeButton("取消", null).setPositiveButton("连接") { _, _ ->
                task("正在验证电脑…") {
                    val peer = PeerClient(pairing)
                    peer.info()
                    val entries = peer.list("")
                    store.save(pairing)
                    ui { client = peer; folder = ""; render(entries); status.text = "配对成功，之后打开 App 即可访问" }
                }
            }.show()
    }

    private fun chooseUpload() {
        if (connection() == null) return
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE); type = "*/*"
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
        }, 101)
    }

    private fun upload(uris: List<Uri>) {
        val peer = connection() ?: return
        task("正在准备上传…") {
            val target = folder
            var completed = 0
            try {
                uris.forEachIndexed { index, uri ->
                    val saved = peer.upload(contentResolver, uri, target, cacheDir) { done, total ->
                        transferProgress("上传 ${index + 1}/${uris.size}", done, total)
                    }
                    completed++
                    ui { status.text = "已上传：$saved" }
                }
                val entries = peer.list(target)
                ui { render(entries); status.text = "上传完成 · $completed 个文件" }
            } catch (error: Exception) {
                throw java.io.IOException("已完成 $completed/${uris.size} 个文件；${error.message}", error)
            }
        }
    }

    private fun chooseDownload(entry: RemoteEntry) {
        pendingDownload = entry
        startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE); type = "application/octet-stream"
            putExtra(Intent.EXTRA_TITLE, entry.name)
        }, 102)
    }

    private fun createFolder() {
        val peer = connection() ?: return
        val field = EditText(this).apply { hint = "文件夹名称"; setSingleLine() }
        AlertDialog.Builder(this).setTitle("新建文件夹").setView(field)
            .setNegativeButton("取消", null).setPositiveButton("创建") { _, _ ->
                val name = field.text.toString().trim()
                if (name.isEmpty() || name.contains('/') || name.contains('\\')) { status.text = "请输入有效名称"; return@setPositiveButton }
                task("正在创建文件夹…") {
                    peer.mkdir(if (folder.isEmpty()) name else "$folder/$name")
                    val entries = peer.list(folder)
                    ui { render(entries); status.text = "文件夹已创建" }
                }
            }.show()
    }

    private fun transferProgress(label: String, done: Long, total: Long) {
        val now = SystemClock.elapsedRealtime()
        if (now - lastProgress < 150 && done != total) return
        lastProgress = now
        ui {
            progress.isIndeterminate = total <= 0
            if (total > 0) progress.progress = (done.toDouble() / total * 100).toInt().coerceIn(0, 100)
            status.text = if (total >= 0) "$label · ${formatSize(done)} / ${formatSize(total)}"
                else "准备文件 · 已缓存 ${formatSize(done)}"
        }
    }

    private fun formatSize(bytes: Long): String = when {
        bytes >= 1024L * 1024 * 1024 -> "%.1f GiB".format(bytes.toDouble() / (1024L * 1024 * 1024))
        bytes >= 1024 * 1024 -> "%.1f MiB".format(bytes.toDouble() / (1024 * 1024))
        bytes >= 1024 -> "%.1f KiB".format(bytes.toDouble() / 1024)
        else -> "$bytes B"
    }

    private fun captureShares(intent: Intent?) {
        pendingShares = when (intent?.action) {
            Intent.ACTION_SEND -> listOfNotNull(intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))
            Intent.ACTION_SEND_MULTIPLE -> intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)?.toList() ?: emptyList()
            else -> emptyList()
        }.filter { it.scheme == "content" }
    }

    private fun offerShares() {
        val uris = pendingShares
        pendingShares = emptyList()
        AlertDialog.Builder(this).setTitle("上传分享过来的 ${uris.size} 个文件？")
            .setMessage("目标：/${folder}")
            .setNegativeButton("取消", null).setPositiveButton("上传") { _, _ -> upload(uris) }.show()
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        val scan = IntentIntegrator.parseActivityResult(requestCode, resultCode, data)
        if (scan != null) { scan.contents?.let { acceptPairing(it) }; return }
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != RESULT_OK || data == null) return
        if (requestCode == 101) {
            val clip = data.clipData
            upload(if (clip != null) (0 until clip.itemCount).map { clip.getItemAt(it).uri } else listOfNotNull(data.data))
        } else if (requestCode == 102) {
            val destination = data.data ?: return
            val entry = pendingDownload ?: return
            pendingDownload = null
            val peer = connection() ?: return
            task("正在下载 ${entry.name}…") {
                try {
                    peer.download(contentResolver, entry, destination) { done, total -> transferProgress("下载", done, total) }
                    ui { status.text = "已保存：${entry.name}" }
                } catch (error: Exception) {
                    val removed = try { DocumentsContract.deleteDocument(contentResolver, destination) } catch (_: Exception) { false }
                    throw java.io.IOException("${error.message}。" + if (removed) "已移除未完成文件。" else "保存位置可能有未完成文件，请删除后重试。", error)
                }
            }
        }
    }

    override fun onBackPressed() {
        if (busy) { status.text = "文件正在传输，请等待完成后退出"; return }
        if (folder.isNotEmpty()) { folder = folder.substringBeforeLast('/', ""); refresh() }
        else super.onBackPressed()
    }

    override fun onDestroy() {
        client?.cancel(); worker.shutdownNow()
        super.onDestroy()
    }
}
