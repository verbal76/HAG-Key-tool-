"""Google Play / Apple expansion: core (Qt-free) behaviour. Temporary test credentials only."""

import hashlib
import json
import plistlib
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from cryptography.x509.oid import NameOID

from hag_bsm import android, apple, backup, playsigning
from hag_bsm.model import Profile
from hag_bsm.platform_secrets import PLAY_UPLOAD_NAMES, play_upload_names
from hag_bsm.prompt import generate_prompt
from hag_bsm.validation import validate_profile

TEST_PW = "Tmp-Test-Passw0rd-xyz"


def play_profile(**kw):
    p = Profile(name="Play Test", android_package="com.test.playtest", **kw)
    p.platforms["android"].update(enabled=True, formats=["aab"])
    p.stores = ["google_play"]
    return p


def make_cert(cn, ou, days=365, start=None):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn), x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, ou),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test Org")])
    start = start or datetime.now(timezone.utc) - timedelta(days=1)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(start)
            .not_valid_after(start + timedelta(days=days)).sign(key, hashes.SHA256()))
    return key, cert


def make_profile_file(cert, bundle="com.test.app", team="ABCDE12345", kind="app_store", days=200):
    ent = {"application-identifier": f"{team}.{bundle}", "com.apple.developer.team-identifier": team,
           "aps-environment": "production", "get-task-allow": kind == "development"}
    pl = {"UUID": "11111111-2222-3333-4444-555555555555", "Name": "Test Profile", "TeamIdentifier": [team],
          "ApplicationIdentifierPrefix": [team], "Platform": ["iOS"], "Entitlements": ent,
          "CreationDate": datetime.now(timezone.utc) - timedelta(days=1),
          "ExpirationDate": datetime.now(timezone.utc) + timedelta(days=days),
          "DeveloperCertificates": [cert.public_bytes(Encoding.DER)]}
    if kind in ("development", "ad_hoc"):
        pl["ProvisionedDevices"] = ["00008030-000000000000002E"]
    return b"\x30\x82\x01\x00cms-garbage\x00" + plistlib.dumps(pl) + b"\x00trailer-signature"


# --- fingerprints ------------------------------------------------------------------------------

def test_fingerprint_input_normalisation_and_validation():
    raw = "ab" * 32
    assert playsigning.normalize_fingerprint_input("SHA256: " + raw, 32) == ":".join(["AB"] * 32)
    assert playsigning.normalize_fingerprint_input(":".join(["ab"] * 20), 20) == ":".join(["AB"] * 20)
    assert playsigning.validate_fingerprint("", 32) == ""
    assert "hex digits" in playsigning.validate_fingerprint("ab" * 31, 32)
    assert "0-9" in playsigning.validate_fingerprint("zz" * 32, 32)


def test_certificate_fingerprints_match_independent_hashes():
    _, cert = make_cert("Some Cert", "TEAM")
    der = cert.public_bytes(Encoding.DER)
    s256, s1, _ = playsigning.certificate_fingerprints(cert.public_bytes(Encoding.PEM).decode())
    assert s256.replace(":", "").lower() == hashlib.sha256(der).hexdigest()
    assert s1.replace(":", "").lower() == hashlib.sha1(der).hexdigest()
    assert playsigning.certificate_fingerprints(der)[0] == s256
    with pytest.raises(ValueError):
        playsigning.certificate_fingerprints(b"not a certificate")


# --- upload key: generate / import / PEM / separation / preservation -----------------------------------

