"""Finding older or separately stored project profiles and importing them safely.

Importing is always the owner's decision. The source file is only ever read; before anything is
written a verified copy is kept in `migration_backups`."""

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from .fsutil import atomic_write_json
from .model import Profile
from .profiles import EXPORT_FORMAT, ProfileError, ProfileStore, migrate, parse_profile_data

MAX_BYTES = 2_000_000
_NOT_PROFILES = {"settings.json", "discovery.json"}
_SKIP_DIRS = {"profiles", "deleted", "logs", "migration_backups"}


@dataclass
class Candidate:
    path: Path
    sha: str
    fmt: str            # v0, v1, v2, export
    status: str         # new, registered, conflict, declined, invalid
    profile: Profile = None
    error: str = ""
    identity_id: str = ""
    existing_name: str = ""

    @property
    def importable(self) -> bool:
        return self.status in ("new", "conflict", "declined")


def _load_declined(config_root: Path) -> dict:
    try:
        return dict(json.loads((config_root / "discovery.json").read_text("utf-8")).get("declined", {}))
    except (OSError, ValueError, AttributeError):
        return {}


def decline(config_root: Path, candidates) -> None:
    """Remember skipped files so they are not offered again unless they change or a rescan is requested."""
    declined = _load_declined(config_root)
    for c in candidates:
        declined[str(c.path)] = c.sha
    atomic_write_json(config_root / "discovery.json", {"declined": declined})


def _files(config_root: Path, extra_dirs):
    seen = set()
    roots = [(config_root, True)] + [(Path(d), True) for d in extra_dirs]
    for root, descend in roots:
        if not root.is_dir():
            continue
        dirs = [root] + ([d for d in sorted(root.iterdir()) if d.is_dir() and d.name not in _SKIP_DIRS] if descend else [])
        for d in dirs:
            for f in sorted(d.glob("*.json")):
                if f.name in _NOT_PROFILES or ".bak." in f.name or f in seen or not f.is_file():
                    continue
                seen.add(f)
                yield f


def scan(config_root: Path, store: ProfileStore, extra_dirs=(), force: bool = False) -> list:
    declined = {} if force else _load_declined(config_root)
    out = []
    for f in _files(config_root, extra_dirs):
        if f.stat().st_size > MAX_BYTES:
            continue
        raw_bytes = f.read_bytes()
        try:
            raw = json.loads(raw_bytes.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue   # not JSON: not ours
        if not isinstance(raw, dict):
            continue
        fmt = "export" if raw.get("export_format") == EXPORT_FORMAT else None
        data = raw.get("profile") if fmt else raw
        if not isinstance(data, dict) or not ("id" in data and ("name" in data or "platforms" in data)):
            continue   # some other JSON file
        sha = hashlib.sha256(raw_bytes).hexdigest()
        fmt = fmt or f"v{data.get('schema_version', 0)}"
        try:
            migrated = migrate(data)
            profile = parse_profile_data(data)
        except ProfileError as exc:
            out.append(Candidate(f, sha, fmt, "invalid", error=str(exc)))
            continue
        identity = (data.get("signing") or {}).get("android_identity_id") or data.get("android_keystore_id", "")
        cand = Candidate(f, sha, fmt, "new", profile, identity_id=identity if isinstance(identity, str) else "")
        if store.exists(profile.id):
            try:
                same = store.load(profile.id).to_dict() == profile.to_dict()
            except ProfileError:
                same = False
            cand.status = "registered" if same else "conflict"
            cand.existing_name = profile.name
        if cand.status in ("new", "conflict") and declined.get(str(f)) == sha:
            cand.status = "declined"
        out.append(cand)
        del migrated
    return out


def import_candidate(store: ProfileStore, config_root: Path, cand: Candidate, mode: str = "new") -> Profile:
    """Import with every safety step; raises ProfileError and leaves the store unchanged on failure."""
    # 1. validate the source is still what was scanned
    if cand.profile is None or not cand.path.is_file() or hashlib.sha256(cand.path.read_bytes()).hexdigest() != cand.sha:
        raise ProfileError("The source file changed or is not a valid profile. Scan again.")
    # 2-3. recoverable backup, confirmed byte for byte
    backups = config_root / "migration_backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = Profile().created_at.replace(":", "").replace("+", "_")
    backup = backups / f"{stamp}-{cand.path.name}"
    n = 1
    while backup.exists():
        backup = backups / f"{stamp}-{n}-{cand.path.name}"
        n += 1
    shutil.copy2(cand.path, backup)
    if not backup.is_file() or backup.read_bytes() != cand.path.read_bytes():
        raise ProfileError("The backup of the source profile could not be verified, so nothing was imported.")
    # 4-6. migrate a copy, validate it, and confirm the signing identity reference survived
    migrated = cand.profile.clone()
    try:
        round_trip = Profile.from_dict(migrated.to_dict())
    except ValueError as exc:
        raise ProfileError(f"The migrated profile did not validate: {exc}") from exc
    if round_trip.id != migrated.id or round_trip.name != migrated.name:
        raise ProfileError("The migrated profile did not match its source.")
    if migrated.android_identity_id != cand.identity_id:
        raise ProfileError("The signing identity reference changed during migration, so nothing was imported.")
    # 7-8. write; restore the previous state if that fails. The original source is never modified or deleted.
    target = store._path(migrated.id) if mode == "replace" else None
    previous = target.read_bytes() if target and target.is_file() else None
    if previous is not None:
        (backups / f"{stamp}-replaced-{target.name}").write_bytes(previous)
    saved = None
    try:
        saved = store.import_profile(migrated, mode)
        if store.load(saved.id).to_dict()["id"] != saved.id:
            raise ProfileError("The imported profile could not be read back.")
        return saved
    except Exception as exc:
        if mode == "replace" and previous is not None:
            target.write_bytes(previous)
        elif saved is not None:
            store._path(saved.id).unlink(missing_ok=True)
        raise ProfileError(f"The import failed and was rolled back: {exc}") from exc
