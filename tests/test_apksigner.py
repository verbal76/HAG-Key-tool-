"""End-to-end APK verification with the real Android SDK (runs where build-tools are installed, e.g. CI).

Builds a minimal real APK with aapt2, signs it with apksigner using a vault identity, then checks
that inspection verifies the signature, detects a different signer, and rejects a tampered file.
"""

import glob
import os
import subprocess
from pathlib import Path

import pytest

from hag_bsm import android

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.hotatticgames.citest" android:versionCode="1" android:versionName="1.0">
    <uses-sdk android:minSdkVersion="24" android:targetSdkVersion="34" />
    <application android:hasCode="false" android:label="CI Test" />
</manifest>
"""


@pytest.fixture
def sdk(keytool_tools):
    if not keytool_tools.has_apksigner:
        pytest.skip("apksigner (Android SDK build-tools) not available")
    build_tools = Path(keytool_tools.apksigner_jar).parent.parent
    aapt2 = build_tools / ("aapt2.exe" if os.name == "nt" else "aapt2")
    sdk_root = build_tools.parent.parent
    jars = sorted(glob.glob(str(sdk_root / "platforms" / "android-*" / "android.jar")))
    if not aapt2.is_file() or not jars:
        pytest.skip("aapt2 or an Android platform is not installed")
    return keytool_tools, aapt2, Path(jars[-1])


def build_apk(aapt2, android_jar, tmp_path) -> Path:
    manifest = tmp_path / "AndroidManifest.xml"
    manifest.write_text(MANIFEST, encoding="utf-8")
    out = tmp_path / "unsigned.apk"
    res = subprocess.run([str(aapt2), "link", "-o", str(out), "-I", str(android_jar), "--manifest", str(manifest)],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return out


def sign(tools, vault, rec, src, dest):
    creds = vault.credentials(rec.id)
    res = subprocess.run([str(tools.java), "-jar", str(tools.apksigner_jar), "sign",
                          "--ks", str(vault.keystore_path(rec.id)), "--ks-pass", "env:HAGBSM_T_SP",
                          "--key-pass", "env:HAGBSM_T_KP", "--ks-key-alias", rec.alias,
                          "--out", str(dest), str(src)],
                         env=dict(os.environ, HAGBSM_T_SP=creds.store_password, HAGBSM_T_KP=creds.key_password),
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    return dest


def test_real_apk_verification(sdk, vault, tmp_path):
    tools, aapt2, android_jar = sdk
    rec = vault.generate(tools, "CI Game", "ci_release", "ci.jks", "CN=Hot Attic Games")
    other = vault.generate(tools, "Other Game", "other_release", "other.jks", "CN=Someone Else")
    unsigned = build_apk(aapt2, android_jar, tmp_path)
    signed = sign(tools, vault, rec, unsigned, tmp_path / "signed.apk")

    insp = android.inspect_apk(tools, signed)
    assert insp.status == android.APK_VERIFIED, insp.detail
    assert [android.normalize_fingerprint(f) for f in insp.signer_sha256] == \
        [android.normalize_fingerprint(rec.fingerprint_sha256)]
    assert android.compare_apk(insp, rec.fingerprint_sha256).result == android.CMP_MATCH
    assert android.compare_apk(insp, other.fingerprint_sha256).result == android.CMP_MISMATCH

    data = bytearray(signed.read_bytes())
    data[100] ^= 0xFF   # corrupt signed content near the start of the archive
    tampered = tmp_path / "tampered.apk"
    tampered.write_bytes(bytes(data))
    bad = android.inspect_apk(tools, tampered)
    assert bad.status in (android.APK_INVALID, android.APK_UNDETERMINED)
    assert android.compare_apk(bad, rec.fingerprint_sha256).result != android.CMP_MATCH

    assert android.inspect_apk(tools, unsigned).status in (android.APK_INVALID, android.APK_UNDETERMINED)
