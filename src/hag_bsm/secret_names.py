"""GitHub Actions secret names for Android signing.

A secret *name* is only a label in the repository. Changing it never touches the signing identity.
"""

import re

ROLES = ("keystore_base64", "keystore_password", "key_alias", "key_password")

DEFAULT_NAMES = {
    "keystore_base64": "ANDROID_RELEASE_KEYSTORE_BASE64",
    "keystore_password": "ANDROID_RELEASE_KEYSTORE_PASSWORD",
    "key_alias": "ANDROID_RELEASE_KEY_ALIAS",
    "key_password": "ANDROID_RELEASE_KEY_PASSWORD",
}

ROLE_DESCRIPTIONS = {
    "keystore_base64": "The keystore file, base64-encoded",
    "keystore_password": "The keystore password",
    "key_alias": "The key alias inside the keystore",
    "key_password": "The key password",
}

MAX_SUFFIX = 9999
_NAME_RE = re.compile(r"[A-Z_][A-Z0-9_]*")


def validate_suffix(value) -> str:
    """Return an error message, or '' if `value` is a valid suffix."""
    if isinstance(value, bool):
        return "The suffix must be a whole number."
    if isinstance(value, str):
        if not value.strip().isdigit():
            return "The suffix must be a whole number such as 2."
        value = int(value.strip())
    if not isinstance(value, int):
        return "The suffix must be a whole number."
    if value < 1:
        return "The suffix must be a positive number (1 or more)."
    if value > MAX_SUFFIX:
        return f"The suffix must be {MAX_SUFFIX} or less."
    return ""


def validate_secret_name(name: str) -> str:
    """GitHub rules: letters, digits, underscore; not starting with a digit; no GITHUB_ prefix."""
    if not name:
        return "Secret names cannot be empty."
    if not _NAME_RE.fullmatch(name):
        return f"{name!r} may only contain A–Z, 0–9 and _ and must not start with a digit."
    if name.startswith("GITHUB_"):
        return f"{name!r} must not start with GITHUB_."
    return ""


def secret_names(use_suffix: bool = False, suffix: int = 2) -> dict:
    """Return {role: final secret name}. Raises ValueError for an invalid suffix."""
    if not use_suffix:
        return dict(DEFAULT_NAMES)
    err = validate_suffix(suffix)
    if err:
        raise ValueError(err)
    names = {role: f"{base}_{int(suffix)}" for role, base in DEFAULT_NAMES.items()}
    for name in names.values():
        err = validate_secret_name(name)
        if err:
            raise ValueError(err)
    return names


def custom_names(mapping: dict) -> dict:
    """Validate an owner-chosen role -> secret name mapping. Raises ValueError with a plain message."""
    missing = [r for r in ROLES if not str(mapping.get(r, "")).strip()]
    if missing:
        raise ValueError("Enter a secret name for every role (missing: " + ", ".join(missing) + ").")
    names = {r: str(mapping[r]).strip() for r in ROLES}
    for name in names.values():
        err = validate_secret_name(name)
        if err:
            raise ValueError(err)
    if len(set(names.values())) != len(names):
        raise ValueError("Each secret needs its own name; two roles use the same name.")
    return names


def names_for_profile(profile) -> dict:
    v = getattr(profile, "v11", None)
    if v is not None and v.secret_mode in ("custom", "workflow"):
        return custom_names(v.secret_custom)
    return secret_names(profile.secret_use_suffix, profile.secret_suffix)
