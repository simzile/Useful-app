"""A small authenticated HTTPS API intended for trusted private networks."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import hmac
import json
import logging
import re
import socket
import ssl
import threading

from .storage import FileStore, StorageError

LOG = logging.getLogger(__name__)
MAX_UPLOAD = 100 * 1024**3


class FolderServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, address, store, token, tls=None, on_event=None):
        self.store = store
        self.token = token
        self.tls = tls
        self.on_event = on_event or (lambda message: None)
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        connection = request
        try:
            connection.settimeout(60)
            if self.tls:
                connection = self.tls.wrap_socket(connection, server_side=True)
            self.finish_request(connection, client_address)
        except (OSError, ssl.SSLError):
            pass
        except Exception:
            LOG.exception("Request failed")
        finally:
            self.shutdown_request(connection)
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PocketBridge/0.1"
    sys_version = ""

    def log_message(self, format, *args):
        # Do not record credentials, URL query strings or private filenames.
        pass

    def response(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.response_started = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def route(self):
        self.close_connection = True
        self.response_started = False
        try:
            if len(self.headers.get_all("Authorization", [])) != 1:
                raise StorageError("请先与电脑配对", 401)
            authorization = self.headers.get("Authorization", "")
            if not hmac.compare_digest(authorization.encode(), ("Bearer " + self.server.token).encode()):
                raise StorageError("配对凭据无效，请重新扫描二维码", 401)
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=8)
            relative = query.get("path", [""])[0]
            if self.command == "GET" and parsed.path == "/v1/info":
                self.response(200, {"name": "PocketBridge", "version": 1, "folder": self.server.store.root.name})
            elif self.command == "GET" and parsed.path == "/v1/files":
                self.response(200, {"path": relative, "entries": self.server.store.list(relative)})
            elif self.command == "GET" and parsed.path == "/v1/file":
                self.download(relative)
            elif self.command == "PUT" and parsed.path == "/v1/file":
                if self.headers.get("Transfer-Encoding"):
                    raise StorageError("需要固定文件长度", 411)
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,12}", lengths[0]):
                    raise StorageError("缺少有效的文件长度", 411)
                length = int(lengths[0])
                if length > MAX_UPLOAD:
                    raise StorageError("单文件最大 100 GiB", 413)
                expected = self.headers.get("X-Content-SHA256")
                if expected is not None and not re.fullmatch(r"[0-9a-f]{64}", expected):
                    raise StorageError("校验值格式错误")
                saved = self.server.store.receive(self.rfile, relative, length, expected)
                self.server.on_event(f'已接收：{saved["path"]}')
                self.response(201, saved)
            elif self.command == "POST" and parsed.path == "/v1/folder":
                self.server.store.mkdir(relative)
                self.response(201, {"path": relative})
            else:
                raise StorageError("接口不存在", 404)
        except StorageError as error:
            self.fail(error.status, str(error))
        except (ValueError, UnicodeError):
            self.fail(400, "请求格式错误")
        except (socket.timeout, TimeoutError):
            self.fail(408, "传输超时，请重试")
        except OSError:
            self.fail(500, "读写失败，请检查目录权限、磁盘空间及 NTFS 文件系统")

    def fail(self, status, message):
        # A failed streamed download must end early, never append a second HTTP
        # response to the bytes of the file that the client is saving.
        if not self.response_started:
            self.response(status, {"error": message})
        self.close_connection = True

    def download(self, relative):
        path = self.server.store.path(relative)
        if not path.is_file():
            raise StorageError("请选择一个文件")
        with path.open("rb") as source:
            import os
            size = os.fstat(source.fileno()).st_size
            self.response_started = True
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            remaining = size
            while remaining:
                data = source.read(min(256 * 1024, remaining))
                if not data:
                    # Closing early makes the client detect Content-Length mismatch.
                    break
                self.wfile.write(data)
                remaining -= len(data)

    do_GET = route
    do_PUT = route
    do_POST = route


def start_server(config, on_event=None):
    root = config.data["root"]
    store = FileStore(root)
    if config.directory.is_relative_to(store.root):
        raise ValueError("共享目录不能包含程序配置目录，请选择专用文件夹")
    server = FolderServer(
        (config.data["host"], int(config.data["port"])), store,
        config.data["token"], config.tls_context(), on_event,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
