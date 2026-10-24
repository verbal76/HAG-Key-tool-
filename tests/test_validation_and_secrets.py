import struct
import zlib

import pytest

from hag_bsm.model import PLATFORMS, Profile
from hag_bsm.secret_names import DEFAULT_NAMES, secret_names, validate_secret_name, validate_suffix
from hag_bsm.validation import (ERROR, WARNING, has_errors, validate_android_package, validate_bundle_id,
                                validate_profile, validate_version)


def profile(*platforms, **kw):
    p = Profile(name="Game", android_package="com.hotatticgames.game", apple_bundle_id="com.hotatticgames.game", **kw)
    for k in platforms:
        p.platforms[k]["enabled"] = True
    p.stores = ["private"]
    return p


# --- secret names -----------------------------------------------------------------

def test_default_secret_names():
    assert secret_names() == {
        "keystore_base64": "ANDROID_RELEASE_KEYSTORE_BASE64",
        "keystore_password": "ANDROID_RELEASE_KEYSTORE_PASSWORD",
        "key_alias": "ANDROID_RELEASE_KEY_ALIAS",
        "key_password": "ANDROID_RELEASE_KEY_PASSWORD",
    }


@pytest.mark.parametrize("n", [2, 3])
def test_suffix_applied_consistently(n):
    names = secret_names(True, n)
    assert set(names.values()) == {f"{v}_{n}" for v in DEFAULT_NAMES.values()}
    assert all(validate_secret_name(v) == "" for v in names.values())


@pytest.mark.parametrize("bad", [0, -1, "abc", "", "2.5", True, 10000])
def test_invalid_suffix(bad):
    assert validate_suffix(bad)
    if not isinstance(bad, str):
        with pytest.raises(ValueError):
            secret_names(True, bad)


def test_secret_name_rules():
    assert validate_secret_name("GITHUB_TOKEN")
    assert validate_secret_name("1ABC")
    assert validate_secret_name("lower")
    assert not validate_secret_name("ANDROID_RELEASE_KEY_ALIAS_2")


# --- identifiers and versions ------------------------------------------------------------

def test_android_package_rules():
    assert not validate_android_package("com.hotatticgames.backroomssurvivor")
    assert validate_android_package("backrooms")
    assert validate_android_package("com.1game.x")
    assert validate_android_package("com.class.game")
    assert validate_android_package("com.hot-attic.game")


def test_bundle_id_rules():
    assert not validate_bundle_id("com.hotatticgames.backrooms-survivor")
    assert validate_bundle_id("com.hot_attic.game")
    assert validate_bundle_id("single")


def test_version_rules():
    assert not validate_version("1.0.0", [])
    assert validate_version("1.0.0.0", ["ios"])
    assert not validate_version("1.0.0.0", ["android"])
    assert validate_version("1.70000", ["windows"])
    assert validate_version("v1", [])
    assert validate_version("1.02", [])


# --- profile combinations ----------------------------------------------------------------

@pytest.mark.parametrize("plats", [
    ("android",), ("windows",), ("linux",), ("macos",), ("ios",), ("web",),
    ("android", "windows", "linux"), tuple(p.key for p in PLATFORMS),
])
def test_valid_platform_combinations(plats):
    assert not has_errors(validate_profile(profile(*plats)))


def test_no_platforms_is_error():
    issues = validate_profile(profile())
    assert any(i.level == ERROR and i.field == "platforms" for i in issues)


def test_platform_without_formats_is_error():
    p = profile("android")
    p.platforms["android"]["formats"] = []
    assert any(i.field == "formats.android" and i.level == ERROR for i in validate_profile(p))


def test_android_requires_package_but_windows_does_not():
    p = profile("windows")
    p.android_package = ""
    assert not has_errors(validate_profile(p))
    p.platforms["android"]["enabled"] = True
    assert any(i.field == "android_package" for i in validate_profile(p))


def test_store_consistency_warnings():
    p = profile("windows")
    p.stores = ["google_play", "private"]
    msgs = [i for i in validate_profile(p) if i.level == WARNING]
    assert any("Google Play" in i.message for i in msgs)
    assert any("together" in i.message for i in msgs)


def test_missing_identity_in_vault_is_error():
    p = profile("android")
    p.android_identity_id = "a" * 32
    assert any(i.field == "signing" and i.level == ERROR for i in validate_profile(p, lambda _: False))


def _png(path, w, h):
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def test_icon_validation(tmp_path):
    p = profile("ios")
    p.icon_path = str(tmp_path / "missing.png")
    assert any(i.field == "icon_path" and i.level == ERROR for i in validate_profile(p))
    p.icon_path = str(_png(tmp_path / "small icon.png", 64, 32))
    msgs = [i.message for i in validate_profile(p) if i.field == "icon_path"]
    assert any("square" in m for m in msgs) and any("1024" in m for m in msgs)
    p.icon_path = str(_png(tmp_path / "good.png", 1024, 1024))
    assert not [i for i in validate_profile(p) if i.field == "icon_path"]
