"""Conservative, Windows-compatible paths and atomic, non-overwriting uploads."""

from contextlib import contextmanager
from pathlib import Path
import hashlib
import os
import re
import tempfile
import threading


class StorageError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def valid_name(name):
    return bool(
        name and name not in (".", "..") and not name.startswith(".")
        and not name.endswith((" ", "."))
        and len(name.encode("utf-8")) <= 220
        and not re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
        and not re.match(r"^(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])(?:\.|$)", name, re.I)
    )


class FileStore:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.commit_lock = threading.Lock()

    def path(self, relative="", *, exists=True):
        if not isinstance(relative, str) or len(relative) > 2048:
            raise StorageError("路径无效")
        if relative == "":
            return self.root
        parts = relative.split("/")
        if any(not valid_name(part) for part in parts):
            raise StorageError("路径包含不支持的名称")
        target = self.root
        for part in parts:
            target /= part
            if target.is_symlink() or (hasattr(target, "is_junction") and target.is_junction()):
                raise StorageError("不允许访问符号链接或目录联接", 403)
        if not target.resolve().is_relative_to(self.root):
            raise StorageError("路径超出共享目录", 403)
        if exists and not target.exists():
            raise StorageError("文件或目录不存在", 404)
        return target

    def list(self, relative=""):
        directory = self.path(relative)
        if not directory.is_dir():
            raise StorageError("这不是文件夹", 400)
        entries = []
        for item in directory.iterdir():
            try:
                if not valid_name(item.name):
                    continue
                safe = self.path(item.relative_to(self.root).as_posix())
                if not (safe.is_file() or safe.is_dir()):
                    continue
                stat = safe.stat()
                entries.append({
                    "name": item.name,
                    "path": item.relative_to(self.root).as_posix(),
                    "directory": safe.is_dir(),
                    "size": 0 if safe.is_dir() else stat.st_size,
                    "modified": int(stat.st_mtime),
                })
            except (StorageError, OSError):
                continue
        entries.sort(key=lambda entry: (not entry["directory"], entry["name"].casefold()))
        return entries

    def mkdir(self, relative):
        target = self.path(relative, exists=False)
        if target == self.root or not target.parent.is_dir():
            raise StorageError("父文件夹不存在", 400)
        try:
            target.mkdir()
        except FileExistsError:
            raise StorageError("同名文件或文件夹已存在", 409) from None

    @contextmanager
    def upload(self, relative):
        target = self.path(relative, exists=False)
        if target == self.root or not target.parent.is_dir():
            raise StorageError("请选择有效的目标文件夹")
        fd, name = tempfile.mkstemp(prefix=".pocketbridge-", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as output:
                yield output, temporary
        finally:
            temporary.unlink(missing_ok=True)

    def commit(self, temporary, relative):
        target = self.path(relative, exists=False)
        # Hard links create the destination atomically without overwriting. If the
        # filesystem does not support them, fail safely instead of truncating files.
        with self.commit_lock:
            for number in range(10000):
                if number == 0:
                    candidate = target
                else:
                    stem, suffix = target.stem[:60], target.suffix[:30]
                    name = f"{stem} ({number}){suffix}"
                    while len(name.encode("utf-8")) > 220:
                        stem = stem[:-1]
                        name = f"{stem} ({number}){suffix}"
                    candidate = target.with_name(name)
                try:
                    os.link(temporary, candidate)
                    return candidate.relative_to(self.root).as_posix()
                except FileExistsError:
                    continue
            raise StorageError("同名文件过多，请重命名后重试", 409)

    def receive(self, stream, relative, length, expected_digest=None):
        digest = hashlib.sha256()
        with self.upload(relative) as (output, temporary):
            remaining = length
            while remaining:
                chunk = stream.read(min(256 * 1024, remaining))
                if not chunk:
                    raise StorageError("传输中断，未保存不完整文件")
                output.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            if expected_digest and digest.hexdigest() != expected_digest:
                raise StorageError("文件校验失败，未保存文件")
            output.flush()
            os.fsync(output.fileno())
            # Windows requires the writer to close before finalization.
            output.close()
            saved = self.commit(temporary, relative)
        return {"path": saved, "size": length, "sha256": digest.hexdigest()}
