"""Windows tray application; configuration stays in the user's local AppData."""

from pathlib import Path
import ipaddress
import os
import queue
import secrets
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .config import tailscale_ip
from .server import start_server


class DesktopApp:
    def __init__(self, config, background=False):
        self.config = config
        self.server = None
        self.tray = None
        self.events = queue.Queue()
        self.window = tk.Tk()
        self.window.title("口袋桥 · PocketBridge")
        self.window.geometry("740x570")
        self.window.minsize(640, 520)
        self.window.configure(background="#f3f6fb")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f3f6fb")
        style.configure("TLabel", background="#f3f6fb", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", padding=(12, 8), font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 23, "bold"), foreground="#152846")
        frame = ttk.Frame(self.window, padding=28)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="文件在电脑，随时从手机取用", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text="口袋桥  /  你的个人共享文件夹", foreground="#56708f").pack(anchor="w", pady=(8, 24))
        ttk.Label(frame, text="共享文件夹").pack(anchor="w")
        folder_row = ttk.Frame(frame)
        folder_row.pack(fill="x", pady=(6, 16))
        self.folder = tk.StringVar(value=config.data["root"])
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder)
        self.folder_entry.pack(side="left", fill="x", expand=True, ipady=8)
        self.choose = ttk.Button(folder_row, text="选择文件夹", command=self.choose_folder)
        self.choose.pack(side="left", padx=(10, 0))
        ttk.Label(frame, text="电脑的 Tailscale IPv4 地址（同一局域网也可填本机局域网地址）").pack(anchor="w")
        address_row = ttk.Frame(frame)
        address_row.pack(fill="x", pady=(6, 10))
        self.host = tk.StringVar(value=config.data["host"])
        self.host_entry = ttk.Entry(address_row, textvariable=self.host)
        self.host_entry.pack(side="left", fill="x", expand=True, ipady=8)
        self.detect = ttk.Button(address_row, text="检测 Tailscale", command=self.detect_ip)
        self.detect.pack(side="left", padx=(10, 0))
        ttk.Label(frame, text="手机和电脑先连接 Tailscale；电脑保持开机，默认使用端口 8765。", foreground="#56708f").pack(anchor="w", pady=(0, 18))
        actions = ttk.Frame(frame)
        actions.pack(fill="x")
        self.toggle_button = ttk.Button(actions, text="开启共享", command=self.toggle)
        self.toggle_button.pack(side="left")
        ttk.Button(actions, text="手机扫码配对", command=self.pair).pack(side="left", padx=8)
        ttk.Button(actions, text="打开文件夹", command=self.open_folder).pack(side="left")
        settings = ttk.Frame(frame)
        settings.pack(fill="x", pady=(12, 0))
        self.autostart = tk.BooleanVar(value=self.startup_enabled())
        ttk.Checkbutton(settings, text="Windows 登录后自动运行", variable=self.autostart, command=self.set_startup).pack(side="left")
        ttk.Button(settings, text="撤销手机配对", command=self.revoke).pack(side="right")
        self.status = tk.StringVar(value="尚未开启共享")
        ttk.Label(frame, textvariable=self.status, foreground="#166a59", wraplength=650).pack(anchor="w", pady=(22, 6))
        self.latest = tk.StringVar(value="配对一次后，手机上传无需在电脑确认。")
        ttk.Label(frame, textvariable=self.latest, foreground="#56708f", wraplength=650).pack(anchor="w")
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        self.setup_tray()
        self.window.after(200, self.poll)
        # --background is used only by the opt-in Windows login startup entry.
        if background:
            self.window.after(400, self.start_background)

    def choose_folder(self):
        selected = filedialog.askdirectory(title="选择用于手机共享的文件夹")
        if selected:
            self.folder.set(selected)

    def detect_ip(self):
        address = tailscale_ip()
        self.host.set(address)
        if address == "127.0.0.1":
            messagebox.showinfo("未检测到 Tailscale", "请先安装、登录并连接 Tailscale，再点击检测。也可以手动填写本机局域网 IPv4 地址。")

    def toggle(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
            self.status.set("共享已停止接受新连接")
        else:
            try:
                address = ipaddress.ip_address(self.host.get().strip())
                if address.version != 4 or address.is_unspecified or address.is_multicast:
                    raise ValueError("请填写本机具体的 IPv4 地址")
                if address.is_loopback:
                    raise ValueError("127.0.0.1 只能本机访问，请先连接 Tailscale 并检测地址")
                if not self.folder.get().strip():
                    raise ValueError("请选择共享文件夹")
                self.config.data.update(root=str(Path(self.folder.get()).expanduser().resolve()), host=str(address))
                self.server = start_server(self.config, self.events.put)
                self.config.save()
                self.status.set(f"正在共享 · {address}:{self.config.data['port']} · 关闭窗口后仍在托盘运行")
            except Exception as error:
                if self.server:
                    self.server.shutdown()
                    self.server.server_close()
                    self.server = None
                messagebox.showerror("无法开启共享", str(error))
        running = self.server is not None
        self.toggle_button.configure(text="停止共享" if running else "开启共享")
        for widget in (self.folder_entry, self.host_entry, self.choose, self.detect):
            widget.configure(state="disabled" if running else "normal")

    def start_background(self):
        self.toggle()
        if self.server and self.tray:
            self.window.withdraw()

    def pair(self):
        if not self.server:
            messagebox.showinfo("先开启共享", "先选择文件夹并开启共享，再让手机扫码。")
            return
        import qrcode
        from PIL import ImageTk
        dialog = tk.Toplevel(self.window)
        dialog.title("手机配对 · 二维码包含访问凭据，请勿公开")
        ttk.Label(dialog, text="Android 端点击「扫码连接电脑」", font=("Microsoft YaHei UI", 13)).pack(padx=24, pady=(20, 12))
        code = self.config.pairing()
        qr = qrcode.QRCode(box_size=5, border=4)
        qr.add_data(code)
        qr.make(fit=True)
        bitmap = ImageTk.PhotoImage(qr.make_image().convert("RGB"))
        label = ttk.Label(dialog, image=bitmap)
        label.image = bitmap
        label.pack(padx=24)
        ttk.Label(dialog, text="扫描一次即可。无法扫描时，可复制配对信息手动导入。").pack(pady=12)
        def copy():
            self.window.clipboard_clear()
            self.window.clipboard_append(code)
        ttk.Button(dialog, text="复制配对信息", command=copy).pack(pady=(0, 20))

    def revoke(self):
        if not messagebox.askyesno("撤销配对", "旧手机将无法发起新的访问；正在传输的文件可能继续完成。确定撤销所有手机的配对？"):
            return
        self.config.data["token"] = secrets.token_urlsafe(32)
        self.config.save()
        if self.server:
            self.server.token = self.config.data["token"]
        self.latest.set("旧配对已撤销。请用手机扫描新二维码。")

    def open_folder(self):
        if os.name == "nt":
            path = Path(self.folder.get()).resolve()
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(path)
        else:
            messagebox.showinfo("共享目录", self.folder.get())

    def startup_enabled(self):
        if os.name != "nt":
            return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                winreg.QueryValueEx(key, "PocketBridge")
            return True
        except OSError:
            return False

    def set_startup(self):
        if os.name != "nt" or not getattr(sys, "frozen", False):
            self.autostart.set(False)
            messagebox.showinfo("使用 Windows EXE", "此选项适用于打包后的 Windows 程序。下载构建生成的 EXE 后即可启用。")
            return
        import winreg
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                if self.autostart.get():
                    winreg.SetValueEx(key, "PocketBridge", 0, winreg.REG_SZ, f'"{sys.executable}" --background')
                else:
                    try:
                        winreg.DeleteValue(key, "PocketBridge")
                    except FileNotFoundError:
                        pass
        except OSError as error:
            self.autostart.set(self.startup_enabled())
            messagebox.showerror("设置失败", str(error))

    def setup_tray(self):
        if os.name != "nt":
            return
        import pystray
        from PIL import Image, ImageDraw
        bitmap = Image.new("RGB", (64, 64), "#1954df")
        draw = ImageDraw.Draw(bitmap)
        draw.rounded_rectangle((12, 17, 52, 48), radius=5, fill="white")
        draw.rectangle((16, 12, 33, 22), fill="white")
        draw.line((25, 34, 40, 34), fill="#1954df", width=5)
        self.tray = pystray.Icon("PocketBridge", bitmap, "口袋桥 · PocketBridge", pystray.Menu(
            pystray.MenuItem("打开口袋桥", lambda icon, item: self.events.put("__show__"), default=True),
            pystray.MenuItem("退出", lambda icon, item: self.events.put("__exit__")),
        ))
        self.tray.run_detached()

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event == "__show__":
                    self.window.deiconify()
                    self.window.lift()
                elif event == "__exit__":
                    self.quit()
                    return
                else:
                    self.latest.set(event)
        except queue.Empty:
            pass
        self.window.after(200, self.poll)

    def hide(self):
        if self.tray:
            self.window.withdraw()
        else:
            self.quit()

    def quit(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.tray:
            self.tray.stop()
        self.window.destroy()

    def run(self):
        self.window.mainloop()

