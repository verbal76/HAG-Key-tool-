"""Saved project profiles: listing, atomic saving, migration, soft deletion, export and import."""

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from .fsutil import atomic_write_json, write_new_file
from .model import MAX_SCHEMA_VERSION, PLATFORMS, SCHEMA_VERSION, Profile, new_id, now_iso

log = logging.getLogger(__name__)

EXPORT_FORMAT = "hag-bsm-profile"


class ProfileError(Exception):
    pass


@dataclass
class BrokenProfile:
    """A profile file that could not be read. It is reported, never modified or deleted."""
    path: Path
    error: str


# --- migration ----------------------------------------------------------------

def _migrate_v0(d: dict) -> dict:
    """Pre-release drafts had no schema_version, a flat platform list and a top-level keystore id."""
    out = dict(d)
    plats = d.get("platforms", [])
    if isinstance(plats, list):
        out["platforms"] = {
            p.key: {"enabled": p.key in plats, "formats": list(p.default_formats)} for p in PLATFORMS
        }
    out.setdefault("signing", {"android_identity_id": d.get("android_keystore_id", "")})
    out.pop("android_keystore_id", None)
    out["schema_version"] = 1
    return out


_MIGRATIONS = {0: _migrate_v0}


def migrate(data: dict) -> dict:
    """Return `data` upgraded to SCHEMA_VERSION. Raises ProfileError for unknown or newer versions."""
    if not isinstance(data, dict):
        raise ProfileError("The profile file does not contain a JSON object.")
    version = data.get("schema_version", 0)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ProfileError("The profile has an invalid schema_version.")
    if version > MAX_SCHEMA_VERSION:
        raise ProfileError(f"This profile was saved by a newer version of the application "
                           f"(schema {version}). Update the application to open it.")
    while version < SCHEMA_VERSION:
        step = _MIGRATIONS.get(version)
        if step is None:
            raise ProfileError(f"No migration is available from profile schema {version}.")
        data = step(data)
        version = data["schema_version"]
    return data


def parse_profile_data(data) -> Profile:
    try:
        return Profile.from_dict(migrate(data))
    except ValueError as exc:
        raise ProfileError(f"The profile data is invalid: {exc}") from exc


# --- store ----------------------------------------------------------------------

class ProfileStore:
    def __init__(self, profiles_dir: Path, deleted_dir: Path):
        self.dir = profiles_dir
        self.deleted_dir = deleted_dir

    def _path(self, pid: str) -> Path:
        return self.dir / f"{pid}.json"

    def list(self) -> list:
        """Return Profiles and BrokenProfiles, newest modification first."""
        if not self.dir.is_dir():
            return []
        good, broken = [], []
        for path in sorted(self.dir.glob("*.json")):
            if ".bak." in path.name:
                continue  # pre-migration copies, kept for recovery only
            try:
                good.append(self._read(path))
            except ProfileError as exc:
                broken.append(BrokenProfile(path, str(exc)))
        good.sort(key=lambda p: p.modified_at, reverse=True)
        return good + broken

    def _read(self, path: Path) -> Profile:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            raise ProfileError(f"Could not read {path.name}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ProfileError(f"{path.name} is not valid JSON ({exc.msg} at line {exc.lineno}).") from exc
        original_version = raw.get("schema_version", 0) if isinstance(raw, dict) else None
        profile = parse_profile_data(raw)
        if original_version == 0:
            # Keep the pre-migration file before writing the upgraded one.
            backup = path.with_name(f"{path.stem}.v{original_version}.bak.json")
            if not backup.exists():
                shutil.copy2(path, backup)
            atomic_write_json(path, profile.to_dict())
            log.info("Migrated profile %s from schema %s", profile.id, original_version)
        return profile

    def load(self, pid: str) -> Profile:
        path = self._path(pid)
        if not path.is_file():
            raise ProfileError("The project profile no longer exists.")
        return self._read(path)

    def exists(self, pid: str) -> bool:
        return self._path(pid).is_file()

    def save(self, profile: Profile) -> Profile:
        profile.modified_at = now_iso()
        atomic_write_json(self._path(profile.id), profile.to_dict())
        return profile

    def duplicate(self, profile: Profile) -> Profile:
        """Copy a profile under a new id. The signing identity link is NOT copied: a new
        game normally needs its own identity, and sharing one by accident is hard to undo."""
        copy = profile.clone()
        copy.id = new_id()
        copy.name = f"{profile.name} (copy)" if profile.name else "Untitled (copy)"
        copy.android_identity_id = ""
        copy.created_at = now_iso()
        return self.save(copy)

    def delete(self, pid: str) -> Path:
        """Move the profile into the deleted folder (recoverable). Signing identities are untouched."""
        src = self._path(pid)
        if not src.is_file():
            raise ProfileError("The project profile no longer exists.")
        self.deleted_dir.mkdir(parents=True, exist_ok=True)
        stamp = now_iso().replace(":", "").replace("+", "_")
        dest = self.deleted_dir / f"{pid}-{stamp}.json"
        n = 1
        while dest.exists():
            dest = self.deleted_dir / f"{pid}-{stamp}-{n}.json"
            n += 1
        src.replace(dest)
        return dest

    # --- export / import -------------------------------------------------------

    @staticmethod
    def export_to(profile: Profile, dest: Path, overwrite: bool = False, identity_summary: dict = None) -> None:
        """Write a shareable profile file. Profiles contain no secrets; only the public
        certificate fingerprint of a linked identity is included for reference."""
        payload = {
            "export_format": EXPORT_FORMAT,
            "exported_at": now_iso(),
            "profile": profile.to_dict(),
        }
        if identity_summary:
            payload["android_identity_public"] = {
                k: identity_summary[k] for k in ("alias", "fingerprint_sha256") if k in identity_summary
            }
        data = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        if overwrite:
            atomic_write_json(dest, payload)
        else:
            write_new_file(dest, data)

    @staticmethod
    def read_export(src: Path) -> Profile:
        try:
            raw = json.loads(Path(src).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            raise ProfileError(f"Could not read the file: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ProfileError(f"The file is not valid JSON ({exc.msg} at line {exc.lineno}).") from exc
        if isinstance(raw, dict) and raw.get("export_format") == EXPORT_FORMAT:
            raw = raw.get("profile")
        elif isinstance(raw, dict) and "export_format" in raw:
            raise ProfileError("This file is not a Build & Signing Manager profile export.")
        return parse_profile_data(raw)

    def import_profile(self, profile: Profile, mode: str) -> Profile:
        """mode: 'new' (no conflict), 'replace' (overwrite same id) or 'copy' (new id)."""
        if mode == "copy":
            profile = profile.clone()
            profile.id = new_id()
            profile.name = f"{profile.name} (imported)"
        elif mode == "new" and self.exists(profile.id):
            raise ProfileError("A project with the same internal id already exists.")
        elif mode not in ("new", "replace"):
            raise ValueError(mode)
        return self.save(profile)
