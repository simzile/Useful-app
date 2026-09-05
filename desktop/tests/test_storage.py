import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from pocketbridge.storage import FileStore, StorageError


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = FileStore(Path(self.temporary.name) / "shared")

    def tearDown(self):
        self.temporary.cleanup()

    def test_unicode_names_and_nested_folders(self):
        self.store.mkdir("论文资料")
        data = "你好，文件夹".encode()
        saved = self.store.receive(io.BytesIO(data), "论文资料/实验数据.txt", len(data))
        self.assertEqual(saved["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(self.store.path(saved["path"]).read_bytes(), data)
        self.assertEqual(self.store.list("论文资料")[0]["name"], "实验数据.txt")

    def test_zero_byte_file(self):
        saved = self.store.receive(io.BytesIO(b""), "empty.txt", 0)
        self.assertEqual(self.store.path(saved["path"]).stat().st_size, 0)

    def test_long_unicode_collision_stays_visible(self):
        name = "文" * 60 + "." + "件" * 13
        self.store.receive(io.BytesIO(b"a"), name, 1)
        saved = self.store.receive(io.BytesIO(b"b"), name, 1)
        self.assertIn(saved["path"], [entry["path"] for entry in self.store.list()])

    def test_existing_file_is_preserved(self):
        self.store.path("photo.jpg", exists=False).write_bytes(b"original")
        saved = self.store.receive(io.BytesIO(b"new"), "photo.jpg", 3)
        self.assertEqual(saved["path"], "photo (1).jpg")
        self.assertEqual(self.store.path("photo.jpg").read_bytes(), b"original")

    def test_concurrent_uploads_never_overwrite(self):
        def send(number):
            body = str(number).encode()
            return self.store.receive(io.BytesIO(body), "same.txt", len(body))["path"]
        with ThreadPoolExecutor(max_workers=6) as pool:
            paths = list(pool.map(send, range(12)))
        self.assertEqual(len(set(paths)), 12)
        self.assertEqual({self.store.path(path).read_text() for path in paths}, {str(i) for i in range(12)})

    def test_partial_upload_is_removed(self):
        with self.assertRaises(StorageError):
            self.store.receive(io.BytesIO(b"partial"), "result.txt", 100)
        self.assertEqual(list(self.store.root.iterdir()), [])

    def test_wrong_digest_is_removed(self):
        with self.assertRaises(StorageError):
            self.store.receive(io.BytesIO(b"abc"), "result.txt", 3, "0" * 64)
        self.assertEqual(list(self.store.root.iterdir()), [])

    def test_traversal_absolute_windows_and_reserved_paths_rejected(self):
        for path in ("../secret", "/etc/passwd", "C:/Windows", "a/../../secret", "a\\b", "x:stream",
                     "CON", "con.txt", "LPT1.txt", "aux", "abc.", "abc ", "a//b", "a/./b", ".private", "x\x00z"):
            with self.subTest(path=path), self.assertRaises(StorageError):
                self.store.path(path, exists=False)

    def test_symlinks_not_listed_or_traversed(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("private")
        try:
            (self.store.root / "link").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks requires Windows developer mode or privilege")
        self.assertEqual(self.store.list(), [])
        with self.assertRaises(StorageError):
            self.store.path("link/secret.txt")
        with self.assertRaises(StorageError):
            self.store.receive(io.BytesIO(b"x"), "link/injected", 1)

    def test_missing_parent_and_folder_conflict(self):
        with self.assertRaises(StorageError):
            self.store.receive(io.BytesIO(b"x"), "absent/file", 1)
        self.store.mkdir("folder")
        with self.assertRaises(StorageError):
            self.store.mkdir("folder")

    def test_hidden_files_stay_out_of_listing(self):
        (self.store.root / ".pocketbridge-incomplete").write_text("partial")
        self.assertEqual(self.store.list(), [])


if __name__ == "__main__":
    unittest.main()
