"""Locations of user data. Nothing here is created until it is first needed."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

_VENDOR = "HotAtticGames"
_PRODUCT = "BuildSigningManager"


@dataclass(frozen=True)
class AppPaths:
    config_root: Path   # profiles, settings, logs
    vault_root: Path    # signing identities (kept apart from ordinary profile data)

    @property
    def profiles_dir(self) -> Path:
        return self.config_root / "profiles"

    @property
    def deleted_profiles_dir(self) -> Path:
        return self.profiles_dir / "deleted"

    @property
    def settings_file(self) -> Path:
        return self.config_root / "settings.json"

    @property
    def logs_dir(self) -> Path:
        return self.config_root / "logs"

    @property
    def identities_dir(self) -> Path:
        return self.vault_root / "identities"


def default_paths() -> AppPaths:
    override = os.environ.get("HAGBSM_HOME")
    if override:
        base = Path(override)
        return AppPaths(base / "config", base / "vault")
    if sys.platform == "win32":
        roaming = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return AppPaths(roaming / _VENDOR / _PRODUCT, local / _VENDOR / _PRODUCT / "vault")
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return AppPaths(data / "hag-bsm" / "config", data / "hag-bsm" / "vault")
