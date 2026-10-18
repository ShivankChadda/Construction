"""Ed25519 signature over the approved slip's exact contents.

What this gives you: the PDF carries a verification code and a QR link. The
server re-checks the signature against its own record, so a slip whose
quantities, rates or vendors were edited after approval shows as INVALID.

What it is not: a Class-3 DSC under the IT Act. For internal purchase control
and vendor hand-off this is the right tool; for statutory filings use a DSC.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

log = logging.getLogger(__name__)


def generate_seed_b64() -> str:
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(raw).decode()


class Signer:
    def __init__(self, seed_b64: str):
        self._key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(seed_b64))
        self._pub = self._key.public_key()

    @classmethod
    def from_settings(cls, seed_b64: str, key_path: str) -> "Signer":
        if seed_b64:
            return cls(seed_b64)
        path = Path(key_path)
        if path.exists():
            return cls(path.read_text().strip())
        log.warning("SIGNING_KEY not set; generating a new key at %s. Back this file up.", path)
        path.parent.mkdir(parents=True, exist_ok=True)
        seed = generate_seed_b64()
        path.write_text(seed)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return cls(seed)

    @property
    def public_key_b64(self) -> str:
        raw = self._pub.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        return base64.b64encode(raw).decode()

    def sign(self, payload: bytes) -> str:
        return base64.urlsafe_b64encode(self._key.sign(payload)).decode().rstrip("=")

    def verify(self, payload: bytes, signature: str) -> bool:
        try:
            sig = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
            self._pub.verify(sig, payload)
            return True
        except (InvalidSignature, ValueError):
            return False


def canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def verify_code(signature: str) -> str:
    """Short human-checkable code derived from the signature: 7K2M-9QXA-P4TR."""
    digest = hashlib.sha256(signature.encode()).digest()
    code = base64.b32encode(digest).decode()[:12]
    return f"{code[:4]}-{code[4:8]}-{code[8:12]}"
