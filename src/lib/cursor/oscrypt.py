from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # pragma: no cover
    AESGCM = None

OPENAI_KEY_DB_KEY = "secret://cursorAuth/openAIKey"

try:
    import win32crypt  # type: ignore[import-not-found]
except ImportError:
    win32crypt = None


def local_state_path() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "Cursor" / "Local State"
    if sys.platform == "darwin":
        return (
            Path.home() / "Library" / "Application Support" / "Cursor" / "Local State"
        )
    return Path.home() / ".config" / "Cursor" / "Local State"


def _dpapi_unprotect(data: bytes) -> bytes | None:
    if sys.platform != "win32":
        return None
    if win32crypt is not None:
        try:
            return win32crypt.CryptUnprotectData(data, None, None, None, 0)[1]
        except Exception:
            return None

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    inblob = DATA_BLOB(
        len(data),
        ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)),
    )
    outblob = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(inblob), None, None, None, None, 0, ctypes.byref(outblob)
    ):
        return None
    try:
        return ctypes.string_at(outblob.pbData, outblob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outblob.pbData)


def password_to_aes_key(password: str) -> bytes | None:
    """Convert a Keychain/keyring secret to the 32-byte AES-GCM key.

    Electron stores the raw AES key in the system secret store as base64.
    """
    try:
        raw = base64.b64decode(password.strip(), validate=True)
    except (ValueError, TypeError):
        return None
    if len(raw) == 32:
        return raw
    return None


def _run_secret_tool(args: list[str], timeout: float = 10.0) -> str | None:
    import subprocess

    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _macos_keychain_key() -> bytes | None:
    """Read the Electron safeStorage key from the macOS login Keychain."""
    # Electron stores the key as a generic password whose service name is the
    # app name (or bundle id) plus "Safe Storage"; try the known variants.
    candidates = [
        ("Cursor Safe Storage", None),
        ("Electron Safe Storage", None),
        ("com.todesktop.230313mzl4w4u92 Safe Storage", None),
        ("com.todesktop.230313mzl4w4u92", "Cursor Safe Storage"),
        ("com.todesktop.230313mzl4w4u92", "Electron Safe Storage"),
    ]
    for service, account in candidates:
        args = ["security", "find-generic-password"]
        if service:
            args += ["-s", service]
        if account:
            args += ["-a", account]
        args.append("-w")
        value = _run_secret_tool(args)
        if value is None:
            continue
        key = password_to_aes_key(value)
        if key is not None:
            return key
    return None


def _linux_keyring_key() -> bytes | None:
    """Read the Electron safeStorage key from the Linux Secret Service."""
    candidates = [
        ["secret-tool", "lookup", "service", "Cursor Safe Storage"],
        ["secret-tool", "lookup", "service", "Electron Safe Storage"],
        ["secret-tool", "lookup", "application", "Cursor"],
    ]
    for args in candidates:
        value = _run_secret_tool(args)
        if value is None:
            continue
        key = password_to_aes_key(value)
        if key is not None:
            return key
    return None


def load_oscrypt_key() -> bytes | None:
    """Return the 32-byte AES key Cursor uses for its secret:// values.

    Windows stores it DPAPI-wrapped in Local State; macOS keeps it in the
    login Keychain; Linux in the Secret Service keyring. Local State is tried
    first everywhere, then the platform secret store.
    """
    path = local_state_path()
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            encrypted_key = state.get("os_crypt", {}).get("encrypted_key")
            if isinstance(encrypted_key, str) and encrypted_key:
                raw = base64.b64decode(encrypted_key)
                if raw.startswith(b"DPAPI"):
                    unwrapped = _dpapi_unprotect(raw[len(b"DPAPI") :])
                else:
                    unwrapped = raw
                if unwrapped is not None and len(unwrapped) == 32:
                    return unwrapped
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    if sys.platform == "darwin":
        return _macos_keychain_key()
    if sys.platform == "linux":
        return _linux_keyring_key()
    return None


def decrypt_secret_buffer(value: str, key: bytes | None = None) -> str | None:
    """Decrypt a Cursor secret:// value stored as a JSON Buffer blob."""
    if AESGCM is None:
        return None
    try:
        payload = json.loads(value)
        data = payload.get("data")
        if not isinstance(data, list):
            return None
        blob = bytes(int(b) for b in data)
        if not blob.startswith(b"v10"):
            return None
        aes_key = key or load_oscrypt_key()
        if aes_key is None:
            return None
        ciphertext = blob[len(b"v10") :]
        nonce, tagged = ciphertext[:12], ciphertext[12:]
        return AESGCM(aes_key).decrypt(nonce, tagged, None).decode("utf-8")
    except Exception:
        return None


def encrypt_secret_plaintext(plaintext: str, key: bytes | None = None) -> str | None:
    """Encrypt a plaintext value into a Cursor secret:// JSON Buffer blob."""
    if AESGCM is None:
        return None
    try:
        aes_key = key or load_oscrypt_key()
        if aes_key is None:
            return None
        nonce = os.urandom(12)
        tagged = AESGCM(aes_key).encrypt(nonce, plaintext.encode("utf-8"), None)
        blob = b"v10" + nonce + tagged
        return json.dumps({"type": "Buffer", "data": list(blob)})
    except Exception:
        return None


def is_oscrypt_available() -> bool:
    return AESGCM is not None and load_oscrypt_key() is not None


def api_key_status(value: str | None) -> str:
    if not value:
        return "no api key saved"
    if decrypt_secret_buffer(value) is not None:
        return "set (encrypted)"
    return "set (opaque)"
