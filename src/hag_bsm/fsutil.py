"""Small filesystem helpers: atomic replacement and private directories."""

import json
import os
import sys
import tempfile
from pathlib import Path


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(path, 0o700)
    return path


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write `data` to `path` so readers see either the old or the new file, never a partial one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, obj) -> None:
    atomic_write_bytes(path, (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def write_new_file(path: Path, data: bytes) -> None:
    """Create `path` with `data`; refuse if it already exists. Removes the file again if writing fails."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as fh:
        try:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        except BaseException:
            fh.close()
            path.unlink(missing_ok=True)
            raise
