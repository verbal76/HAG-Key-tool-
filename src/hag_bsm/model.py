"""Project profile data model. Profiles hold configuration only, never secret material."""

import copy
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import PUBLISHER

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PlatformSpec:
    key: str
    label: str
    formats: tuple  # ((key, label), ...)
    default_formats: tuple


PLATFORMS = (
    PlatformSpec("android", "Android", (("apk", "APK"), ("aab", "AAB (Android App Bundle)")), ("aab",)),
    PlatformSpec("windows", "Windows", (("exe", "EXE"), ("installer", "Installer package (if the project supports one)")), ("exe",)),
    PlatformSpec("linux", "Linux", (("executable", "Native executable"), ("package", "Distribution package (AppImage, .deb, .rpm, …)")), ("executable",)),
    PlatformSpec("macos", "macOS", (("app", "APP bundle"), ("dmg", "DMG disk image")), ("app",)),
    PlatformSpec("ios", "iOS / iPadOS", (("ipa", "IPA"),), ("ipa",)),
    PlatformSpec("web", "Web", (("html5", "HTML5 / WebAssembly"),), ("html5",)),
)
PLATFORM_BY_KEY = {p.key: p for p in PLATFORMS}
APPLE_PLATFORMS = ("macos", "ios")

STORES = (
    ("google_play", "Google Play"),
    ("app_store", "Apple App Store"),
    ("steam", "Steam"),
    ("private", "No Store / Private Distribution"),
)
STORE_LABELS = dict(STORES)

CHANNELS = (
    ("private_testing", "Private Testing"),
    ("beta", "Beta"),
    ("production", "Production"),
)
CHANNEL_LABELS = dict(CHANNELS)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


def slugify(text: str, sep: str = "") -> str:
    """ASCII lowercase slug, e.g. 'Backrooms Survivor' -> 'backroomssurvivor'."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return sep.join(words)


def _default_platforms() -> dict:
    return {p.key: {"enabled": False, "formats": list(p.default_formats)} for p in PLATFORMS}


@dataclass
class Profile:
    id: str = field(default_factory=new_id)
    name: str = ""
    publisher: str = PUBLISHER
    android_package: str = ""
    apple_bundle_id: str = ""
    macos_bundle_id: str = ""   # blank = same as apple_bundle_id
    desktop_app_id: str = ""    # optional, Windows/Linux
    version: str = "1.0.0"
    build_number: int = 1
    release_channel: str = "private_testing"
    icon_path: str = ""
    platforms: dict = field(default_factory=_default_platforms)
    stores: list = field(default_factory=list)
    android_identity_id: str = ""
    secret_use_suffix: bool = False
    secret_suffix: int = 2
    created_at: str = field(default_factory=now_iso)
    modified_at: str = field(default_factory=now_iso)

    # --- convenience -----------------------------------------------------
    def enabled_platforms(self) -> list:
        return [p.key for p in PLATFORMS if self.platforms.get(p.key, {}).get("enabled")]

    def is_enabled(self, key: str) -> bool:
        return bool(self.platforms.get(key, {}).get("enabled"))

    def formats(self, key: str) -> list:
        allowed = [f for f, _ in PLATFORM_BY_KEY[key].formats]
        chosen = self.platforms.get(key, {}).get("formats", [])
        return [f for f in allowed if f in chosen]

    def effective_macos_bundle_id(self) -> str:
        return self.macos_bundle_id.strip() or self.apple_bundle_id.strip()

    def slug(self) -> str:
        return slugify(self.name) or "app"

    def clone(self) -> "Profile":
        return Profile.from_dict(self.to_dict())

    # --- serialisation ---------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "publisher": self.publisher,
            "identifiers": {
                "android_package": self.android_package,
                "apple_bundle_id": self.apple_bundle_id,
                "macos_bundle_id": self.macos_bundle_id,
                "desktop_app_id": self.desktop_app_id,
            },
            "version": self.version,
            "build_number": self.build_number,
            "release_channel": self.release_channel,
            "icon_path": self.icon_path,
            "platforms": copy.deepcopy(self.platforms),
            "stores": list(self.stores),
            "signing": {"android_identity_id": self.android_identity_id},
            "github_secrets": {"use_suffix": self.secret_use_suffix, "suffix": self.secret_suffix},
            "created_at": self.created_at,
            "modified_at": self.modified_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        """Build a profile from current-schema data. Raises ValueError on malformed input."""
        if not isinstance(d, dict):
            raise ValueError("profile data must be a JSON object")
        if d.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported profile schema version {d.get('schema_version')!r}")
        pid = d.get("id")
        if not isinstance(pid, str) or not re.fullmatch(r"[0-9a-f]{32}", pid):
            raise ValueError("profile id is missing or malformed")

        def s(obj, key, default=""):
            v = obj.get(key, default)
            if not isinstance(v, str):
                raise ValueError(f"field {key!r} must be text")
            return v

        ids = d.get("identifiers", {})
        sign = d.get("signing", {})
        gh = d.get("github_secrets", {})
        if not all(isinstance(x, dict) for x in (ids, sign, gh)):
            raise ValueError("identifiers, signing and github_secrets must be objects")

        build = d.get("build_number", 1)
        if not isinstance(build, int) or isinstance(build, bool):
            raise ValueError("build_number must be an integer")
        suffix = gh.get("suffix", 2)
        if not isinstance(suffix, int) or isinstance(suffix, bool):
            raise ValueError("github_secrets.suffix must be an integer")

        platforms = _default_platforms()
        raw_platforms = d.get("platforms", {})
        if not isinstance(raw_platforms, dict):
            raise ValueError("platforms must be an object")
        for key, val in raw_platforms.items():
            if key not in platforms:
                continue  # unknown platform from a newer build: ignore rather than fail
            if not isinstance(val, dict):
                raise ValueError(f"platform {key!r} must be an object")
            allowed = {f for f, _ in PLATFORM_BY_KEY[key].formats}
            formats = val.get("formats", [])
            if not isinstance(formats, list):
                raise ValueError(f"platform {key!r} formats must be a list")
            platforms[key] = {
                "enabled": bool(val.get("enabled", False)),
                "formats": [f for f in formats if f in allowed],
            }

        stores = d.get("stores", [])
        if not isinstance(stores, list):
            raise ValueError("stores must be a list")
        channel = s(d, "release_channel", "private_testing")
        if channel not in CHANNEL_LABELS:
            raise ValueError(f"unknown release channel {channel!r}")

        return cls(
            id=pid,
            name=s(d, "name"),
            publisher=s(d, "publisher", PUBLISHER),
            android_package=s(ids, "android_package"),
            apple_bundle_id=s(ids, "apple_bundle_id"),
            macos_bundle_id=s(ids, "macos_bundle_id"),
            desktop_app_id=s(ids, "desktop_app_id"),
            version=s(d, "version", "1.0.0"),
            build_number=build,
            release_channel=channel,
            icon_path=s(d, "icon_path"),
            platforms=platforms,
            stores=[x for x in stores if x in STORE_LABELS],
            android_identity_id=s(sign, "android_identity_id"),
            secret_use_suffix=bool(gh.get("use_suffix", False)),
            secret_suffix=suffix,
            created_at=s(d, "created_at", now_iso()),
            modified_at=s(d, "modified_at", now_iso()),
        )
