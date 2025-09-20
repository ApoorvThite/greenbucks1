from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from typing import Optional

from .config import get_settings


def _get_fernet() -> Optional[Fernet]:
    key = get_settings().encryption_key
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None


def encrypt_to_bytes(plaintext: str) -> bytes:
    f = _get_fernet()
    if not f:
        raise RuntimeError("Encryption key not configured. Set ENCRYPTION_KEY in .env")
    return f.encrypt(plaintext.encode())


def decrypt_to_str(token: bytes) -> str:
    f = _get_fernet()
    if not f:
        raise RuntimeError("Encryption key not configured. Set ENCRYPTION_KEY in .env")
    try:
        return f.decrypt(token).decode()
    except InvalidToken as e:
        raise RuntimeError("Failed to decrypt secret; invalid key or data") from e
