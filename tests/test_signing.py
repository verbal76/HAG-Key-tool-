"""Signing tests use the real keytool (and apksigner when the Android SDK is installed)."""

import base64
import hashlib
import json
import logging

import pytest

from conftest import TEST_SCRYPT_N, jarsign, make_keystore, make_unsigned_apk
from hag_bsm import android, backup
from hag_bsm.redact import RedactingFormatter
from hag_bsm.tools import AndroidTools
from hag_bsm.vault import VaultError


def test_generate_identity_is_real_and_unique(vault, keytool_tools):
    a = vault.generate(keytool_tools, "Game A", "a_release", "a-release.jks", android.build_dname("Hot Attic Games"))
    b = vault.generate(keytool_tools, "Game B", "b_release", "b-release.jks", android.build_dname("Hot Attic Games"))
    assert a.fingerprint_sha256 != b.fingerprint_sha256
    assert a.key_algorithm == "RSA" and a.key_size == 4096
    assert a.store_type == "PKCS12"
    creds = vault.credentials(a.id)
    assert creds.store_password == creds.key_password and len(creds.store_password) >= 32
    # Independently re-read the certificate from the stored keystore.
    cert = android.read_certificate(keytool_tools, vault.keystore_path(a.id), creds.store_password, "a_release")
    assert cert.sha256 == a.fingerprint_sha256
    # Base64 value decodes to the exact keystore bytes.
    assert base64.b64decode(vault.keystore_base64(a.id)) == vault.keystore_path(a.id).read_bytes()


def test_credentials_not_in_plaintext_metadata(vault, keytool_tools):
    rec = vault.generate(keytool_tools, "Game", "g_release", "g-release.jks", "CN=Test")
    creds = vault.credentials(rec.id)
    folder = vault.folder(rec.id)
    assert creds.store_password not in (folder / "identity.json").read_text()
    assert creds.store_password.encode() not in (folder / "credentials.bin").read_bytes()


def test_generate_refuses_to_overwrite(keytool_tools, tmp_path):
    dest = tmp_path / "existing.jks"
    dest.write_bytes(b"precious")
    with pytest.raises(android.SigningError) as exc:
        android.generate_keystore(keytool_tools, dest, "x", "password123", "CN=x")
    assert exc.value.kind == "exists"
    assert dest.read_bytes() == b"precious"


def test_generation_failure_leaves_no_identity(vault, keytool_tools):
    with pytest.raises(android.SigningError):
        vault.generate(keytool_tools, "Game", "alias", "x.jks", "not a valid dname ===")
    assert vault.list() == []


def test_import_existing_keystore_and_multiple_aliases(vault, keytool_tools, tmp_path):
    ks = make_keystore(keytool_tools, tmp_path / "my keys.jks", "first", "storepass1", "JKS", key_password="keypass11")
    make_keystore(keytool_tools, ks, "second", "storepass1", "JKS", key_password="keypass22")
    original = ks.read_bytes()
    aliases = android.list_aliases(keytool_tools, ks, "storepass1")
    assert [a.alias for a in aliases] == ["first", "second"] or {a.alias for a in aliases} == {"first", "second"}
    with pytest.raises(android.SigningError) as exc:
        vault.import_keystore(keytool_tools, ks, "storepass1", "second", "wrongkeypass")
    assert exc.value.kind == "bad_key_password"
    rec = vault.import_keystore(keytool_tools, ks, "storepass1", "second", "keypass22", "Imported Game")
    assert rec.alias == "second" and rec.store_type == "JKS" and not rec.key_password_matches_store
    assert ks.read_bytes() == original  # original untouched
    assert vault.credentials(rec.id).key_password == "keypass22"


def test_reject_wrong_password_and_invalid_file(vault, keytool_tools, tmp_path):
    ks = make_keystore(keytool_tools, tmp_path / "k.p12", "k", "rightpass1")
    with pytest.raises(android.SigningError) as exc:
        android.list_aliases(keytool_tools, ks, "wrongpass1")
    assert exc.value.kind == "bad_password"
    junk = tmp_path / "junk.jks"
    junk.write_bytes(b"this is not a keystore")
    with pytest.raises(android.SigningError) as exc:
        vault.import_keystore(keytool_tools, junk, "whatever1", "k", "whatever1")
    assert exc.value.kind in ("not_keystore", "bad_password")
    assert vault.list() == []