def test_upload_key_generate_pem_and_separation(vault, keytool_tools):
    direct = vault.generate(keytool_tools, "Play Test", "direct", "d.jks", "CN=Direct")
    before = (vault.dir / direct.id / "d.jks").read_bytes()
    upload = vault.generate(keytool_tools, "Play Test", "upload", "u.jks", "CN=Upload", role="upload")
    assert upload.label.endswith("upload key") and upload.id != direct.id
    assert upload.fingerprint_sha256 != direct.fingerprint_sha256
    assert (vault.dir / direct.id / "d.jks").read_bytes() == before        # existing identity untouched

    creds = vault.credentials(upload.id)
    pem = android.export_certificate_pem(keytool_tools, vault.keystore_path(upload.id), creds.store_password, upload.alias)
    assert pem.startswith("-----BEGIN CERTIFICATE-----") and "PRIVATE" not in pem
    s256, s1, _ = playsigning.certificate_fingerprints(pem)
    assert (s256, s1) == (upload.fingerprint_sha256, upload.fingerprint_sha1)
    assert len(upload.fingerprint_sha1.split(":")) == 20 and len(upload.fingerprint_sha256.split(":")) == 32

    assert playsigning.relation(upload, direct) == playsigning.SEPARATE
    assert playsigning.relation(direct, direct) == playsigning.SHARED
    assert playsigning.relation(None, direct) == playsigning.NO_UPLOAD


def test_upload_key_import_and_existing_preserved(vault, keytool_tools, tmp_path):
    from conftest import make_keystore
    ks = tmp_path / "up.p12"
    make_keystore(keytool_tools, str(ks), "upalias", TEST_PW)
    rec = vault.import_keystore(keytool_tools, ks, TEST_PW, "upalias", TEST_PW, "Play Test", label="Play Test upload key")
    assert rec.label == "Play Test upload key" and rec.store_type == "PKCS12"
    assert vault.find_by_fingerprint(rec.fingerprint_sha256)[0].id == rec.id
    with pytest.raises(android.SigningError):
        vault.import_keystore(keytool_tools, ks, TEST_PW, "wrong-alias", TEST_PW)
    with pytest.raises(android.SigningError):
        vault.import_keystore(keytool_tools, ks, "bad-password-123", "upalias", "bad-password-123")


def test_backup_failures_leave_vault_unchanged(vault, keytool_tools, tmp_path):
    up = vault.generate(keytool_tools, "Play Test", "upload", "u.jks", "CN=Upload", role="upload")
    dest = tmp_path / "up.hagbackup"
    res = backup.create_backup(vault, up.id, dest, "a long enough passphrase 1", keytool_tools)
    assert res.ok
    count = len(vault.list())
    with pytest.raises(backup.BackupError):
        backup.open_backup(dest, "the wrong passphrase!!")
    bad = backup.verify_backup(dest, "the wrong passphrase!!", keytool_tools, up.fingerprint_sha256)
    assert not bad.ok
    corrupt = tmp_path / "corrupt.hagbackup"
    data = bytearray(dest.read_bytes())
    data[-5] ^= 0xFF
    corrupt.write_bytes(bytes(data))
    assert not backup.verify_backup(corrupt, "a long enough passphrase 1", keytool_tools).ok
    with pytest.raises(backup.BackupError):
        backup.restore_backup(vault, corrupt, "a long enough passphrase 1", keytool_tools, "x")
    assert len(vault.list()) == count


# --- Google Play checks -------------------------------------------------------------------------

class Rec:
    def __init__(self, sha256, not_after="2060-01-01T00:00:00+00:00", label="up", rid="a" * 32):
        self.fingerprint_sha256, self.fingerprint_sha1, self.not_after, self.label, self.id = sha256, "11:22", not_after, label, rid


def fp(n):
    return ":".join([f"{n:02X}"] * 32)


def test_play_checks_distinguish_roles_and_never_claim_verification():
    p = play_profile()
    titles = {c.title: c for c in playsigning.play_checks(p)}
    assert titles["Upload signing key"].status == "fail"
    up, direct = Rec(fp(1)), Rec(fp(2), rid="b" * 32)
    p.v11.play_upload_identity_id = up.id
    p.v11.play_signing_sha256 = fp(1)                       # Google's key pasted equal to the upload key
    p.v11.play_console_upload_sha256 = fp(9)                # does not match the local upload key
    texts = {c.title: c for c in playsigning.play_checks(p, direct, up)}
    assert texts["Play Console upload certificate"].status == "fail"
    assert texts["App-signing and upload certificates"].status == "warn"
    assert "not verified" in texts["Google Play app-signing certificate"].detail
    assert "SEPARATE" not in texts["Upload key and direct APK key"].detail and "different" in texts["Upload key and direct APK key"].detail
    assert "cannot check" in texts["Play App Signing enrollment"].detail


