"""Profile validation with plain-language messages.

Errors block prompt generation; warnings are shown but do not block.
"""

import re
from dataclasses import dataclass

from .icons import inspect_icon
from .model import APPLE_PLATFORMS, PLATFORM_BY_KEY, Profile
from .secret_names import validate_suffix

ERROR = "error"
WARNING = "warning"

ANDROID_MAX_VERSION_CODE = 2_100_000_000

_JAVA_KEYWORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char", "class", "const",
    "continue", "default", "do", "double", "else", "enum", "extends", "false", "final", "finally",
    "float", "for", "goto", "if", "implements", "import", "instanceof", "int", "interface", "long",
    "native", "new", "null", "package", "private", "protected", "public", "return", "short",
    "static", "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
    "transient", "true", "try", "void", "volatile", "while",
}


@dataclass(frozen=True)
class Issue:
    level: str
    field: str
    message: str


def validate_android_package(value: str) -> str:
    if not value:
        return "An Android package name is required when Android is selected."
    parts = value.split(".")
    if len(parts) < 2:
        return "The Android package name needs at least two parts, e.g. com.hotatticgames.mygame."
    for part in parts:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", part):
            return (f"'{part}' is not allowed in an Android package name. Each part must start with a "
                    "letter and contain only letters, digits and underscores.")
        if part in _JAVA_KEYWORDS:
            return f"'{part}' is a reserved Java word and cannot be part of an Android package name."
    return ""


def validate_bundle_id(value: str, what: str = "Apple bundle identifier") -> str:
    if not value:
        return f"An {what} is required when an Apple platform is selected."
    if not re.fullmatch(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+", value):
        return (f"The {what} may only contain letters, digits, hyphens and periods, "
                "with at least two parts, e.g. com.hotatticgames.mygame.")
    return ""


def validate_version(version: str, platforms) -> str:
    if not re.fullmatch(r"\d+(\.\d+){0,3}", version or ""):
        return "Use a version made of numbers separated by periods, e.g. 1.0.0."
    parts = version.split(".")
    if any(p != "0" and p.startswith("0") for p in parts):
        return "Version numbers should not have leading zeros (use 1.2.0, not 1.02.0)."
    if any(k in platforms for k in APPLE_PLATFORMS) and len(parts) > 3:
        return "Apple platforms allow at most three version numbers (e.g. 1.2.3)."
    if "windows" in platforms and any(int(p) > 65535 for p in parts):
        return "Windows version numbers must each be 65535 or less."
    return ""


def validate_build_number(build, platforms) -> str:
    if not isinstance(build, int) or isinstance(build, bool) or build < 1:
        return "The build number must be a whole number of 1 or more."
    if "android" in platforms and build > ANDROID_MAX_VERSION_CODE:
        return f"Android build numbers (versionCode) must be {ANDROID_MAX_VERSION_CODE:,} or less."
    return ""


def validate_profile(p: Profile, identity_exists=None) -> list:
    """Return a list of Issues. `identity_exists(id) -> bool` checks the vault if provided."""
    issues = []
    add = lambda level, fld, msg: issues.append(Issue(level, fld, msg))
    plats = p.enabled_platforms()

    if not p.name.strip():
        add(ERROR, "name", "Enter an application name.")
    elif len(p.name) > 100:
        add(ERROR, "name", "The application name must be 100 characters or fewer.")
    if not p.publisher.strip():
        add(ERROR, "publisher", "Enter a publisher name.")

    if err := validate_version(p.version, plats):
        add(ERROR, "version", err)
    if err := validate_build_number(p.build_number, plats):
        add(ERROR, "build_number", err)

    if not plats:
        add(ERROR, "platforms", "Select at least one build platform.")
    for key in plats:
        if not p.formats(key):
            add(ERROR, f"formats.{key}", f"Choose at least one output format for {PLATFORM_BY_KEY[key].label}.")

    if "android" in plats and (err := validate_android_package(p.android_package.strip())):
        add(ERROR, "android_package", err)
    if any(k in plats for k in APPLE_PLATFORMS):
        if err := validate_bundle_id(p.apple_bundle_id.strip()):
            add(ERROR, "apple_bundle_id", err)
    if "macos" in plats and p.macos_bundle_id.strip():
        if err := validate_bundle_id(p.macos_bundle_id.strip(), "macOS bundle identifier"):
            add(ERROR, "macos_bundle_id", err)
    if p.desktop_app_id.strip() and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", p.desktop_app_id.strip()):
        add(ERROR, "desktop_app_id", "The desktop identifier may only contain letters, digits, '.', '_' and '-'.")

    stores = set(p.stores)
    if not stores:
        add(WARNING, "stores", "No target store selected. Choose 'No Store / Private Distribution' if none apply.")
    if "private" in stores and len(stores) > 1:
        add(WARNING, "stores", "'No Store / Private Distribution' is selected together with a store.")
    if "google_play" in stores and "android" not in plats:
        add(WARNING, "stores", "Google Play is selected but Android is not.")
    if "app_store" in stores and not any(k in plats for k in APPLE_PLATFORMS):
        add(WARNING, "stores", "Apple App Store is selected but neither iOS / iPadOS nor macOS is.")
    if "steam" in stores and not any(k in plats for k in ("windows", "linux", "macos")):
        add(WARNING, "stores", "Steam is selected but no desktop platform (Windows, Linux, macOS) is.")
    if "google_play" in stores and "android" in plats and "aab" not in p.formats("android"):
        add(WARNING, "formats.android", "Google Play requires an AAB for new apps; only APK is selected.")

    if p.icon_path.strip():
        info = inspect_icon(p.icon_path.strip())
        if not info.exists or info.error:
            add(ERROR, "icon_path", info.error or "The icon file was not found.")
        else:
            if info.kind == "unknown":
                add(WARNING, "icon_path", "The icon file type was not recognised. PNG is the most widely supported.")
            if info.kind == "png" and info.width != info.height:
                add(WARNING, "icon_path", f"The icon is {info.width}×{info.height}; app icons should be square.")
            if info.kind == "png" and ("ios" in plats or "app_store" in stores) and min(info.width, info.height) < 1024:
                add(WARNING, "icon_path", "Apple requires a 1024×1024 PNG icon for App Store builds.")
            elif info.kind == "png" and ("android" in plats or "google_play" in stores) and min(info.width, info.height) < 512:
                add(WARNING, "icon_path", "Google Play requires a 512×512 PNG icon.")
            if "windows" in plats and info.kind not in ("ico", "png"):
                add(WARNING, "icon_path", "Windows executables normally use a .ico icon (or a PNG converted to .ico).")

    if p.secret_use_suffix and (err := validate_suffix(p.secret_suffix)):
        add(ERROR, "secret_suffix", err)

    if "android" in plats:
        if not p.android_identity_id:
            add(WARNING, "signing", "No Android signing identity is configured for this project yet.")
        elif identity_exists is not None and not identity_exists(p.android_identity_id):
            add(ERROR, "signing", "The Android signing identity linked to this project is missing from the vault. "
                                  "Restore it from a backup or re-import the keystore.")
    return issues


def has_errors(issues) -> bool:
    return any(i.level == ERROR for i in issues)