def test_missing_tool_reported():
    with pytest.raises(android.SigningError) as exc:
        android.list_aliases(AndroidTools(), "x.jks", "pw")
    assert exc.value.kind == "tool_missing"
    insp = android.inspect_apk(AndroidTools(), __file__)
    assert insp.status in (android.APK_INVALID, android.APK_TOOL_MISSING)


def test_vault_rejects_bad_alias_and_filename(vault, keytool_tools):
    with pytest.raises(VaultError):
        vault.generate(keytool_tools, "G", "bad alias!", "ok.jks", "CN=x")
    with pytest.raises(VaultError):
        vault.generate(keytool_tools, "G", "ok", "..\\evil.jks", "CN=x")


def test_dname_escaping():
    assert android.build_dname("Hot Attic Games, LLC", country="us") == "CN=Hot Attic Games\\, LLC, C=US"
    with pytest.raises(ValueError):
        android.build_dname("")


# --- APK inspection --------------------------------------------------------------

def test_apk_v1_certificate_and_comparison(vault, keytool_tools, tmp_path):
    rec = vault.generate(keytool_tools, "Game", "g_release", "g.jks", "CN=Game")
    creds = vault.credentials(rec.id)
    apk = make_unsigned_apk(tmp_path / "game build.apk")
    jarsign(keytool_tools, apk, vault.keystore_path(rec.id), creds.store_password, "g_release")
    tools = AndroidTools(keytool=keytool_tools.keytool, java=keytool_tools.java)  # keytool fallback path
    insp = android.inspect_apk(tools, apk)
    assert insp.status == android.APK_CERT_ONLY
    assert insp.signer_sha256 == [rec.fingerprint_sha256]
    cmp = android.compare_apk(insp, rec.fingerprint_sha256)
    assert cmp.result == android.CMP_MATCH_UNVERIFIED  # never a full match without verification

    other = vault.generate(keytool_tools, "Other", "o_release", "o.jks", "CN=Other")
    assert android.compare_apk(insp, other.fingerprint_sha256).result == android.CMP_MISMATCH


def test_invalid_apk(keytool_tools, tmp_path):
    bad = tmp_path / "bad.apk"
    bad.write_bytes(b"not a zip")
    assert android.inspect_apk(keytool_tools, bad).status == android.APK_INVALID
    unsigned = make_unsigned_apk(tmp_path / "unsigned.apk")
    insp = android.inspect_apk(keytool_tools, unsigned)
    assert insp.status in (android.APK_INVALID, android.APK_TOOL_MISSING, android.APK_UNDETERMINED)
    assert android.compare_apk(insp, "AA").result != android.CMP_MATCH


def test_apksigner_output_parsing():
    ok = ("Verifies\nVerified using v1 scheme (JAR signing): false\n"
          "Verified using v2 scheme (APK Signature Scheme v2): true\n"
          "Number of signers: 1\nSigner #1 certificate DN: CN=x\n"
          "Signer #1 certificate SHA-256 digest: " + "ab" * 32 + "\n")
    insp = android._parse_apksigner(0, ok, "")
    assert insp.status == android.APK_VERIFIED and insp.schemes == {"v1": False, "v2": True}
    assert android.normalize_fingerprint(insp.signer_sha256[0]) == "AB" * 32
    assert android.compare_apk(insp, ":".join(["AB"] * 32)).result == android.CMP_MATCH
    # build-tools 37 format
    new = ("Verifies\nVerified using v1 scheme (JAR signing): false\n"
           "Verified using v2 scheme (APK Signature Scheme v2): true\n"
           "Verified using v3 scheme (APK Signature Scheme v3): true\n"
           "Verified using v3.1 scheme (APK Signature Scheme v3.1): false\n"
           "Number of signers: 1\nV3.0 Signer: certificate DN: CN=x\n"
           "V3.0 Signer: certificate SHA-256 digest: " + "cd" * 32 + "\n"
           "V3.0 Signer: public key SHA-256 digest: " + "ef" * 32 + "\n")
    insp = android._parse_apksigner(0, new, "")
    assert insp.status == android.APK_VERIFIED and not insp.rotation_detected
    assert [android.normalize_fingerprint(f) for f in insp.signer_sha256] == ["CD" * 32]
    lineage = ok + "Signer #1 lineage certificate SHA-256 digest: " + "11" * 32 + "\n"
    assert len(android._parse_apksigner(0, lineage, "").signer_sha256) == 1
    bad = android._parse_apksigner(1, "DOES NOT VERIFY\nERROR: APK Signature Scheme v2 signer #1: digest mismatch", "")
    assert bad.status == android.APK_INVALID
    assert android.compare_apk(bad, "AB").result == android.CMP_INVALID


