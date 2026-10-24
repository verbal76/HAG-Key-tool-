"""Encrypted signing-identity backups.

File layout (documented in docs/SECURITY.md; tools/decrypt_backup.py decrypts it without the app):

    line 1   b"HAGBSM-BACKUP 1\\n"
    line 2   JSON header (UTF-8), followed by b"\\n"
    rest     AES-256-GCM ciphertext of a ZIP archive

The key is derived from the user's passphrase with scrypt. The magic line and header are
authenticated as associated data, so tampering with any part of the file is detected.
The ZIP contains the keystore, its passwords, its public metadata and recovery instructions.
"""

import base64
import hashlib
import io
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import __version__, android
from .fsutil import write_new_file
from .model import now_iso
from .redact import register_secret
from .vault import Credentials, IdentityRecord, IdentityVault

MAGIC = b"HAGBSM-BACKUP 1\n"
MIN_PASSPHRASE = 12
DEFAULT_SCRYPT_N = 2 ** 17   # 128 MiB with r=8
SCRYPT_R = 8
SCRYPT_P = 1
BACKUP_EXTENSION = ".hagbackup"


class BackupError(Exception):
    pass


def validate_passphrase(passphrase: str, confirm: str = None) -> str:
    if len(passphrase) < MIN_PASSPHRASE:
        return f"Use a backup passphrase of at least {MIN_PASSPHRASE} characters."
    if confirm is not None and passphrase != confirm:
        return "The passphrases do not match."
    return ""


def _derive(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


RECOVERY_TEXT = """HOT ATTIC GAMES BUILD & SIGNING MANAGER — SIGNING IDENTITY RECOVERY

This archive was decrypted from a Build & Signing Manager backup. It contains:

  {keystore}        the Android keystore (KEEP PRIVATE)
  credentials.json  the keystore password, key alias and key password (KEEP PRIVATE)
  identity.json     public details, including the certificate SHA-256 fingerprint

Certificate SHA-256: {fingerprint}
Key alias:           {alias}

To restore with the application: Signing Identities > Restore from Backup.
To use without the application: the keystore works with any Android build tool
(Gradle signingConfigs, apksigner, Godot/Unity/Unreal export settings) using the
passwords in credentials.json. Verify with:

  keytool -list -v -keystore {keystore} -alias {alias}

and check that the SHA-256 fingerprint matches the one above.
"""


def build_archive(rec: IdentityRecord, keystore_bytes: bytes, creds: Credentials) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"keystore/{rec.keystore_filename}", keystore_bytes)
        zf.writestr("credentials.json", json.dumps({
            "store_password": creds.store_password,
            "key_alias": rec.alias,
            "key_password": creds.key_password,
        }, indent=2))
        zf.writestr("identity.json", json.dumps(rec.to_dict(), indent=2))
        zf.writestr("manifest.json", json.dumps({
            "keystore_file": rec.keystore_filename,
            "keystore_sha256": hashlib.sha256(keystore_bytes).hexdigest(),
            "fingerprint_sha256": rec.fingerprint_sha256,
            "created_at": now_iso(),
            "app_version": __version__,
        }, indent=2))
        zf.writestr("RECOVERY.txt", RECOVERY_TEXT.format(
            keystore=rec.keystore_filename, fingerprint=rec.fingerprint_sha256, alias=rec.alias))
    return buf.getvalue()


def encrypt(plaintext: bytes, passphrase: str, header_extra: dict, n: int = DEFAULT_SCRYPT_N) -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    header = {
        "kdf": "scrypt", "n": n, "r": SCRYPT_R, "p": SCRYPT_P,
        "salt": base64.b64encode(salt).decode(), "cipher": "AES-256-GCM",
        "nonce": base64.b64encode(nonce).decode(), **header_extra,
    }
    header_bytes = json.dumps(header, sort_keys=True).encode("utf-8") + b"\n"
    key = _derive(passphrase, salt, n, SCRYPT_R, SCRYPT_P)
    return MAGIC + header_bytes + AESGCM(key).encrypt(nonce, plaintext, MAGIC + header_bytes)


def read_header(data: bytes) -> tuple:
    if not data.startswith(MAGIC):
        raise BackupError("This file is not a Build & Signing Manager backup.")
    end = data.find(b"\n", len(MAGIC))
    if end < 0:
        raise BackupError("The backup file is damaged (header incomplete).")
    header_bytes = data[len(MAGIC):end + 1]
    try:
        header = json.loads(header_bytes)
    except ValueError as exc:
        raise BackupError("The backup file is damaged (header unreadable).") from exc
    return header, header_bytes, data[end + 1:]


def decrypt(data: bytes, passphrase: str) -> tuple:
    header, header_bytes, ct = read_header(data)
    if header.get("kdf") != "scrypt" or header.get("cipher") != "AES-256-GCM":
        raise BackupError("The backup uses an unsupported format.")
    try:
        salt = base64.b64decode(header["salt"])
        nonce = base64.b64decode(header["nonce"])
        key = _derive(passphrase, salt, int(header["n"]), int(header["r"]), int(header["p"]))
    except (KeyError, ValueError) as exc:
        raise BackupError("The backup file is damaged (bad key parameters).") from exc
    try:
        return header, AESGCM(key).decrypt(nonce, ct, MAGIC + header_bytes)
    except InvalidTag as exc:
        raise BackupError("The passphrase is incorrect, or the backup file has been modified or damaged.") from exc


@dataclass
class BackupContents:
    header: dict
    record: IdentityRecord
    keystore_filename: str
    keystore_bytes: bytes
    credentials: Credentials


