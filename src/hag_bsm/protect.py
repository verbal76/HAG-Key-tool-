"""Protection of locally stored credentials.

On Windows this uses DPAPI (CryptProtectData), which ties the data to the signed-in Windows
user. Elsewhere (development and CI only) it falls back to AES-256-GCM with a random key kept
in a private file next to the vault; that fallback is clearly weaker and is reported as such.
"""

import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .fsutil import ensure_private_dir, write_new_file

_ENTROPY = b"HotAtticGames.BuildSigningManager.v1"
_MAGIC_DPAPI = b"HAGP1D"
_MAGIC_FILEKEY = b"HAGP1F"


class ProtectionError(Exception):
    pass


def scheme_name() -> str:
    return "Windows DPAPI (current user)" if sys.platform == "win32" else "Local key file (development fallback)"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def _blob(data: bytes):
        buf = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _dpapi(encrypt: bool, data: bytes) -> bytes:
        inp, _keep1 = _blob(data)
        ent, _keep2 = _blob(_ENTROPY)
        out = _Blob()
        if encrypt:
            ok = _crypt32.CryptProtectData(
                ctypes.byref(inp), ctypes.c_wchar_p("Build & Signing Manager credential"),
                ctypes.byref(ent), None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
        else:
            ok = _crypt32.CryptUnprotectData(
                ctypes.byref(inp), None, ctypes.byref(ent), None, None,
                _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
        if not ok:
            raise ProtectionError(f"Windows DPAPI failed (error {ctypes.get_last_error()}).")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(out.pbData)


class Protector:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    # -- fallback key handling --
    def _file_key(self) -> bytes:
        key_path = self.vault_root / "vault.key"
        if not key_path.exists():
            ensure_private_dir(self.vault_root)
            try:
                write_new_file(key_path, AESGCM.generate_key(256))
                os.chmod(key_path, 0o600)
            except FileExistsError:
                pass
        key = key_path.read_bytes()
        if len(key) != 32:
            raise ProtectionError("The local vault key file is damaged.")
        return key

    def protect(self, data: bytes) -> bytes:
        if sys.platform == "win32":
            return _MAGIC_DPAPI + _dpapi(True, data)
        nonce = os.urandom(12)
        return _MAGIC_FILEKEY + nonce + AESGCM(self._file_key()).encrypt(nonce, data, _ENTROPY)

    def unprotect(self, blob: bytes) -> bytes:
        if blob.startswith(_MAGIC_DPAPI):
            if sys.platform != "win32":
                raise ProtectionError("These credentials were protected with Windows DPAPI and can only be "
                                      "opened by the same Windows user. Restore from an encrypted backup instead.")
            return _dpapi(False, blob[len(_MAGIC_DPAPI):])
        if blob.startswith(_MAGIC_FILEKEY):
            body = blob[len(_MAGIC_FILEKEY):]
            try:
                return AESGCM(self._file_key()).decrypt(body[:12], body[12:], _ENTROPY)
            except Exception as exc:
                raise ProtectionError("The stored credentials could not be decrypted.") from exc
        raise ProtectionError("The stored credentials are in an unknown format.")