def test_play_checks_aab_validity_and_inapplicable_profiles():
    p = play_profile()
    p.platforms["android"]["formats"] = ["apk"]
    old = Rec(fp(1), not_after="2020-01-01T00:00:00+00:00")
    p.v11.play_upload_identity_id = old.id
    res = {c.title: c for c in playsigning.play_checks(p, None, old)}
    assert res["Artifact format"].status == "warn" and res["Upload certificate validity"].status == "fail"
    p.stores = ["private"]
    assert playsigning.play_checks(p) == []


def test_signer_classification_mismatch_detection():
    p = play_profile()
    p.v11.play_signing_sha256 = fp(3)
    direct, up = Rec(fp(1)), Rec(fp(2))
    assert playsigning.classify_signer([fp(1)], direct, up, p) == ["direct APK signing key"]
    assert "Google Play app-signing" in playsigning.classify_signer([fp(3)], direct, up, p)[0]
    assert playsigning.classify_signer([fp(7)], direct, up, p) == []


def test_new_fields_validated():
    p = play_profile()
    p.v11.play_signing_sha256 = "12:34"
    p.v11.apple_team_id = "short"
    fields = {i.field for i in validate_profile(p)}
    assert {"play_signing_sha256", "apple_team_id"} <= fields


# --- Apple ------------------------------------------------------------------------------------------

def test_team_id_and_bundle_identifier_rules():
    assert apple.validate_team_id("ABCDE12345") == "" and apple.validate_team_id("abcde12345") != ""
    from hag_bsm.identifiers import propose_identifiers
    from hag_bsm.validation import validate_bundle_id
    sug = propose_identifiers("Hot Attic Games", "Backrooms Survivor")["apple"]
    assert sug == "com.hotatticgames.backroomssurvivor" and validate_bundle_id(sug) == ""
    assert validate_bundle_id("com.bad_name.app") != "" and validate_bundle_id("single") != ""


def test_certificate_and_p12_inspection_keeps_no_private_key(tmp_path):
    key, cert = make_cert("Apple Distribution: Test Org (ABCDE12345)", "ABCDE12345")
    info = apple.inspect_certificate(cert.public_bytes(Encoding.PEM))
    assert (info["kind"], info["team_id"], info["source"]) == ("distribution", "ABCDE12345", "certificate")
    assert info["sha256"].replace(":", "").lower() == hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest()
    p12 = pkcs12.serialize_key_and_certificates(b"n", key, cert, None, serialization.BestAvailableEncryption(TEST_PW.encode()))
    info2 = apple.inspect_certificate(p12, TEST_PW)
    assert info2["private_key_present"] and info2["sha256"] == info["sha256"]
    assert "PRIVATE" not in json.dumps(info2) and TEST_PW not in json.dumps(info2)
    with pytest.raises(apple.AppleError, match="password"):
        apple.inspect_certificate(p12, "wrong")
    with pytest.raises(apple.AppleError):
        apple.inspect_certificate(b"garbage")
    k2, dev = make_cert("Apple Development: Someone (XYZ)", "ABCDE12345")
    assert apple.inspect_certificate(dev.public_bytes(Encoding.DER))["kind"] == "development"


