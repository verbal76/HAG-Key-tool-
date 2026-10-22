"""Signing identity vault.

Each identity lives in its own folder under the vault root:

    identities/<id>/identity.json    public metadata (alias, fingerprint, backups…) — no secrets
    identities/<id>/<keystore file>  the keystore itself
    identities/<id>/credentials.bin  passwords, protected with DPAPI (see protect.py)

The application never deletes identity folders. Profiles only hold an identity id.
"""

import base64
import json
import os
import re
import secrets
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import android
from .fsutil import atomic_write_bytes, atomic_write_json, ensure_private_dir
from .model import new_id, now_iso, slugify
from .protect import Protector
from .redact import register_secret
from .tools import AndroidTools

PASSWORD_BYTES = 24   # 32 URL-safe characters


def generate_password() -> str:
    return secrets.token_urlsafe(PASSWORD_BYTES)


@dataclass
class Credentials:
    store_password: str
    key_password: str


@dataclass
class IdentityRecord:
    id: str
    label: str
    alias: str
    keystore_filename: str
    store_type: str
    source: str                     # generated, imported, restored
    fingerprint_sha256: str
    fingerprint_sha1: str = ""
    subject: str = ""
    not_before: str = ""
    not_after: str = ""
    key_algorithm: str = ""
    key_size: int = 0
    key_password_matches_store: bool = True
    original_path: str = ""         # where an imported keystore came from (left untouched)
    project_name: str = ""
    created_at: str = field(default_factory=now_iso)
    backups: list = field(default_factory=list)   # [{path, created_at, verified, verified_at}]
    last_recovery_test: dict = field(default_factory=dict)  # {path, ok, at, message}
    platform: str = "android"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["format"] = 1
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "IdentityRecord":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    # -- status helpers --
    @property
    def has_verified_backup(self) -> bool:
        return any(b.get("verified") for b in self.backups)

    @property
    def has_any_backup(self) -> bool:
        return bool(self.backups)

    def public_summary(self) -> dict:
        return {"alias": self.alias, "fingerprint_sha256": self.fingerprint_sha256}


class VaultError(Exception):
    pass


def proposed_names(project_name: str) -> tuple:
    slug = slugify(project_name) or "app"
    return f"{slug}-release.jks", f"{slug}_release"


