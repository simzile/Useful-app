from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import ipaddress
import json
import os
import secrets
import ssl
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def default_state_dir():
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
    return base / "PocketBridge"


def tailscale_ip():
    commands = ["tailscale", r"C:\Program Files\Tailscale\tailscale.exe"]
    for command in commands:
        try:
            result = subprocess.run(
                [command, "ip", "-4"], capture_output=True, text=True, timeout=4,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            value = result.stdout.strip().splitlines()[0]
            if result.returncode == 0 and ipaddress.ip_address(value).version == 4:
                return value
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
            pass
    return "127.0.0.1"


class Config:
    def __init__(self, directory=None):
        self.directory = Path(directory or default_state_dir()).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file = self.directory / "config.json"
        if self.file.exists():
            self.data = json.loads(self.file.read_text(encoding="utf-8"))
        else:
            self.data = {
                "root": str(Path.home() / "PocketBridgeFiles"),
                "host": tailscale_ip(), "port": 8765,
                "token": secrets.token_urlsafe(32),
            }
            self.save()
        self.cert = self.directory / "certificate.pem"
        self.key = self.directory / "private-key.pem"
        if not self.cert.exists() or not self.key.exists():
            self.create_certificate()

    def save(self):
        temporary = self.file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(self.file)

    def create_certificate(self):
        key = ec.generate_private_key(ec.SECP256R1())
        now = datetime.now(timezone.utc)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PocketBridge")])
        certificate = (
            x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("pocketbridge.local")]), critical=False)
            .sign(key, hashes.SHA256())
        )
        self.key.write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        self.key.chmod(0o600)
        self.cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))

    def tls_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.cert, self.key)
        return context

    def pairing(self):
        der = x509.load_pem_x509_certificate(self.cert.read_bytes()).public_bytes(serialization.Encoding.DER)
        return json.dumps({
            "version": 1,
            "url": f'https://{self.data["host"]}:{self.data["port"]}',
            "token": self.data["token"],
            "fingerprint": hashlib.sha256(der).hexdigest(),
        }, separators=(",", ":"))