def test_provisioning_profile_inspection_and_relationships():
    _, cert = make_cert("Apple Distribution: Test Org (ABCDE12345)", "ABCDE12345")
    prof = apple.inspect_provisioning_profile(make_profile_file(cert))
    assert (prof["team_id"], prof["bundle_id"], prof["kind"]) == ("ABCDE12345", "com.test.app", "app_store")
    assert prof["certificate_sha256"] == [apple.inspect_certificate(cert.public_bytes(Encoding.DER))["sha256"]]
    assert "aps-environment" in prof["capabilities"]
    assert apple.inspect_provisioning_profile(make_profile_file(cert, kind="development"))["kind"] == "development"
    assert apple.inspect_provisioning_profile(make_profile_file(cert, kind="ad_hoc"))["kind"] == "ad_hoc"
    with pytest.raises(apple.AppleError):
        apple.inspect_provisioning_profile(b"no plist here")
    assert apple.bundle_matches("com.acme.*", "com.acme.game") and not apple.bundle_matches("com.acme.game", "com.acme.other")

    p = Profile(name="Apple Test", apple_bundle_id="com.test.app")
    p.platforms["ios"].update(enabled=True)
    p.v11.apple_team_id = "ABCDE12345"
    p.v11.apple_certs = [apple.inspect_certificate(cert.public_bytes(Encoding.DER))]
    p.v11.apple_profiles = [prof]
    assert not [c for c in apple.apple_checks(p) if c.status == "fail"]
    p.apple_bundle_id = "com.other.app"
    p.v11.apple_team_id = "ZZZZZ99999"
    fails = " ".join(c.text() for c in apple.apple_checks(p) if c.status == "fail")
    assert "not this project's bundle identifier" in fails and "Team ID ABCDE12345" in fails
    gone = apple.apple_checks(p, now=datetime.now(timezone.utc) + timedelta(days=4000))
    assert any("expired" in c.text() for c in gone if c.status == "fail")
    assert any("macOS" in c.detail for c in apple.apple_checks(p) if c.title == "Where Apple signing happens")


# --- profiles & prompt -------------------------------------------------------------------------------

def test_profile_compatibility_and_schema(store):
    old = Profile(name="Old", android_package="com.test.old")
    assert old.to_dict()["schema_version"] == 1 and "v11" not in old.to_dict()
    store.save(old)
    assert store.load(old.id).to_dict() == old.to_dict()
    p = play_profile()
    p.v11.play_signing_sha256 = fp(4)
    p.v11.apple_certs = [{"kind": "distribution", "sha256": fp(5)}]
    d = p.to_dict()
    assert d["schema_version"] == 2 and d["v11"]["play_signing_sha256"] == fp(4)
    store.save(p)
    back = store.load(p.id)
    assert back.v11.play_signing_sha256 == fp(4) and back.v11.apple_certs == p.v11.apple_certs
    assert back.build_number == 1 and back.android_package == "com.test.playtest"


def test_prompt_labels_unverified_and_contains_no_secrets():
    p = play_profile()
    p.v11.project_kind = "existing"
    p.v11.discovered = {"version_code": 57, "android_package": "com.test.playtest"}
    p.build_number = 57
    p.v11.play_signing_sha256 = fp(3)
    p.platforms["ios"].update(enabled=True)
    p.apple_bundle_id = "com.test.playtest"
    p.v11.apple_team_id = "ABCDE12345"
    direct = {"alias": "k", "fingerprint_sha256": fp(1), "fingerprint_sha1": "AA", "store_type": "PKCS12"}
    up = {"alias": "u", "fingerprint_sha256": fp(2), "fingerprint_sha1": "BB", "store_type": "PKCS12"}
    text = generate_prompt(p, direct, up)
    assert "GOOGLE PLAY SIGNING" in text and "APPLE SIGNING AND PROVISIONING" in text
    assert "NOT verified by the manager" in text and "macOS runner" in text
    assert "PLAY_UPLOAD_KEYSTORE_BASE64" in text and fp(2) in text and fp(3) in text
    assert "Continue build numbering from 57" in text
    low = text.lower()
    assert "private key" in low and TEST_PW.lower() not in low and "-----begin" not in low
    assert "do not upload to google play" in low
    # nothing changes for a profile with no v1.1 data
    plain = Profile(name="Plain", android_package="com.test.plain")
    plain.platforms["android"]["enabled"] = True
    assert "GOOGLE PLAY SIGNING" not in generate_prompt(plain, direct)


def test_play_secret_names_follow_key_relationship():
    p = play_profile()
    same, other = Rec(fp(1)), Rec(fp(2), rid="c" * 32)
    assert play_upload_names(p, same, same)["key_alias"] == "ANDROID_RELEASE_KEY_ALIAS"
    assert play_upload_names(p, same, other) == PLAY_UPLOAD_NAMES