class IdentityVault:
    def __init__(self, identities_dir: Path, vault_root: Path):
        self.dir = Path(identities_dir)
        self.protector = Protector(vault_root)

    def _folder(self, iid: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", iid or ""):
            raise VaultError("Invalid identity id.")
        return self.dir / iid

    # -- queries --
    def list(self) -> list:
        if not self.dir.is_dir():
            return []
        out = []
        for meta in sorted(self.dir.glob("*/identity.json")):
            try:
                out.append(IdentityRecord.from_dict(json.loads(meta.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError):
                continue
        out.sort(key=lambda r: r.created_at)
        return out

    def exists(self, iid: str) -> bool:
        try:
            return (self._folder(iid) / "identity.json").is_file()
        except VaultError:
            return False

    def get(self, iid: str) -> IdentityRecord:
        path = self._folder(iid) / "identity.json"
        if not path.is_file():
            raise VaultError("The signing identity was not found in the vault.")
        return IdentityRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def find_by_fingerprint(self, fingerprint: str) -> list:
        want = android.normalize_fingerprint(fingerprint)
        return [r for r in self.list() if android.normalize_fingerprint(r.fingerprint_sha256) == want]

    def keystore_path(self, iid: str) -> Path:
        rec = self.get(iid)
        return self._folder(iid) / rec.keystore_filename

    def folder(self, iid: str) -> Path:
        return self._folder(iid)

    def credentials(self, iid: str) -> Credentials:
        blob = (self._folder(iid) / "credentials.bin").read_bytes()
        data = json.loads(self.protector.unprotect(blob).decode("utf-8"))
        creds = Credentials(data["store_password"], data["key_password"])
        register_secret(creds.store_password)
        register_secret(creds.key_password)
        return creds

    def keystore_base64(self, iid: str) -> str:
        value = base64.b64encode(self.keystore_path(iid).read_bytes()).decode("ascii")
        register_secret(value)
        return value

    # -- mutation --
    def save_record(self, rec: IdentityRecord) -> None:
        atomic_write_json(self._folder(rec.id) / "identity.json", rec.to_dict())

    def _write_credentials(self, iid: str, creds: Credentials) -> None:
        payload = json.dumps({"store_password": creds.store_password, "key_password": creds.key_password})
        atomic_write_bytes(self._folder(iid) / "credentials.bin", self.protector.protect(payload.encode("utf-8")))

    def _new_folder(self) -> tuple:
        ensure_private_dir(self.dir)
        iid = new_id()
        folder = self._folder(iid)
        folder.mkdir()
        if os.name != "nt":
            os.chmod(folder, 0o700)
        return iid, folder

    def _record_from_cert(self, iid, label, alias, filename, store_type, source, cert, **extra) -> IdentityRecord:
        return IdentityRecord(
            id=iid, label=label, alias=alias, keystore_filename=filename, store_type=store_type,
            source=source, fingerprint_sha256=cert.sha256, fingerprint_sha1=cert.sha1, subject=cert.subject,
            not_before=cert.not_before, not_after=cert.not_after, key_algorithm=cert.key_algorithm,
            key_size=cert.key_size, **extra)

    def generate(self, tools: AndroidTools, project_name: str, alias: str, filename: str, dname: str,
                 validity_days: int = android.DEFAULT_VALIDITY_DAYS) -> IdentityRecord:
        """Generate a brand-new identity in its own folder. Never touches existing identities."""
        _check_filename(filename)
        _check_alias(alias)
        password = generate_password()
        register_secret(password)
        iid, folder = self._new_folder()
        try:
            cert = android.generate_keystore(tools, folder / filename, alias, password, dname, validity_days)
            self._write_credentials(iid, Credentials(password, password))
            rec = self._record_from_cert(iid, f"{project_name} release key", alias, filename, "PKCS12",
                                         "generated", cert, project_name=project_name)
            self.save_record(rec)
            return rec
        except BaseException:
            # Nothing usable was produced: remove only the folder this call created.
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def import_keystore(self, tools: AndroidTools, src: Path, store_password: str, alias: str,
                        key_password: str, project_name: str = "", source: str = "imported",
                        label: str = "") -> IdentityRecord:
        """Copy an existing keystore into the vault after verifying it. The original is not modified."""
        src = Path(src)
        if not src.is_file():
            raise VaultError("The keystore file was not found.")
        register_secret(store_password)
        register_secret(key_password)
        entries = android.list_aliases(tools, src, store_password)
        entry = next((e for e in entries if e.alias == alias), None)
        if entry is None:
            raise android.SigningError("alias_not_found", f"The alias '{alias}' is not in this keystore.")
        if not entry.has_private_key:
            raise android.SigningError("no_private_key",
                                       f"'{alias}' does not contain a private key and cannot sign apps.")
        android.verify_key_access(tools, src, store_password, alias, key_password)
        cert = android.read_certificate(tools, src, store_password, alias)

        iid, folder = self._new_folder()
        try:
            filename = _safe_filename(src.name)
            shutil.copy2(src, folder / filename)
            if (folder / filename).read_bytes() != src.read_bytes():
                raise VaultError("The keystore copy in the vault does not match the original file.")
            self._write_credentials(iid, Credentials(store_password, key_password))
            rec = self._record_from_cert(
                iid, label or f"{project_name or src.stem} ({source})", alias, filename,
                android.detect_store_type(src), source, cert, original_path=str(src),
                key_password_matches_store=(store_password == key_password), project_name=project_name)
            self.save_record(rec)
            return rec
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def add_backup(self, iid: str, path: str, verified: bool) -> IdentityRecord:
        rec = self.get(iid)
        rec.backups.append({"path": path, "created_at": now_iso(), "verified": verified,
                            "verified_at": now_iso() if verified else ""})
        self.save_record(rec)
        return rec

    def record_recovery_test(self, iid: str, path: str, ok: bool, message: str) -> IdentityRecord:
        rec = self.get(iid)
        rec.last_recovery_test = {"path": path, "ok": ok, "at": now_iso(), "message": message}
        if ok:
            for b in rec.backups:
                if os.path.normcase(b.get("path", "")) == os.path.normcase(path):
                    b["verified"] = True
                    b["verified_at"] = now_iso()
        self.save_record(rec)
        return rec


def _check_filename(name: str) -> None:
    if not name or name != _safe_filename(name):
        raise VaultError("The keystore filename may only contain letters, digits, '.', '_' and '-'.")


def _check_alias(alias: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", alias or ""):
        raise VaultError("The key alias may only contain letters, digits, '.', '_' and '-' (max 64 characters).")


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._") or "keystore.jks"
    return cleaned[:100]
