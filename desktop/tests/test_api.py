import hashlib
import http.client
import json
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from urllib.parse import urlencode

from pocketbridge.config import Config
from pocketbridge.server import FolderServer, MAX_UPLOAD, start_server
from pocketbridge.storage import FileStore


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary.name)
        cls.config = Config(cls.directory / "state")
        cls.context = ssl.create_default_context(cafile=str(cls.config.cert))
        # This test trusts this exact generated certificate; the Android client
        # verifies the SHA-256 pin instead of conventional hostname identity.
        cls.context.check_hostname = False
        cls.store = FileStore(cls.directory / "files")
        cls.server = FolderServer(("127.0.0.1", 0), cls.store, "test-token", cls.config.tls_context())
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temporary.cleanup()

    def request(self, method, endpoint, body=None, headers=None, token="test-token"):
        connection = http.client.HTTPSConnection("127.0.0.1", self.port, context=self.context, timeout=5)
        merged = {} if token is None else {"Authorization": "Bearer " + token}
        merged.update(headers or {})
        try:
            connection.request(method, endpoint, body=body, headers=merged)
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_authentication_required_everywhere(self):
        for endpoint in ("/v1/info", "/v1/files", "/v1/file?path=unknown"):
            self.assertEqual(self.request("GET", endpoint, token=None)[0], 401)
            self.assertEqual(self.request("GET", endpoint, token="wrong")[0], 401)
        self.assertEqual(self.request("PUT", "/v1/file?path=unauthorized.txt", b"x", token=None)[0], 401)
        self.assertFalse((self.store.root / "unauthorized.txt").exists())

    def test_https_unicode_upload_list_download_roundtrip(self):
        path = "测试 file.bin"
        endpoint = "/v1/file?" + urlencode({"path": path})
        body = bytes(range(256)) * 8192
        digest = hashlib.sha256(body).hexdigest()
        status, payload, _ = self.request("PUT", endpoint, body, {"X-Content-SHA256": digest})
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(payload)["sha256"], digest)
        status, received, headers = self.request("GET", endpoint)
        self.assertEqual(status, 200)
        self.assertEqual(received, body)
        self.assertEqual(headers["Content-Length"], str(len(body)))
        self.assertEqual(headers["Cache-Control"], "no-store")
        listing = json.loads(self.request("GET", "/v1/files")[1])
        self.assertIn(path, [entry["name"] for entry in listing["entries"]])

    def test_folder_creation_and_conflict(self):
        self.assertEqual(self.request("POST", "/v1/folder?path=new-folder", b"")[0], 201)
        self.assertEqual(self.request("POST", "/v1/folder?path=new-folder", b"")[0], 409)
        self.assertEqual(json.loads(self.request("GET", "/v1/files?path=new-folder")[1])["entries"], [])

    def test_api_rejects_path_escape(self):
        for path in ("../state/private-key.pem", "/etc/passwd", "x:secret", "CON.txt"):
            endpoint = "/v1/file?" + urlencode({"path": path})
            self.assertEqual(self.request("GET", endpoint)[0], 400)
            self.assertEqual(self.request("PUT", endpoint, b"x")[0], 400)

    def test_missing_file_and_directory_download(self):
        self.assertEqual(self.request("GET", "/v1/file?path=nonexistent")[0], 404)
        self.assertEqual(self.request("GET", "/v1/file?path=")[0], 400)

    def test_limits_and_unsupported_transfer_encoding(self):
        self.assertEqual(self.request("PUT", "/v1/file?path=large", b"", {"Content-Length": str(MAX_UPLOAD + 1)})[0], 413)
        self.assertEqual(self.request("PUT", "/v1/file?path=chunk", b"", {"Transfer-Encoding": "chunked"})[0], 411)
        self.assertEqual(self.request("PUT", "/v1/file?path=negative", b"", {"Content-Length": "-1"})[0], 411)

    def test_revocation_takes_effect(self):
        try:
            self.server.token = "rotated-token"
            self.assertEqual(self.request("GET", "/v1/info")[0], 401)
            self.assertEqual(self.request("GET", "/v1/info", token="rotated-token")[0], 200)
        finally:
            self.server.token = "test-token"

    def test_certificates_and_pairing_persist(self):
        before = self.config.pairing()
        reloaded = Config(self.directory / "state")
        self.assertEqual(before, reloaded.pairing())
        pairing = json.loads(before)
        der = ssl.PEM_cert_to_DER_cert(self.config.cert.read_text())
        self.assertEqual(pairing["fingerprint"], hashlib.sha256(der).hexdigest())
        self.assertNotIn(str(self.directory), before)

    def test_untrusted_certificate_fails(self):
        connection = http.client.HTTPSConnection("127.0.0.1", self.port, context=ssl.create_default_context(), timeout=5)
        try:
            with self.assertRaises(ssl.SSLCertVerificationError):
                connection.request("GET", "/v1/info")
        finally:
            connection.close()

    def test_shared_folder_cannot_expose_credentials(self):
        config = Config(self.directory / "nested-state")
        config.data.update(root=str(self.directory), host="127.0.0.1", port=0)
        with self.assertRaises(ValueError):
            start_server(config)


if __name__ == "__main__":
    unittest.main()
