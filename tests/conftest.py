import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hag_bsm.paths import AppPaths  # noqa: E402
from hag_bsm.profiles import ProfileStore  # noqa: E402
from hag_bsm.tools import detect_tools  # noqa: E402
from hag_bsm.vault import IdentityVault  # noqa: E402

TEST_SCRYPT_N = 2 ** 12


@pytest.fixture
def paths(tmp_path):
    # Spaces and non-ASCII characters on purpose: Windows user folders often contain them.
    base = tmp_path / "Ünïcode user dir"
    return AppPaths(base / "config", base / "vault")


@pytest.fixture
def store(paths):
    return ProfileStore(paths.profiles_dir, paths.deleted_profiles_dir)


@pytest.fixture
def vault(paths):
    return IdentityVault(paths.identities_dir, paths.vault_root)


@pytest.fixture(scope="session")
def tools():
    return detect_tools()


@pytest.fixture
def keytool_tools(tools):
    if not tools.has_keytool:
        pytest.skip("keytool (JDK) not available")
    return tools


def keytool(tools, *args, env=None):
    full_env = dict(os.environ, **(env or {}))
    return subprocess.run([str(tools.keytool), *map(str, args)], env=full_env, capture_output=True, text=True)


def make_keystore(tools, path, alias, password, storetype="PKCS12", key_password=None, keyalg="RSA", keysize="2048"):
    res = keytool(tools, "-genkeypair", "-keystore", path, "-storetype", storetype, "-alias", alias,
                  "-keyalg", keyalg, "-keysize", keysize, "-validity", "365", "-dname", "CN=Test",
                  "-storepass:env", "SP", "-keypass:env", "KP",
                  env={"SP": password, "KP": key_password or password})
    assert res.returncode == 0, res.stderr
    return Path(path)


def make_unsigned_apk(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00placeholder")
        zf.writestr("classes.dex", b"dex\n035\x00")
    return Path(path)


def jarsign(tools, apk, keystore, password, alias):
    jarsigner = Path(tools.keytool).with_name("jarsigner" + (".exe" if os.name == "nt" else ""))
    if not jarsigner.is_file():
        found = shutil.which("jarsigner")
        if not found:
            pytest.skip("jarsigner not available")
        jarsigner = Path(found)
    res = subprocess.run([str(jarsigner), "-keystore", str(keystore), "-storepass:env", "SP",
                          "-digestalg", "SHA-256", "-sigalg", "SHA256withRSA", str(apk), alias],
                         env=dict(os.environ, SP=password), capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
