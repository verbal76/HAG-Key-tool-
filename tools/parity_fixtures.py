"""Produce fixtures from the Windows (Python) app for the Android (Kotlin) parity tests.

Usage: python tools/parity_fixtures.py <output-dir>

Writes sample profiles with their expected prompts and validation results, a profile export, and a
real signing identity + encrypted backup created with keytool. Test-only keys; never commit them.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hag_bsm import backup  # noqa: E402
from hag_bsm.model import PLATFORMS, Profile  # noqa: E402
from hag_bsm.profiles import ProfileStore  # noqa: E402
from hag_bsm.prompt import generate_prompt  # noqa: E402
from hag_bsm.tools import detect_tools  # noqa: E402
from hag_bsm.validation import validate_profile  # noqa: E402
from hag_bsm.vault import IdentityVault  # noqa: E402

PASSPHRASE = "parity passphrase 42"
FP = "4F:7E:BE:36:8B:9F:12:55:82:10:EE:99:07:75:48:33:50:4C:C4:8D:21:45:23:4E:E9:19:19:2F:96:0C:44:0D"


def samples():
    def p(name, *plats, **kw):
        prof = Profile(name=name, android_package="com.hotatticgames.parity", apple_bundle_id="com.hotatticgames.parity",
                       **kw)
        for k in plats:
            prof.platforms[k]["enabled"] = True
        return prof

    out = {}
    for spec in PLATFORMS:
        out[f"only_{spec.key}"] = (p(f"Only {spec.label}", spec.key, stores=["private"]), "")
    mixed = p("Backrooms Survivor", "android", "windows", "linux", version="1.2.3", build_number=15,
              stores=["google_play", "steam"], release_channel="beta")
    mixed.platforms["android"]["formats"] = ["apk", "aab"]
    out["mixed_with_fingerprint"] = (mixed, FP)
    allp = p("Everything Ünïcode Game", *[s.key for s in PLATFORMS], release_channel="production",
             stores=["google_play", "app_store", "steam"], macos_bundle_id="com.hotatticgames.parity.mac",
             desktop_app_id="com.hotatticgames.parity.desktop")
    allp.secret_use_suffix, allp.secret_suffix = True, 3
    allp.platforms["macos"]["formats"] = ["app", "dmg"]
    out["all_platforms_suffix"] = (allp, FP)
    bad = p("", "android", "ios", version="1.02", build_number=0, stores=["private", "steam"])
    bad.android_package, bad.apple_bundle_id = "com.class.x", "bad_id"
    bad.icon_path = "/definitely/missing/icon.png"
    bad.platforms["ios"]["formats"] = []
    out["invalid"] = (bad, "")
    out["no_platforms"] = (p("Nothing", stores=[]), "")
    return out


def main(out_dir):
    out = Path(out_dir)
    for sub in ("profiles", "prompts", "validation"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    for key, (prof, fp) in samples().items():
        (out / "profiles" / f"{key}.json").write_text(json.dumps(prof.to_dict(), indent=2, ensure_ascii=False), "utf-8")
        (out / "profiles" / f"{key}.fp").write_text(fp, "utf-8")
        issues = validate_profile(prof)
        (out / "validation" / f"{key}.json").write_text(
            json.dumps([[i.level, i.field, i.message] for i in issues], ensure_ascii=False, indent=1), "utf-8")
        if not any(i.level == "error" for i in issues):
            (out / "prompts" / f"{key}.txt").write_bytes(
                generate_prompt(prof, {"fingerprint_sha256": fp} if fp else None).encode("utf-8"))

    mixed = samples()["mixed_with_fingerprint"][0]
    export = out / "export.json"
    export.unlink(missing_ok=True)
    ProfileStore.export_to(mixed, export, identity_summary={"alias": "x", "fingerprint_sha256": FP})

    tools = detect_tools()
    if not tools.has_keytool:
        print("keytool not found: skipping identity/backup fixtures", file=sys.stderr)
        return 0
    work = Path(tempfile.mkdtemp(prefix="hagbsm-parity-"))
    vault = IdentityVault(work / "identities", work)
    rec = vault.generate(tools, "Parity Game", "parity_release", "parity-release.jks", "CN=Hot Attic Games")
    dest = out / "py_backup.hagbackup"
    dest.unlink(missing_ok=True)
    result = backup.create_backup(vault, rec.id, dest, PASSPHRASE, tools, scrypt_n=2 ** 12)
    assert result.ok, result.message
    creds = vault.credentials(rec.id)
    (out / "py_backup.json").write_text(json.dumps({
        "passphrase": PASSPHRASE, "fingerprint": rec.fingerprint_sha256, "alias": rec.alias,
        "store_password": creds.store_password}), "utf-8")
    print(f"Wrote parity fixtures to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.environ["HAGBSM_PARITY_DIR"]))
