import pytest

from hag_bsm.model import PLATFORMS, Profile
from hag_bsm.prompt import artifact_names, generate_prompt

FP = "AB:CD:" + ":".join(["01"] * 30)


def profile(*platforms, **kw):
    p = Profile(name="Backrooms Survivor", version="1.2.3", build_number=15,
                android_package="com.hotatticgames.backroomssurvivor",
                apple_bundle_id="com.hotatticgames.backroomssurvivor.ios", **kw)
    for k in platforms:
        p.platforms[k]["enabled"] = True
    return p


def test_android_only_prompt_contents():
    p = profile("android")
    p.platforms["android"]["formats"] = ["apk", "aab"]
    p.stores = ["google_play"]
    text = generate_prompt(p, {"alias": "backroomssurvivor_release", "fingerprint_sha256": FP})
    for needle in ["Backrooms Survivor", "Hot Attic Games", "1.2.3", "Build number:     15",
                   "com.hotatticgames.backroomssurvivor", "ANDROID_RELEASE_KEYSTORE_BASE64",
                   "ANDROID_RELEASE_KEY_PASSWORD", FP, "Google Play", "backroomssurvivor-1.2.3-b15-android.apk",
                   "backroomssurvivor-1.2.3-b15-android.aab", "Private Testing", "Never publish"]:
        assert needle in text, needle
    assert "macOS" not in text and "iOS" not in text and "Authenticode" not in text
    assert "backroomssurvivor_release" not in text  # alias value is a secret value, not needed in the prompt


def test_windows_only_has_no_android_or_apple_sections():
    text = generate_prompt(profile("windows"))
    assert "ANDROID" not in text
    assert "android keystore" not in text.lower() and "keystore_" not in text.lower()
    assert "Apple" not in text
    assert "Authenticode" in text
    assert "backroomssurvivor-1.2.3-b15-windows.exe" in text


def test_apple_only():
    text = generate_prompt(profile("ios", "macos"))
    assert "provisioning profile" in text and "notarization" in text
    assert "com.hotatticgames.backroomssurvivor.ios" in text
    assert "ANDROID_RELEASE" not in text


@pytest.mark.parametrize("key", [p.key for p in PLATFORMS])
def test_single_platform_prompts_only_mention_selected_artifacts(key):
    text = generate_prompt(profile(key))
    for other in PLATFORMS:
        token = f"-b15-{other.key}."
        assert (token in text) == (other.key == key)


def test_mixed_platforms_with_suffix():
    p = profile("android", "windows", "linux")
    p.secret_use_suffix, p.secret_suffix = True, 3
    text = generate_prompt(p)
    assert "ANDROID_RELEASE_KEYSTORE_PASSWORD_3" in text
    assert "ANDROID_RELEASE_KEYSTORE_PASSWORD\n" not in text
    assert "not yet recorded" in text
    assert len(artifact_names(p)) == 3


def test_prompt_never_contains_secret_values(vault, keytool_tools):
    p = profile("android")
    rec = vault.generate(keytool_tools, "Backrooms Survivor", "bs_release", "bs-release.jks", "CN=Hot Attic Games")
    p.android_identity_id = rec.id
    text = generate_prompt(p, rec.public_summary())
    creds = vault.credentials(rec.id)
    assert creds.store_password not in text
    assert vault.keystore_base64(rec.id)[:40] not in text
    assert rec.fingerprint_sha256 in text


def test_channel_rules():
    for channel, phrase in [("private_testing", "PRIVATE TESTING"), ("beta", "BETA"), ("production", "PRODUCTION")]:
        assert phrase in generate_prompt(profile("web", release_channel=channel))


def test_no_publishing_instructions():
    text = generate_prompt(profile(*[p.key for p in PLATFORMS])).lower()
    assert "do not publish without owner authorization" in text
    assert "upload to the store" not in text