def open_backup(path: Path, passphrase: str) -> BackupContents:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise BackupError(f"The backup file could not be read: {exc.strerror or exc}") from exc
    header, plain = decrypt(data, passphrase)
    try:
        with zipfile.ZipFile(io.BytesIO(plain)) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            creds_raw = json.loads(zf.read("credentials.json"))
            record = IdentityRecord.from_dict(json.loads(zf.read("identity.json")))
            ks_name = manifest["keystore_file"]
            ks_bytes = zf.read(f"keystore/{ks_name}")
    except (KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise BackupError("The backup decrypted, but its contents are incomplete.") from exc
    if hashlib.sha256(ks_bytes).hexdigest() != manifest.get("keystore_sha256"):
        raise BackupError("The keystore inside the backup does not match its recorded checksum.")
    creds = Credentials(creds_raw["store_password"], creds_raw["key_password"])
    register_secret(creds.store_password)
    register_secret(creds.key_password)
    return BackupContents(header, record, ks_name, ks_bytes, creds)


@dataclass
class VerifyResult:
    ok: bool
    message: str
    fingerprint: str = ""
    tool_checked: bool = False


def verify_backup(path: Path, passphrase: str, tools=None, expected_fingerprint: str = "") -> VerifyResult:
    """Decrypt the backup and, when keytool is available, open the keystore it contains with the
    stored passwords and compare the certificate fingerprint. This is a real recovery test."""
    try:
        contents = open_backup(path, passphrase)
    except BackupError as exc:
        return VerifyResult(False, str(exc))
    rec = contents.record
    expected = expected_fingerprint or rec.fingerprint_sha256
    if not (tools and tools.has_keytool):
        return VerifyResult(False, "The backup decrypted and its checksum is correct, but keytool is not "
                                   "available to confirm the keystore opens. Install a Java JDK to complete "
                                   "the recovery test.", rec.fingerprint_sha256)
    tmp = Path(tempfile.mkdtemp(prefix="hagbsm-verify-"))
    try:
        if os.name != "nt":
            os.chmod(tmp, 0o700)
        ks = tmp / contents.keystore_filename
        write_new_file(ks, contents.keystore_bytes)
        try:
            android.verify_key_access(tools, ks, contents.credentials.store_password, rec.alias,
                                      contents.credentials.key_password)
            cert = android.read_certificate(tools, ks, contents.credentials.store_password, rec.alias)
        except android.SigningError as exc:
            return VerifyResult(False, f"The keystore in the backup could not be opened: {exc}", tool_checked=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if android.normalize_fingerprint(cert.sha256) != android.normalize_fingerprint(expected):
        return VerifyResult(False, "The keystore in the backup has a different certificate than expected.",
                            cert.sha256, True)
    return VerifyResult(True, "Recovery test passed: the backup decrypts, the keystore opens with the stored "
                              "passwords, and the certificate fingerprint matches.", cert.sha256, True)


def create_backup(vault: IdentityVault, iid: str, dest: Path, passphrase: str, tools=None,
                  scrypt_n: int = DEFAULT_SCRYPT_N) -> VerifyResult:
    """Write an encrypted backup to `dest` (never overwriting) and immediately verify it."""
    err = validate_passphrase(passphrase)
    if err:
        raise BackupError(err)
    dest = Path(dest)
    if dest.exists():
        raise BackupError(f"{dest.name} already exists. Choose a new file name; existing backups are never overwritten.")
    rec = vault.get(iid)
    archive = build_archive(rec, vault.keystore_path(iid).read_bytes(), vault.credentials(iid))
    blob = encrypt(archive, passphrase, {
        "created_at": now_iso(), "identity_id": rec.id, "label": rec.label,
        "fingerprint_sha256": rec.fingerprint_sha256, "app_version": __version__,
    }, n=scrypt_n)
    try:
        write_new_file(dest, blob)
    except FileExistsError as exc:
        raise BackupError(f"{dest.name} already exists.") from exc
    except OSError as exc:
        raise BackupError(f"The backup could not be written: {exc.strerror or exc}") from exc
    if dest.read_bytes() != blob:
        raise BackupError("The backup file on disk does not match what was written. Try another location.")
    result = verify_backup(dest, passphrase, tools, rec.fingerprint_sha256)
    vault.add_backup(iid, str(dest), result.ok)
    return result


def restore_backup(vault: IdentityVault, path: Path, passphrase: str, tools, project_name: str = "") -> tuple:
    """Restore into the vault. Returns (record, created) — created is False if the same identity
    (same certificate fingerprint and id) is already in the vault."""
    contents = open_backup(path, passphrase)
    rec = contents.record
    if vault.exists(rec.id) and android.normalize_fingerprint(vault.get(rec.id).fingerprint_sha256) == \
            android.normalize_fingerprint(rec.fingerprint_sha256):
        return vault.get(rec.id), False
    tmp = Path(tempfile.mkdtemp(prefix="hagbsm-restore-"))
    try:
        if os.name != "nt":
            os.chmod(tmp, 0o700)
        ks = tmp / contents.keystore_filename
        write_new_file(ks, contents.keystore_bytes)
        cert = android.read_certificate(tools, ks, contents.credentials.store_password, rec.alias)
        if android.normalize_fingerprint(cert.sha256) != android.normalize_fingerprint(rec.fingerprint_sha256):
            raise BackupError("The keystore in the backup has a different certificate than its recorded fingerprint.")
        new_rec = vault.import_keystore(tools, ks, contents.credentials.store_password, rec.alias,
                                        contents.credentials.key_password, project_name or rec.project_name,
                                        source="restored", label=rec.label)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    new_rec.original_path = str(path)
    new_rec.backups = [{"path": str(path), "created_at": contents.header.get("created_at", ""),
                        "verified": True, "verified_at": now_iso()}]
    vault.save_record(new_rec)
    return new_rec, True