# --- backups ---------------------------------------------------------------------

def test_backup_verify_and_restore(vault, keytool_tools, tmp_path, paths):
    rec = vault.generate(keytool_tools, "Game", "g_release", "g.jks", "CN=Game")
    dest = tmp_path / "backups with space" / "game.hagbackup"
    result = backup.create_backup(vault, rec.id, dest, "correct horse battery", keytool_tools, scrypt_n=TEST_SCRYPT_N)
    assert result.ok and result.tool_checked, result.message
    assert vault.get(rec.id).has_verified_backup

    raw = dest.read_bytes()
    creds = vault.credentials(rec.id)
    assert creds.store_password.encode() not in raw
    assert vault.keystore_path(rec.id).read_bytes() not in raw

    # Never overwrite an existing backup.
    with pytest.raises(backup.BackupError):
        backup.create_backup(vault, rec.id, dest, "correct horse battery", keytool_tools, scrypt_n=TEST_SCRYPT_N)
    assert dest.read_bytes() == raw

    assert not backup.verify_backup(dest, "wrong passphrase!!", keytool_tools).ok
    tampered = tmp_path / "tampered.hagbackup"
    tampered.write_bytes(raw[:-5] + bytes(b ^ 1 for b in raw[-5:]))
    assert not backup.verify_backup(tampered, "correct horse battery", keytool_tools).ok

    # Same identity already present: no duplicate.
    same, created = backup.restore_backup(vault, dest, "correct horse battery", keytool_tools)
    assert not created and same.id == rec.id

    # Restore into a fresh vault (e.g. a new PC).
    from hag_bsm.vault import IdentityVault
    fresh = IdentityVault(tmp_path / "newpc" / "identities", tmp_path / "newpc")
    restored, created = backup.restore_backup(fresh, dest, "correct horse battery", keytool_tools)
    assert created and restored.fingerprint_sha256 == rec.fingerprint_sha256
    assert fresh.credentials(restored.id).store_password == creds.store_password
    assert hashlib.sha256(fresh.keystore_path(restored.id).read_bytes()).digest() == \
        hashlib.sha256(vault.keystore_path(rec.id).read_bytes()).digest()


def test_backup_requires_strong_passphrase(vault, keytool_tools, tmp_path):
    rec = vault.generate(keytool_tools, "Game", "g_release", "g.jks", "CN=Game")
    with pytest.raises(backup.BackupError):
        backup.create_backup(vault, rec.id, tmp_path / "b.hagbackup", "short", keytool_tools)
    assert not (tmp_path / "b.hagbackup").exists()


def test_standalone_decryptor(vault, keytool_tools, tmp_path):
    import subprocess, sys
    from pathlib import Path
    rec = vault.generate(keytool_tools, "Game", "g_release", "g.jks", "CN=Game")
    dest = tmp_path / "b.hagbackup"
    backup.create_backup(vault, rec.id, dest, "correct horse battery", keytool_tools, scrypt_n=TEST_SCRYPT_N)
    script = Path(__file__).resolve().parents[1] / "tools" / "decrypt_backup.py"
    out = tmp_path / "out"
    res = subprocess.run([sys.executable, "-I", str(script), str(dest), str(out)],
                         input="correct horse battery\n", capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert (out / "keystore" / "g.jks").read_bytes() == vault.keystore_path(rec.id).read_bytes()
    assert json.loads((out / "credentials.json").read_text())["key_alias"] == "g_release"


def test_secrets_never_logged(vault, keytool_tools, tmp_path, caplog):
    rec = vault.generate(keytool_tools, "Game", "g_release", "g.jks", "CN=Game")
    creds = vault.credentials(rec.id)
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "oops %s", (creds.store_password,), None)
    assert creds.store_password not in RedactingFormatter("%(message)s").format(record)
