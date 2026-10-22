"""Verify artifacts written by the Android (Kotlin) parity test with the Windows app's code and keytool.

Usage: python tools/check_parity.py <parity-dir>
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hag_bsm import android, backup  # noqa: E402
from hag_bsm.tools import detect_tools  # noqa: E402


def main(parity_dir):
    out = Path(parity_dir) / "kotlin"
    meta = json.loads((out / "kt_backup.json").read_text("utf-8"))
    tools = detect_tools()
    if not tools.has_keytool:
        print("keytool is required", file=sys.stderr)
        return 1

    cert = android.read_certificate(tools, out / "kt_keystore.jks", meta["store_password"], meta["alias"])
    android.verify_key_access(tools, out / "kt_keystore.jks", meta["store_password"], meta["alias"], meta["store_password"])
    assert cert.sha256 == meta["fingerprint"], (cert.sha256, meta["fingerprint"])

    result = backup.verify_backup(out / "kt_backup.hagbackup", meta["passphrase"], tools, meta["fingerprint"])
    assert result.ok, result.message
    print("Parity OK: keytool opens the Kotlin-generated PKCS12 keystore and the Python app restores "
          "the Kotlin-made backup with a matching fingerprint.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
