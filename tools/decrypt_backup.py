"""Decrypt a Build & Signing Manager backup without the application.

Usage:  python decrypt_backup.py <backup.hagbackup> <output-folder>
Needs:  Python 3.8+ and the `cryptography` package (pip install cryptography).

The passphrase is read from the terminal (or stdin). The output folder must not exist yet;
it will contain the keystore, credentials.json and RECOVERY.txt. Keep it private and delete
it when you no longer need it.
"""

import base64
import getpass
import io
import json
import sys
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"HAGBSM-BACKUP 1\n"


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    data = Path(argv[1]).read_bytes()
    out = Path(argv[2])
    if out.exists():
        print(f"{out} already exists; choose a new folder.", file=sys.stderr)
        return 2
    if not data.startswith(MAGIC):
        print("Not a Build & Signing Manager backup.", file=sys.stderr)
        return 1
    end = data.index(b"\n", len(MAGIC))
    header_bytes = data[len(MAGIC):end + 1]
    header = json.loads(header_bytes)
    passphrase = getpass.getpass("Backup passphrase: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\r\n")
    key = Scrypt(salt=base64.b64decode(header["salt"]), length=32, n=header["n"], r=header["r"],
                 p=header["p"]).derive(passphrase.encode("utf-8"))
    try:
        plain = AESGCM(key).decrypt(base64.b64decode(header["nonce"]), data[end + 1:], MAGIC + header_bytes)
    except Exception:
        print("Wrong passphrase, or the file is damaged.", file=sys.stderr)
        return 1
    out.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(plain)) as zf:
        for name in zf.namelist():
            target = (out / name).resolve()
            if out.resolve() not in target.parents:
                raise SystemExit(f"Refusing unsafe path in archive: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
    print(f"Decrypted to {out}. See RECOVERY.txt.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
