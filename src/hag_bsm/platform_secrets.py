"""Suggested GitHub secret and variable names for Google Play upload signing and Apple signing.

The existing four Android signing names (secret_names.py) are untouched. Public fingerprints and the Team ID are not
secrets; they are listed as repository VARIABLES so that nobody pastes private material into a public place by mistake.
"""

from .secret_names import ROLES, names_for_profile
from .playsigning import SHARED, relation

PLAY_UPLOAD_NAMES = {
    "keystore_base64": "PLAY_UPLOAD_KEYSTORE_BASE64",
    "keystore_password": "PLAY_UPLOAD_KEYSTORE_PASSWORD",
    "key_alias": "PLAY_UPLOAD_KEY_ALIAS",
    "key_password": "PLAY_UPLOAD_KEY_PASSWORD",
}

SECRET, VARIABLE = "secret", "variable"


def play_upload_names(p, direct_rec=None, upload_rec=None) -> dict:
    """The upload key reuses the project's existing Android secrets when it is the same key; otherwise PLAY_UPLOAD_*."""
    if upload_rec is not None and relation(upload_rec, direct_rec) == SHARED:
        return names_for_profile(p)
    return dict(PLAY_UPLOAD_NAMES)


def apple_suggestions(p) -> list:
    """[(name, kind, description)] for the selected Apple platforms. Names only: this application stores no Apple private keys."""
    if not any(p.is_enabled(k) for k in ("ios", "macos")):
        return []
    rows = [("APPLE_TEAM_ID", VARIABLE, "Your 10-character Apple Team ID (public, not a secret)."),
            ("APPLE_CERTIFICATE_P12_BASE64", SECRET, "The signing certificate with its private key as a P12 file, base64-encoded."),
            ("APPLE_CERTIFICATE_PASSWORD", SECRET, "The password of that P12 file."),
            ("APPLE_KEYCHAIN_PASSWORD", SECRET, "A throw-away password for the temporary keychain created on the macOS runner.")]
    if p.is_enabled("ios") or "app_store" in p.stores:
        rows.append(("APPLE_PROVISIONING_PROFILE_BASE64", SECRET, "The provisioning profile for the bundle identifier, base64-encoded."))
    if "app_store" in p.stores or p.is_enabled("macos"):
        rows += [("APP_STORE_CONNECT_KEY_ID", VARIABLE, "App Store Connect API key ID (used for notarization or uploads the owner approves)."),
                 ("APP_STORE_CONNECT_ISSUER_ID", VARIABLE, "App Store Connect issuer ID."),
                 ("APP_STORE_CONNECT_PRIVATE_KEY", SECRET, "The App Store Connect API private key (.p8 contents).")]
    return rows
